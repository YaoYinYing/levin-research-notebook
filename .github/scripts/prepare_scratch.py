#!/usr/bin/env python3
"""Prepare ``NOTEBOOK_TEST_SCRATCH`` for the CI test job.

Two reasons this is a script instead of three lines in the workflow:

1. Cross-shell. The default shell differs per runner (bash on Linux/macOS, pwsh
   on Windows), so anything relying on heredocs or ``$VAR`` expansion needs a
   shell override. A Python file runs identically with the default shell on all
   three platforms.
2. Path normalisation. The suite takes ``NOTEBOOK_TEST_SCRATCH`` and later
   compares paths it derives from it against paths it derives from
   ``tempfile.mkdtemp(dir=SCRATCH)``. On macOS ``$GITHUB_WORKSPACE`` lives under
   ``/Users/...`` but the runner may hand out a path through a symlink, and on
   macOS ``/tmp`` is itself a symlink to ``/private/tmp``; passing an unresolved
   root makes ``test_init_is_idempotent_and_reopens`` and
   ``test_reference_outside_workspace_is_explicit_external`` fail on a
   path-string comparison that has nothing to do with the code under test.
   ``Path.resolve()`` removes that variable. This is a CI-environment concern:
   no test and no module under mcp/ is touched.

The resolved path goes to ``$GITHUB_ENV`` so later steps inherit it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    workspace = os.environ.get("GITHUB_WORKSPACE") or os.getcwd()
    root = Path(workspace).resolve()
    if not root.is_dir():
        print(f"ERROR: GITHUB_WORKSPACE {root} is not a directory", file=sys.stderr)
        return 1

    scratch = root / "levin_scratch" / "ci-tests"
    scratch.mkdir(parents=True, exist_ok=True)

    # Fail early, in this step, if the workspace itself still has a symlink in it:
    # silently resolving around it would hide a genuinely odd environment.
    raw = Path(workspace)
    if raw.exists() and raw.resolve() != raw:
        print(f"note: GITHUB_WORKSPACE {raw} resolves to {raw.resolve()} (symlinked); using the resolved path")

    target = os.environ.get("GITHUB_ENV")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"NOTEBOOK_TEST_SCRATCH={scratch}\n")
    else:
        print("no GITHUB_ENV set; running outside Actions, not exporting anything")

    print(f"workspace         : {root}")
    print(f"NOTEBOOK_TEST_SCRATCH = {scratch}")
    print(f"retained workspaces will appear there and be uploaded on failure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
