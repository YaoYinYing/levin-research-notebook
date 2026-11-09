#!/usr/bin/env python3
"""Verify a packaged ``*.levin-plugin.tgz`` against itself — no Levin app needed.

This is the closest thing to the Creator's own ``package`` step that can run on a
runner: the published tarball carries its own vendored ``levin_plugin_sdk`` and its
own compiled ``.levin-plugin/plugin.json``, so the consistency check the Creator
performs (``validate_compiled_plugin``) can be replayed from the artefact alone.

Checks
------
1. The archive extracts without escaping its directory, and contains the files a
   Levin plugin package must contain (plugin.json, sdk.json, .mcp.json, the server
   entrypoint, the vendored SDK, the skill tree, plugin_spec.py).
2. ``.levin-plugin/plugin.json`` version, ``.levin-plugin/sdk.json`` version,
   ``plugin_spec.py`` version and the release tag all agree.
3. ``plugin_spec.py`` imports against the package's own vendored SDK and declares
   the eight ``research_record_*`` tools.
4. ``levin_plugin_sdk.compiler.validate_compiled_plugin`` accepts the package (this
   is the Creator's own check: manifest, sdk metadata, .mcp.json, entrypoint and
   the vendored SDK file set must all be the deterministic output of the spec).
5. Every SKILL.md in the package is within the 12000-character limit.

Exit 0 only when all five hold. ``--expect-version`` is optional; when given, the
package version must equal it (use the release tag to catch a mislabelled asset).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tarfile
import tempfile
from pathlib import Path

MAX_SKILL_CHARS = 12000
REQUIRED_FILES = (
    ".mcp.json",
    ".levin-plugin/plugin.json",
    ".levin-plugin/sdk.json",
    "mcp/runner/plugin_spec.py",
    "mcp/runner/server.py",
    "mcp/runner/setup_runtime.py",
)
REQUIRED_PREFIXES = (
    ".levin-plugin/vendor/python/levin_plugin_sdk/",
    "skills/",
)
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


def fail(message: str) -> None:
    print(f"FAIL  {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"ok    {message}")


def extract(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                fail(f"archive member escapes the extraction root: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(destination, filter="data")
        else:  # Python < 3.11.4
            tar.extractall(destination)
    return destination


def spec_version(root: Path) -> str:
    path = root / "mcp/runner/plugin_spec.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "Plugin":
                continue
            for keyword in node.keywords:
                if keyword.arg == "version":
                    return str(ast.literal_eval(keyword.value))
    fail("plugin_spec.py has no Plugin(version=...)")


def check_contents(root: Path) -> None:
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            fail(f"package is missing {relative}")
    for prefix in REQUIRED_PREFIXES:
        if not (root / prefix).is_dir():
            fail(f"package is missing the {prefix} directory")
    skills = sorted(root.glob("skills/*/SKILL.md"))
    if not skills:
        fail("package has no skills/*/SKILL.md")
    ok(f"package contains {len(REQUIRED_FILES)} required files, the vendored SDK and {len(skills)} SKILL.md")


def check_versions(root: Path, tag: str | None) -> str:
    manifest = json.loads((root / ".levin-plugin/plugin.json").read_text(encoding="utf-8"))
    metadata = json.loads((root / ".levin-plugin/sdk.json").read_text(encoding="utf-8"))
    versions = {
        "plugin_spec.py": spec_version(root),
        ".levin-plugin/plugin.json": str(manifest.get("version")),
        ".levin-plugin/sdk.json": str((metadata.get("plugin") or {}).get("version")),
    }
    distinct = set(versions.values())
    if len(distinct) != 1:
        fail(f"package versions disagree: {versions}")
    version = distinct.pop()
    ok(f"package version {version} agrees across plugin_spec.py, plugin.json and sdk.json")
    if tag:
        normalised = tag[1:] if tag.startswith("v") else tag
        if normalised != version:
            fail(f"release tag {tag!r} does not match the packaged version {version}")
        ok(f"release tag {tag} matches the packaged version")
    return version


def check_spec_import(root: Path) -> None:
    vendor = root / ".levin-plugin/vendor/python"
    if not (vendor / "levin_plugin_sdk/__init__.py").is_file():
        fail(f"package has no vendored SDK at {vendor}")
    sys.path.insert(0, str(vendor))
    sys.path.insert(0, str(root / "mcp/runner"))
    sys.dont_write_bytecode = True
    import importlib.util

    spec_path = root / "mcp/runner/plugin_spec.py"
    spec = importlib.util.spec_from_file_location("packaged_plugin_spec", spec_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = module.plugin
    declared = {tool.name for tool in plugin.tools}
    missing = [name for name in EXPECTED_TOOLS if name not in declared]
    if missing:
        fail(f"packaged plugin_spec.py does not declare {missing}")
    ok(f"plugin_spec.py imports against the packaged SDK and declares {len(EXPECTED_TOOLS)} tools")


def check_compiled(root: Path) -> None:
    try:
        from levin_plugin_sdk.compiler import validate_compiled_plugin
    except ImportError as error:
        fail(f"cannot import the packaged SDK compiler: {error}")
    import importlib.util

    spec_path = root / "mcp/runner/plugin_spec.py"
    spec = importlib.util.spec_from_file_location("packaged_plugin_spec_validate", spec_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        validate_compiled_plugin(module.plugin, root)
    except Exception as error:  # noqa: BLE001 - the Creator's own message is the finding
        fail(f"Creator-level package validation rejected the artefact: {error}")
    ok("Creator-level validation passed: manifest, sdk metadata, .mcp.json, entrypoint and SDK file set are deterministic")


def check_skills(root: Path) -> None:
    for skill in sorted(root.glob("skills/*/SKILL.md")):
        size = len(skill.read_text(encoding="utf-8"))
        if size > MAX_SKILL_CHARS:
            fail(f"{skill.relative_to(root)}: {size} characters exceeds {MAX_SKILL_CHARS}")
        ok(f"{skill.relative_to(root)}: {size}/{MAX_SKILL_CHARS} characters")
    text = (root / "README.md")
    if text.is_file():
        ok("README.md is present in the package")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", help="path to a .levin-plugin.tgz")
    parser.add_argument("--expect-version", default=None, help="e.g. the release tag v0.11.2")
    parser.add_argument("--keep", action="store_true", help="extract into a kept temp dir and print it")
    args = parser.parse_args()

    archive = Path(args.archive).resolve()
    if not archive.is_file():
        fail(f"archive not found: {archive}")
    print(f"checking {archive.name} ({archive.stat().st_size} bytes)")

    if args.keep:
        destination = Path(tempfile.mkdtemp(prefix="levin-pkg-"))
        root = extract(archive, destination)
        print(f"extracted to {root}")
    else:
        with tempfile.TemporaryDirectory(prefix="levin-pkg-") as workspace:
            root = extract(archive, Path(workspace))
            print("-" * 70)
            check_contents(root)
            check_versions(root, None if args.expect_version is None else args.expect_version)
            check_spec_import(root)
            check_compiled(root)
            check_skills(root)
        print("-" * 70)
        print("packaged artefact is internally consistent; no Levin app needed")
        return 0

    print("-" * 70)
    check_contents(root)
    check_versions(root, args.expect_version)
    check_spec_import(root)
    check_compiled(root)
    check_skills(root)
    print("-" * 70)
    print("packaged artefact is internally consistent; no Levin app needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
