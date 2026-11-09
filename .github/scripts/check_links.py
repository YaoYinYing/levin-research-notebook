#!/usr/bin/env python3
"""Offline Markdown link check for every tracked ``*.md`` in the repository.

Checks, with no network access:

* relative file links resolve on disk (``docs/x.md``, ``../README.md``, ``img.png``);
* ``#fragment`` links resolve to a heading anchor in the target file, including
  cross-file form ``some.md#Some-Heading``;
* links that escape the repository root are reported, because they cannot exist
  on a fresh clone;
* absolute ``http(s)`` links are counted but not fetched (this job is offline and
  must not depend on third-party uptime).

Exit code 0 = every relative link resolves. ``--strict-anchors`` (default on)
can be turned off with ``--no-anchors`` when a heading is deliberately unstable.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Never walk generated trees: .levin-plugin/ is build output, levin_scratch/ holds
# retained test workspaces (Markdown records written by the suite), dist/ holds
# packaged archives. A fresh clone has none of them, but a repo copy that already
# ran the tests does, and their links are not this repository's links to keep.
SKIP_DIRS = {".git", ".levin-plugin", "levin_scratch", "dist", "node_modules",
             "__pycache__", ".venv", ".idea", ".vscode"}
FENCE_RE = re.compile(r"(?ms)^[ \t]*(?:```|~~~).*?^[ \t]*(?:```|~~~)[ \t]*$")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
HTML_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
LINK_RE = re.compile(r"!?\[(?P<text>[^\]]*)\]\((?P<inner>[^)]*)\)", re.S)
REF_DEF_RE = re.compile(r"(?m)^[ ]{0,3}\[[^\]]+\]:\s*(?P<target>\S+)")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")


def slugify(heading: str) -> str:
    """Approximate GitHub's heading-anchor algorithm closely enough for CI."""
    text = heading.strip().lower()
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def anchors_of(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match:
            base = slugify(match.group("text"))
            count = seen.get(base, 0)
            seen[base] = count + 1
            anchors.add(base if count == 0 else f"{base}-{count}")
        for attr in re.finditer(r"""\b(?:id|name)\s*=\s*["']([^"']+)["']""", line):
            anchors.add(attr.group(1))
    return anchors


def markdown_files() -> list[Path]:
    """Tracked markdown if this is a git repo, otherwise every file on disk."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "*.md"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        files = [ROOT / name for name in out.split("\0") if name]
        if files:
            return sorted(files)
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(
        p for p in ROOT.rglob("*.md")
        if not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
    )


def strip_noise(text: str) -> str:
    text = HTML_COMMENT_RE.sub("", text)
    text = FENCE_RE.sub("", text)
    return INLINE_CODE_RE.sub("", text)


def targets_of(text: str) -> list[str]:
    cleaned = strip_noise(text)
    found: list[str] = []
    for match in LINK_RE.finditer(cleaned):
        inner = match.group("inner").strip()
        if not inner:
            continue
        target = inner.split()[0]
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        found.append(target)
    for match in REF_DEF_RE.finditer(cleaned):
        found.append(match.group("target"))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-anchors", action="store_true", help="skip #fragment verification")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    files = markdown_files()
    print(f"checking {len(files)} markdown file(s) under {ROOT}")
    print("-" * 70)

    failures: list[str] = []
    checked = 0
    external = 0
    anchor_cache: dict[Path, set[str]] = {}

    for source in files:
        rel_source = source.relative_to(ROOT)
        text = source.read_text(encoding="utf-8")
        for target in targets_of(text):
            if target.startswith(("mailto:", "tel:", "data:")) or SCHEME_RE.match(target):
                external += 1
                continue
            if target.startswith("#"):
                path_part, _, fragment = "", target[1:], target[1:]
                path_part = ""
            else:
                path_part, _, fragment = target.partition("#")
            checked += 1
            if path_part:
                resolved = (source.parent / path_part).resolve()
                try:
                    resolved.relative_to(ROOT)
                except ValueError:
                    failures.append(f"{rel_source}: `{target}` escapes the repository root")
                    continue
                if not resolved.exists():
                    failures.append(f"{rel_source}: `{target}` -> missing {resolved.relative_to(ROOT)}")
                    continue
            else:
                resolved = source.resolve()
            if fragment and not args.no_anchors and resolved.suffix.lower() in {".md", ".markdown"}:
                if resolved not in anchor_cache:
                    anchor_cache[resolved] = anchors_of(resolved)
                if fragment.lower() not in {a.lower() for a in anchor_cache[resolved]}:
                    failures.append(
                        f"{rel_source}: `{target}` -> no heading anchor #{fragment} in "
                        f"{resolved.relative_to(ROOT)}"
                    )
                    continue
            if args.verbose:
                print(f"ok    {rel_source}: {target}")

    print("-" * 70)
    print(f"{checked} relative link(s) checked, {external} external link(s) not fetched")
    if failures:
        print(f"\n{len(failures)} broken link(s):")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("all relative links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
