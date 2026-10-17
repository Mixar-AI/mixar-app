# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""restricted_open() write-gate: containment boundary, not a bare prefix match.

The check used to be real.startswith(temp_prefix), which also admitted
sibling paths that merely share the prefix (/tmp/mixar vs /tmp/mixar_evil).
Writes must land INSIDE the temp directory — or on the directory itself.
"""

import importlib.util
import os
from pathlib import Path
import tempfile

import pytest

_SANDBOX_MODULES = (
    Path(__file__).parents[1]
    / "src/scripts/mixar/modules/space_mixie_chat/core/sandbox_modules.py"
)


def _load_sandbox_modules():
    spec = importlib.util.spec_from_file_location(
        "sandbox_modules_restricted_open_under_test", _SANDBOX_MODULES
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_temp_prefix():
    return os.path.realpath(tempfile.gettempdir())


def test_write_inside_tempdir_is_allowed():
    mod = _load_sandbox_modules()
    target = os.path.join(tempfile.gettempdir(), "mixar_restricted_open_ok.txt")
    try:
        with mod.restricted_open(target, "w") as fh:
            fh.write("ok")
        with open(target) as fh:
            assert fh.read() == "ok"
    finally:
        try:
            os.unlink(target)
        except OSError:
            pass


def test_write_to_sibling_prefix_directory_is_rejected():
    # /tmp/<tmpdir>_sibling shares the prefix but is OUTSIDE the boundary.
    mod = _load_sandbox_modules()
    sibling = _real_temp_prefix() + "_sibling_escape/evil.py"
    with pytest.raises(PermissionError):
        mod.restricted_open(sibling, "w")


def test_write_to_sibling_prefix_file_is_rejected():
    # A sibling FILE (not a directory) sharing the prefix.
    mod = _load_sandbox_modules()
    lookalike = _real_temp_prefix() + "-evil.txt"
    with pytest.raises(PermissionError):
        mod.restricted_open(lookalike, "w")


def test_write_outside_tempdir_is_rejected():
    mod = _load_sandbox_modules()
    with pytest.raises(PermissionError):
        mod.restricted_open(os.path.expanduser("~/mixar_restricted_open_escape.txt"), "w")


def test_tempdir_itself_admitted_by_boundary_but_os_rejects_directory():
    # real == temp_prefix passes the boundary check; the OS then refuses the
    # open because a directory cannot be opened for writing. The sandbox gate
    # (PermissionError) must not be the reason it fails.
    mod = _load_sandbox_modules()
    with pytest.raises(OSError) as excinfo:
        mod.restricted_open(_real_temp_prefix(), "w")
    assert not isinstance(excinfo.value, PermissionError)
