#!/usr/bin/env python3
"""Structure gates that the Levin validator enforces and that run without the app.

Gates
-----
1. ``skills/**/SKILL.md`` is at most MAX_SKILL_CHARS characters (hard limit 12000).
2. Every relative link/image in SKILL.md resolves to a real file, and every
   ``#fragment`` resolves to a heading in the target markdown file.
3. The recorded version agrees across ``mcp/runner/plugin_spec.py``, ``README.md``
   and the SKILL.md frontmatter (which has no version key today; if one is added
   it must match).
4. The SKILL.md frontmatter declares a ``name`` equal to its skill directory.

Exit code 0 = every gate passed. Any failure prints the offending file and
exits 1. Warnings never fail the run.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

MAX_SKILL_CHARS = 12000
ROOT = Path(__file__).resolve().parents[2]

failures: list[str] = []
warnings: list[str] = []
passed: list[str] = []


def fail(message: str) -> None:
    failures.append(message)
    print(f"FAIL  {message}")


def warn(message: str) -> None:
    warnings.append(message)
    print(f"WARN  {message}")


def ok(message: str) -> None:
    passed.append(message)
    print(f"ok    {message}")


# --------------------------------------------------------------------------- #
# SKILL.md frontmatter + length
# --------------------------------------------------------------------------- #
def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end]
    body = text[end + 4:]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields, body


def github_slug(heading: str) -> str:
    """Approximate GitHub's heading anchor algorithm."""
    text = heading.strip().lower()
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def headings_and_anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    slugs: set[str] = set()
    seen: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            base = github_slug(match.group(2))
            count = seen.get(base, 0)
            seen[base] = count + 1
            slugs.add(base if count == 0 else f"{base}-{count}")
        for attr in re.finditer(r"""(?:id|name)\s*=\s*["']([^"']+)["']""", line):
            slugs.add(attr.group(1))
    return slugs


LINK_RE = re.compile(r"!?\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)", re.S)


def relative_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    _, body = split_frontmatter(text)
    body = re.sub(r"(?ms)^```.*?^```", "", body)
    body = re.sub(r"(?ms)^~~~.*?^~~~", "", body)
    body = re.sub(r"`[^`\n]*`", "", body)
    targets = []
    for match in LINK_RE.finditer(body):
        target = match.group("target")
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(("#", "//")):
            continue
        targets.append(target)
    return targets


def resolve_target(source: Path, target: str) -> tuple[Path, str]:
    path_part, _, fragment = target.partition("#")
    resolved = (source.parent / path_part).resolve() if path_part else source.resolve()
    return resolved, fragment


# --------------------------------------------------------------------------- #
# Version agreement
# --------------------------------------------------------------------------- #
SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"


def spec_version() -> str | None:
    path = ROOT / "mcp" / "runner" / "plugin_spec.py"
    if not path.is_file():
        fail(f"missing {path.relative_to(ROOT)}")
        return None
    match = re.search(rf"version\s*=\s*['\"](?P<v>{SEMVER})['\"]", path.read_text(encoding="utf-8"))
    if not match:
        fail("mcp/runner/plugin_spec.py: could not find version='X.Y.Z'")
        return None
    return match.group("v")


def readme_version() -> str | None:
    path = ROOT / "README.md"
    if not path.is_file():
        fail("missing README.md")
        return None
    text = path.read_text(encoding="utf-8")
    _, body = split_frontmatter(text)
    patterns = (
        rf"\bv(?P<v>{SEMVER})\b",
        rf"(?i)version[^0-9]{{0,20}}(?P<v>{SEMVER})",
    )
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return match.group("v")
    return None


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #
def gate_skill_length(skill_files: list[Path]) -> None:
    if not skill_files:
        fail("no skills/**/SKILL.md found")
        return
    for skill in skill_files:
        text = skill.read_text(encoding="utf-8")
        size = len(text)
        rel = skill.relative_to(ROOT)
        if size > MAX_SKILL_CHARS:
            fail(f"{rel}: {size} characters exceeds the {MAX_SKILL_CHARS} limit by {size - MAX_SKILL_CHARS}")
        else:
            ok(f"{rel}: {size}/{MAX_SKILL_CHARS} characters ({MAX_SKILL_CHARS - size} left)")


def gate_skill_links(skill_files: list[Path]) -> None:
    for skill in skill_files:
        rel = skill.relative_to(ROOT)
        targets = relative_links(skill)
        if not targets:
            warn(f"{rel}: declares no relative links")
            continue
        for target in targets:
            resolved, fragment = resolve_target(skill, target)
            if not resolved.exists():
                fail(f"{rel}: link target does not exist: {target}")
                continue
            if fragment and resolved.suffix == ".md":
                anchors = headings_and_anchors(resolved)
                if fragment not in anchors:
                    fail(f"{rel}: anchor not found in {resolved.relative_to(ROOT)}: #{fragment}")
                    continue
            ok(f"{rel}: {target} resolves")


def gate_skill_reference_tree(skill_files: list[Path]) -> None:
    """Warn about reference files the skill never links to (dead weight in the tree)."""
    for skill in skill_files:
        linked = set()
        for target in relative_links(skill):
            resolved, _ = resolve_target(skill, target)
            linked.add(resolved)
        for directory in ("references", "examples", "scripts"):
            base = skill.parent / directory
            if not base.is_dir():
                continue
            for child in sorted(base.rglob("*")):
                if child.is_file() and child.resolve() not in linked:
                    warn(f"{skill.relative_to(ROOT)}: {child.relative_to(ROOT)} is not linked from SKILL.md")


def gate_versions(skill_files: list[Path]) -> None:
    spec = spec_version()
    readme = readme_version()
    if spec:
        ok(f"plugin_spec.py version = {spec}")
    if readme:
        ok(f"README.md version = {readme}")
    if spec and readme and spec != readme:
        fail(f"version mismatch: plugin_spec.py says {spec}, README.md says {readme}")

    for skill in skill_files:
        fields, _ = split_frontmatter(skill.read_text(encoding="utf-8"))
        rel = skill.relative_to(ROOT)
        name = fields.get("name")
        if not name:
            fail(f"{rel}: frontmatter has no name")
        elif name != skill.parent.name:
            fail(f"{rel}: frontmatter name {name!r} != directory {skill.parent.name!r}")
        else:
            ok(f"{rel}: frontmatter name = {name}")
        if not fields.get("description"):
            fail(f"{rel}: frontmatter has no description")
        if "version" in fields:
            if spec and fields["version"].strip("v") != spec:
                fail(f"{rel}: frontmatter version {fields['version']!r} != plugin_spec.py {spec}")
            else:
                ok(f"{rel}: frontmatter version = {fields['version']}")
        else:
            warn(f"{rel}: frontmatter has no version key (checked against README/plugin_spec only)")


def main() -> int:
    print(f"structure gates in {ROOT}")
    print(f"python {sys.version.split()[0]} on {sys.platform}")
    print("-" * 70)
    skill_files = sorted((ROOT / "skills").glob("*/SKILL.md"))
    gate_skill_length(skill_files)
    gate_skill_links(skill_files)
    gate_skill_reference_tree(skill_files)
    gate_versions(skill_files)
    print("-" * 70)
    print(f"{len(passed)} checks passed, {len(warnings)} warnings, {len(failures)} failures")
    if failures:
        print("\nStructure gates FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
