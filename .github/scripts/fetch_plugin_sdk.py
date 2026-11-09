#!/usr/bin/env python3
"""Provision the Levin plugin SDK (``levin_plugin_sdk``) into a repo copy.

Why this exists
---------------
``.levin-plugin/`` is gitignored, so a fresh clone has no vendored SDK. The
documented test command puts ``.levin-plugin/vendor/python`` on ``PYTHONPATH`` and
``tests/test_schema_surface.py`` imports ``plugin_spec.py``, which begins with
``from levin_plugin_sdk import ...``. Without the SDK that module never imports and
the whole ``SchemaSurfaceTests`` class errors out.

The SDK is **not on PyPI**. The only public copy ships inside the packaged
``*.levin-plugin.tgz`` attached to a GitHub release, so that is where this script
gets it. Nothing is synthesized: if no usable source is reachable the script exits
non-zero with the reason.

Sources, in priority order
--------------------------
1. ``--sdk-dir`` / ``$LEVIN_SDK_DIR``        an existing ``.../vendor/python`` dir
2. ``--archive``                             a local ``*.levin-plugin.tgz``
3. ``<root>/.levin-plugin/vendor/python``    already provisioned (dev machine)
4. a GitHub release asset                    downloaded via download_release_asset.py

Exit 0 = ``import levin_plugin_sdk`` works from the destination and exposes
``Plugin``, ``PythonRuntime`` and ``RuntimeCommand``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SDK_PACKAGE = "levin_plugin_sdk"
VENDOR_RELATIVE = Path(".levin-plugin") / "vendor" / "python"
REQUIRED_EXPORTS = ("Plugin", "PythonRuntime", "RuntimeCommand")
REQUIRED_FILES = ("__init__.py", "spec.py", "compiler.py", "server.py", "runtime.py")


def log(message: str) -> None:
    print(f"[sdk] {message}", flush=True)


def die(message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[sdk] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def extract_sdk(archive: Path, destination: Path) -> int:
    """Copy only .levin-plugin/vendor/python/levin_plugin_sdk out of the tarball."""
    destination.mkdir(parents=True, exist_ok=True)
    wanted = f"./{VENDOR_RELATIVE.as_posix()}/{SDK_PACKAGE}/"
    shutil.rmtree(destination / SDK_PACKAGE, ignore_errors=True)
    written = 0
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                continue  # never trust archive paths
            normalized = name if name.startswith("./") else f"./{name}"
            if not normalized.startswith(wanted) or not member.isfile():
                continue
            relative = normalized[len(wanted):]
            if "__pycache__" in Path(relative).parts or relative.endswith((".pyc", ".pyo")):
                continue
            target = destination / SDK_PACKAGE / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            target.write_bytes(source.read())
            written += 1
    if not written:
        die(f"{archive.name} contains no {wanted} entries; it cannot supply the SDK")
    return written


def verify(destination: Path) -> dict:
    missing = [f for f in REQUIRED_FILES if not (destination / SDK_PACKAGE / f).is_file()]
    if missing:
        die(f"{destination} is missing SDK files: {missing}")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(destination)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    probe = (
        "import json, levin_plugin_sdk as s;"
        "print(json.dumps({'ABI_VERSION': s.ABI_VERSION, 'CONTRACT_VERSION': s.CONTRACT_VERSION,"
        f" 'exports': [n for n in {REQUIRED_EXPORTS!r} if hasattr(s, n)]}}))"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)
    if result.returncode != 0:
        die(f"import levin_plugin_sdk from {destination} failed:\n{result.stderr.strip()}")
    info = json.loads(result.stdout.strip().splitlines()[-1])
    if sorted(info["exports"]) != sorted(REQUIRED_EXPORTS):
        die(f"SDK at {destination} does not export {REQUIRED_EXPORTS}: {info['exports']}")
    spec_text = (destination / SDK_PACKAGE / "spec.py").read_text(encoding="utf-8", errors="replace")
    match = re.search(r"CONTRACT_VERSION\s*=\s*(\d+)", spec_text)
    if match:
        info["contract_from_spec"] = int(match.group(1))
    info["files"] = len(list((destination / SDK_PACKAGE).glob("*.py")))
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--dest", default=None, help=f"destination (default: <root>/{VENDOR_RELATIVE})")
    parser.add_argument("--sdk-dir", default=os.environ.get("LEVIN_SDK_DIR"))
    parser.add_argument("--archive", default=None, help="local *.levin-plugin.tgz to take the SDK from")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--tag", default=os.environ.get("LEVIN_RELEASE_TAG"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--force", action="store_true", help="re-provision even when already present")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    destination = Path(args.dest).resolve() if args.dest else root / VENDOR_RELATIVE
    provisioned = (destination / SDK_PACKAGE / "__init__.py").is_file()

    # 1. an explicit SDK directory: accept the vendor root, or the package dir
    #    itself, or the plugin root that contains .levin-plugin/vendor/python.
    if args.sdk_dir:
        given = Path(args.sdk_dir).expanduser().resolve()
        candidates = (
            given,
            given / VENDOR_RELATIVE,
            given.parent,
            given.parent / VENDOR_RELATIVE,
        )
        source = next((c for c in candidates if (c / SDK_PACKAGE).is_dir()), None)
        if source is None:
            die(
                f"--sdk-dir {given} contains no {SDK_PACKAGE}/ directory; looked in "
                f"{[str(c) for c in candidates]}"
            )
        log(f"using the SDK at {source}")
        destination.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(destination / SDK_PACKAGE, ignore_errors=True)
        shutil.copytree(source / SDK_PACKAGE, destination / SDK_PACKAGE,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        info = verify(destination)
        log(f"ready: {destination} (ABI {info['ABI_VERSION']}, contract {info['CONTRACT_VERSION']})")
        print(json.dumps({"source": "sdk-dir", "path": str(destination), **info}))
        return 0

    # 2. a local package archive
    if args.archive:
        archive = Path(args.archive).expanduser().resolve()
        if not archive.is_file():
            die(f"--archive {archive} does not exist")
        count = extract_sdk(archive, destination)
        log(f"copied {count} SDK files from {archive.name}")
        info = verify(destination)
        log(f"ready: {destination} (ABI {info['ABI_VERSION']}, contract {info['CONTRACT_VERSION']})")
        print(json.dumps({"source": "archive", "archive": str(archive),
                          "path": str(destination), **info}))
        return 0

    # 3. already provisioned in the tree
    if provisioned and not args.force:
        log(f"already provisioned at {destination}; nothing to download")
        info = verify(destination)
        print(json.dumps({"source": "existing", "path": str(destination), **info}))
        return 0

    # 4. a release asset
    repo = args.repo.strip()
    if not repo:
        die("no SDK source: pass --sdk-dir, --archive, or --repo/owner-name "
            "(GITHUB_REPOSITORY) so the SDK can be taken from a release asset")
    import download_release_asset as releases  # same directory, standard library only

    with tempfile.TemporaryDirectory(prefix="levin-sdk-") as workspace:
        archive = Path(workspace) / "released.levin-plugin.tgz"
        extra = ["--root", str(root), "--repo", repo, "--output", str(archive)]
        if args.tag:
            extra += ["--tag", args.tag]
        if args.token:
            extra += ["--token", args.token]
        argv = sys.argv
        try:
            sys.argv = ["download_release_asset.py", *extra]
            releases.main()
        finally:
            sys.argv = argv
        if not archive.is_file():
            die("release download did not produce an archive")
        count = extract_sdk(archive, destination)
        log(f"copied {count} SDK files from the release asset")

    info = verify(destination)
    log(f"ready: {destination} (ABI {info['ABI_VERSION']}, contract {info['CONTRACT_VERSION']})")
    print(json.dumps({"source": "release", "path": str(destination), **info}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
