#!/usr/bin/env python3
"""Print how reporting.py resolves its fonts on this host.

`mcp/runner/reporting.py` walks per-platform candidate chains
(Times/Liberation/DejaVu on Linux, Times on macOS, times.ttf on Windows, then a
CJK chain with Songti/Noto/arphic/wqy/simsun). Only the macOS chain has ever been
exercised on a real host, so this step exists to put the resolved faces of each
CI platform into the job log next to the test result. It fails the job when the
resolver itself raises: a renderer that cannot resolve fonts is a real defect,
not a diagnostic detail.
"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mcp" / "runner"))

CANDIDATE_PATHS = (
    # Latin
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "C:/Windows/Fonts/times.ttf",
    # Mono
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    # CJK
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "C:/Windows/Fonts/simsun.ttc",
)


def main() -> int:
    print(f"python {sys.version.split()[0]} | platform {sys.platform} | {platform.platform()}")
    try:
        import reporting
    except Exception as error:  # noqa: BLE001 - the import itself is the finding
        print(f"FAIL  mcp/runner/reporting.py is not importable: {error!r}")
        return 1

    print(f"reporting.py: {reporting.__file__}")
    print(f"default profile: {reporting.DEFAULT_PROFILE}")
    print("candidate font files on this host:")
    for candidate in CANDIDATE_PATHS:
        print(f"  {'present' if Path(candidate).is_file() else 'absent '}  {candidate}")

    failures = 0
    for profile in sorted(reporting.FONT_PROFILES) + ["auto"]:
        try:
            info = reporting.font_report(profile)
        except Exception as error:  # noqa: BLE001
            print(f"FAIL  font_report({profile!r}) raised: {error!r}")
            failures += 1
            continue
        print(f"\nprofile {profile} (resolved {info['profile']}, cjk_available={info['cjk_available']})")
        print(json.dumps(info["fonts"], indent=2, sort_keys=True))
        for note in info["notes"]:
            print(f"  note: {note}")

    if failures:
        print(f"\n{failures} font profile(s) failed to resolve")
        return 1
    print("\nall font profiles resolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
