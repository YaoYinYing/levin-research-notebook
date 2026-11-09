#!/usr/bin/env python3
"""Package dry-run without the Levin Creator CLI.

The Creator lives inside the macOS app bundle and cannot be assumed on a runner,
so this script does the parts that need no app:

1. import ``mcp/runner/plugin_spec.py`` (needs ``levin_plugin_sdk`` on the path)
   and assert it exports ``plugin = Plugin(...)``;
2. assert the plugin declares the eight ``research_record_*`` tools plus the
   ``preflight`` metadata probe, each with a handler that actually exists in
   ``mcp/runner/adapter.py``;
3. validate every tool ``input_schema`` against the JSON Schema 2020-12
   metaschema with the pinned ``jsonschema``;
4. if a compiled ``.levin-plugin/plugin.json`` exists, re-run the SDK's own
   ``validate_compiled_plugin`` (the same check the Creator performs) to prove
   the committed manifest still matches the spec.

Exit 0 if the spec is internally consistent and importable. Step 4 is skipped
with a clear message when ``.levin-plugin/`` is absent, which is the normal
state of a fresh clone.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

EXPECTED_TOOLS = (
    "research_record_init",
    "research_record_checkpoint",
    "research_record_register_artifact",
    "research_record_register_run",
    "research_record_validate",
    "research_record_finalize",
    "research_record_prune_reports",
    "research_record_index",
)
EXPECTED_PROBES = ("preflight",)
SEMVER_PARTS = 3


def fail(message: str) -> None:
    print(f"FAIL  {message}")
    raise SystemExit(1)


def ensure_sdk(root: Path) -> None:
    """Put the vendored SDK on sys.path, or fail with the actionable reason."""
    vendor = root / ".levin-plugin" / "vendor" / "python"
    if (vendor / "levin_plugin_sdk" / "__init__.py").is_file():
        if str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        return
    try:
        import levin_plugin_sdk  # noqa: F401  (already importable, e.g. installed elsewhere)
    except ImportError:
        fail(
            "levin_plugin_sdk is not importable. .levin-plugin/ is gitignored, so a fresh clone has "
            "no vendored SDK; run .github/scripts/fetch_plugin_sdk.py --root . first, or set "
            "PYTHONPATH to an existing .levin-plugin/vendor/python. The SDK is not on PyPI."
        )


def load_plugin(root: Path):
    spec_path = root / "mcp" / "runner" / "plugin_spec.py"
    if not spec_path.is_file():
        fail(f"missing {spec_path.relative_to(root)}")
    ensure_sdk(root)
    sys.path.insert(0, str(spec_path.parent))
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("plugin_spec_under_test", spec_path)
    if spec is None or spec.loader is None:
        fail(f"could not build an import spec for {spec_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = getattr(module, "plugin", None)
    if plugin is None:
        fail("mcp/runner/plugin_spec.py does not export `plugin`")
    return plugin


def check_identity(plugin) -> dict:
    if plugin.id != "levin-research-notebook":
        fail(f"plugin.id is {plugin.id!r}, expected 'levin-research-notebook'")
    parts = str(plugin.version).split("-")[0].split(".")
    if len(parts) != SEMVER_PARTS or not all(p.isdigit() for p in parts):
        fail(f"plugin.version {plugin.version!r} is not strict semver")
    runtime = plugin.runtime
    if runtime is None:
        fail("plugin declares no runtime")
    if not runtime.packages:
        fail("runtime declares no packages")
    if not runtime.verify:
        fail("runtime declares no verify command")
    print(f"ok    plugin {plugin.id} {plugin.version} runtime={runtime.id} python={runtime.python}")
    print(f"ok    runtime packages: {', '.join(runtime.packages)}")
    return {"id": plugin.id, "version": plugin.version,
            "packages": list(runtime.packages), "python": runtime.python}


def check_tools(plugin, root: Path) -> list[str]:
    by_name = {tool.name: tool for tool in plugin.tools}
    missing = [name for name in EXPECTED_TOOLS if name not in by_name]
    if missing:
        fail(f"plugin_spec.py does not declare these tools: {missing} (declared: {sorted(by_name)})")
    probes = [name for name, tool in by_name.items() if getattr(tool, "mode", "") == "metadata_probe"]
    for name in EXPECTED_PROBES:
        if name not in by_name:
            fail(f"missing metadata probe {name!r}")
        if name not in probes:
            fail(f"tool {name!r} exists but is not a metadata_probe (mode={by_name[name].mode!r})")
    print(f"ok    {len(EXPECTED_TOOLS)} research_record_* tools declared")
    print(f"ok    metadata probes: {probes}")

    adapter_path = root / "mcp" / "runner" / "adapter.py"
    adapter_source = adapter_path.read_text(encoding="utf-8")
    for name in EXPECTED_TOOLS + EXPECTED_PROBES:
        tool = by_name[name]
        handler = getattr(tool, "handler", None) or ""
        module_name, _, function_name = handler.partition(":")
        if module_name != "adapter":
            fail(f"{name}: handler {handler!r} does not target adapter")
        if f"def {function_name}(" not in adapter_source:
            fail(f"{name}: adapter.py has no `def {function_name}(`")
    print(f"ok    every handler resolves to a real function in mcp/runner/adapter.py")
    return sorted(by_name)


def check_schemas(plugin) -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("WARN  jsonschema is not installed; schema metaschema check skipped")
        return 0
    count = 0
    for tool in plugin.tools:
        schema = tool.input_schema
        if not isinstance(schema, dict):
            fail(f"{tool.name}: input_schema is not an object")
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as error:  # noqa: BLE001 - report the validator's own message
            fail(f"{tool.name}: input_schema is not a valid 2020-12 schema: {error}")
        count += 1
    print(f"ok    {count} tool input schemas are valid JSON Schema 2020-12")
    return count


def check_compiled(plugin, root: Path) -> None:
    manifest = root / ".levin-plugin" / "plugin.json"
    if not manifest.is_file():
        print("skip  no .levin-plugin/plugin.json (gitignored; expected on a fresh clone).")
        print("      The compiled-manifest consistency check needs the Creator CLI output.")
        return
    try:
        from levin_plugin_sdk.compiler import validate_compiled_plugin
    except ImportError as error:
        fail(f"cannot import the SDK compiler to validate the compiled manifest: {error}")
    try:
        validate_compiled_plugin(plugin, root)
    except Exception as error:  # noqa: BLE001
        fail(f"compiled manifest is stale or inconsistent: {error}")
    print("ok    .levin-plugin/plugin.json matches plugin_spec.py and the SDK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--summary", default=None, help="write a JSON summary here")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    print(f"plugin spec dry-run in {root}")
    print(f"python {sys.version.split()[0]} on {sys.platform}")
    ensure_sdk(root)
    print(f"SDK: {importlib.util.find_spec('levin_plugin_sdk').origin}")
    print("-" * 70)

    plugin = load_plugin(root)
    identity = check_identity(plugin)
    tools = check_tools(plugin, root)
    schemas = check_schemas(plugin)
    print("-" * 70)
    check_compiled(plugin, root)
    print("-" * 70)
    print("plugin spec is consistent; no Levin app needed")
    if args.summary:
        Path(args.summary).write_text(json.dumps(
            {**identity, "tools": tools, "schemas_checked": schemas, "root": str(root)}, indent=2
        ) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
