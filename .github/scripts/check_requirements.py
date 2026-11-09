#!/usr/bin/env python3
"""Fail when .github/requirements-ci.txt drifts from plugin_spec.py's runtime pins.

The test job installs from .github/requirements-ci.txt because pip/uv cannot read
the pins out of ``PythonRuntime(packages=(...))``. That duplication is only safe
if it is checked: this script parses the tuple from ``plugin_spec.py`` with
``ast`` (no import, so no SDK needed) and compares it with the runtime section of
the requirements file.

The requirements file is split into two zones by the marker comment
``# --- runtime pins (mirror of plugin_spec.py) ---``: everything before it is
the runtime mirror, everything after it is test-only tooling.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "mcp" / "runner" / "plugin_spec.py"
REQUIREMENTS = ROOT / ".github" / "requirements-ci.txt"
MARKER = "# --- end of runtime pins ---"


def spec_packages() -> tuple[list[str], str]:
    source = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "PythonRuntime":
                continue
            for keyword in node.keywords:
                if keyword.arg == "packages":
                    return list(ast.literal_eval(keyword.value)), "runtime.packages"
    raise SystemExit("FAIL  plugin_spec.py has no PythonRuntime(packages=(...))")


def requirement_runtime_pins() -> list[str]:
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    pins: list[str] = []
    for line in lines:
        if MARKER in line:
            break
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            pins.append(stripped)
    return pins


def normalise(requirement: str) -> str:
    return requirement.replace("_", "-").strip().lower()


def main() -> int:
    declared, where = spec_packages()
    pinned = requirement_runtime_pins()
    print(f"plugin_spec.py {where}: {declared}")
    print(f"{REQUIREMENTS.relative_to(ROOT)}: {pinned}")

    problems: list[str] = []
    if [normalise(x) for x in declared] != [normalise(x) for x in pinned]:
        a = [normalise(x) for x in declared]
        b = [normalise(x) for x in pinned]
        for item in a:
            if item not in b:
                problems.append(f"declared in plugin_spec.py but missing from requirements: {item}")
        for item in b:
            if item not in a:
                problems.append(f"pinned in requirements but not declared in plugin_spec.py: {item}")
        if not problems:
            problems.append(f"same packages, different order: spec={a} requirements={b}")
    if MARKER not in REQUIREMENTS.read_text(encoding="utf-8"):
        problems.append(f"requirements file is missing the '{MARKER}' marker comment")

    if problems:
        print("\nFAIL  dependency pins have drifted:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"\nok    {len(declared)} runtime pins agree with plugin_spec.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
