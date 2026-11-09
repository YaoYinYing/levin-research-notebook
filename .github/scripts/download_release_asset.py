#!/usr/bin/env python3
"""Download a released ``*.levin-plugin.tgz`` so it can be validated.

The Levin Creator CLI lives inside the macOS app bundle, so a runner cannot build
the package from the working tree. It can, however, verify the package that was
actually published — that artefact carries its own vendored SDK, which makes the
Creator's own consistency check replayable (see check_package.py).

Asset selection: the release tagged ``v<plugin_spec.py version>`` when it exists,
otherwise the newest release, with a warning on stderr. ``--tag`` overrides.

Writes the downloaded path and the tag to ``$GITHUB_ENV`` when that is set, so a
later step can call ``check_package.py --expect-version "$RELEASED_TAG"``.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
ASSET_SUFFIX = ".levin-plugin.tgz"


def log(message: str) -> None:
    print(f"[release] {message}", flush=True)


def fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[release] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def api(url: str, token: str | None) -> bytes:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "levin-ci"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def find_release(repo: str, tag: str | None, token: str | None) -> dict | None:
    url = f"{API}/repos/{repo}/releases/tags/{tag}" if tag else f"{API}/repos/{repo}/releases/latest"
    try:
        payload = json.loads(api(url, token))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        fail(f"could not query releases for {repo}: HTTP {error.code} {url}")
    except urllib.error.URLError as error:
        fail(f"could not reach the GitHub API for {repo}: {error.reason}")
    if payload.get("draft"):
        fail(f"release {payload.get('tag_name')} is a draft; its assets are not public")
    return payload


def spec_version(root: Path) -> str | None:
    """plugin_spec.py's version, read with ast so the SDK is not needed."""
    path = root / "mcp" / "runner" / "plugin_spec.py"
    if not path.is_file():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "Plugin":
                continue
            for keyword in node.keywords:
                if keyword.arg == "version":
                    return str(ast.literal_eval(keyword.value))
    return None


def choose_release(repo: str, root: Path, tag: str | None, token: str | None) -> dict:
    if tag:
        release = find_release(repo, tag if tag.startswith("v") else f"v{tag}", token)
        if release is None:
            fail(f"no release tagged {tag} in {repo}")
        return release

    version = spec_version(root)
    if version:
        release = find_release(repo, f"v{version}", token)
        if release is not None:
            log(f"using release v{version}, matching plugin_spec.py")
            return release
        log(f"plugin_spec.py is {version} but there is no v{version} release; using the newest")

    release = find_release(repo, None, token)
    if release is None:
        fail(
            f"{repo} has no published release. The packaged artefact exists only as a release "
            "asset, so this check cannot run until one is published."
        )
    if version and str(release.get("tag_name", "")).lstrip("v") != version:
        log(
            f"WARNING: plugin_spec.py is {version} but the newest release is "
            f"{release.get('tag_name')}. This job validates the last published package, not HEAD; "
            f"publish a v{version} asset to test what you would ship."
        )
    return release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--tag", default=None)
    parser.add_argument("--output", default="released.levin-plugin.tgz")
    parser.add_argument("--require-version-match", action="store_true",
                        help="fail when the release tag differs from plugin_spec.py's version")
    args = parser.parse_args()

    repo = args.repo.strip()
    if not repo:
        fail("no repository known: pass --repo owner/name or set GITHUB_REPOSITORY")

    release = choose_release(repo, Path(args.root).resolve(), args.tag, args.token)
    assets = [a for a in release.get("assets", []) if a.get("name", "").endswith(ASSET_SUFFIX)]
    if not assets:
        names = [a.get("name") for a in release.get("assets", [])]
        fail(f"release {release.get('tag_name')} has no *{ASSET_SUFFIX} asset (assets: {names})")
    assets.sort(key=lambda a: a["name"])
    asset = assets[-1]

    tag = release["tag_name"]
    version = spec_version(Path(args.root).resolve())
    if args.require_version_match and version and tag.lstrip("v") != version:
        fail(f"latest release {tag} does not match plugin_spec.py version {version}")

    try:
        body = urllib.request.urlopen(
            urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "levin-ci"}),
            timeout=180,
        ).read()
    except urllib.error.URLError as error:
        fail(f"could not download {asset['browser_download_url']}: {error}")

    output = Path(args.output)
    output.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    declared = asset.get("digest") or ""
    if declared.startswith("sha256:"):
        if declared.split(":", 1)[1].lower() != digest:
            fail(f"asset digest mismatch: API says {declared}, downloaded sha256 {digest}")
        log(f"sha256 verified against the release metadata: {digest}")
    else:
        log(f"release metadata carries no digest; recorded sha256 {digest}")

    log(f"{asset['name']} from {tag} -> {output} ({len(body)} bytes)")
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as handle:
            handle.write(f"RELEASED_TAG={tag}\n")
            handle.write(f"RELEASED_ASSET={output}\n")
    print(json.dumps({"tag": tag, "asset": asset["name"], "sha256": digest,
                      "path": str(output), "spec_version": version}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
