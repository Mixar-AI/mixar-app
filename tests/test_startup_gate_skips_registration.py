# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source-level pin: the native startup login gate skips modes with no UI.

`creator.cc` shows the Mixar login window (`show_startup_dialog`) before
Blender parses its arguments, unless the command line asks for background
mode. Blender's file-association flags set background mode themselves,
register or unregister, and exit before any window opens. The Windows
installer runs `--register-allusers` / `--unregister-allusers` on every
install, upgrade and uninstall, often as SYSTEM with no visible desktop,
where a login window hangs that process forever with install files open.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CREATOR = ROOT / "src/source/creator/creator.cc"
# The submodule lives in the main checkout; a linked worktree sits two levels below it.
UPSTREAM_ARGS = [
    base / "upstream/source/creator/creator_args.cc" for base in (ROOT, ROOT.parents[1])
]

REGISTRATION_FLAGS = {
    "-r",
    "--register",
    "--register-allusers",
    "--unregister",
    "--unregister-allusers",
}


def _flags_that_skip_the_gate() -> set:
    src = CREATOR.read_text()
    gate = src.index("!show_startup_dialog()")
    block = src[src.rindex("is_background = false;", 0, gate):gate]
    return set(re.findall(r'"(-[^"]*)"', block))


def test_gate_skips_background_and_registration_modes():
    flags = _flags_that_skip_the_gate()
    assert {"-b", "--background"} <= flags
    assert REGISTRATION_FLAGS <= flags


def test_registration_flags_are_blenders_spellings():
    """Each skipped flag is one Blender registers for its registration handlers."""
    upstream = next((path for path in UPSTREAM_ARGS if path.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    args = upstream.read_text()
    registered = set(
        re.findall(
            r'BLI_args_add\(\s*ba,\s*(?:"([^"]+)"|nullptr),\s*"([^"]+)",\s*'
            r"CB\(arg_handle_(?:un)?register_extension(?:_all)?\)",
            args,
        )
    )
    spellings = {flag for pair in registered for flag in pair if flag}
    assert spellings == REGISTRATION_FLAGS
