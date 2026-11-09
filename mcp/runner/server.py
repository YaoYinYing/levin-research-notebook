#!/usr/bin/env python3
"""Levin Plugin Contract v2 entrypoint. Generated from plugin_spec.py."""

from pathlib import Path
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SDK_ROOT = PLUGIN_ROOT / ".levin-plugin" / "vendor" / "python"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SDK_ROOT))

from plugin_spec import plugin


if __name__ == "__main__":
    plugin.serve(PLUGIN_ROOT)
