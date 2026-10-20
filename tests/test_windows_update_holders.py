# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Who holds the Windows install directory, by what the user can do about it.

``win_processes.classify`` is pure: canned rows in the shape of the native
table (``{pid, ppid, name, path, created, has_window}``) in, holders out.
A parent link counts only while the parent is alive and not younger than
the child, so a reused PID never adopts an orphan.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

for _name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

from mixar.modules.common.updates.core import win_processes as wp

INSTALL_DIR = r"C:\Program Files\Mixar"
MIXAR = INSTALL_DIR + r"\mixar.exe"
LAUNCHER = INSTALL_DIR + r"\mixar-launcher.exe"
PYTHON = INSTALL_DIR + r"\5.2\python\bin\python.exe"
CLAUDE = r"C:\Users\u\AppData\Local\AnthropicClaude\Claude.exe"
CMD = r"C:\Windows\System32\cmd.exe"
US = 100


def _row(pid, ppid, name, path="", created=None, window=False):
    # Creation time defaults to the pid: parents listed with lower pids are older.
    return {"pid": pid, "ppid": ppid, "name": name, "path": path,
            "created": pid if created is None else created, "has_window": window}


def _holders(*rows, us=None):
    table = [us or _row(US, 1, "mixar.exe", MIXAR, window=True), *rows]
    return [(h.kind, h.name, h.pid) for h in wp.classify(table, INSTALL_DIR, US)]


def test_our_descendants_are_background_work():
    assert _holders(
        _row(101, US, "mixar.exe", MIXAR),         # preview backfill / render shard
        _row(102, 101, "python.exe", PYTHON),
    ) == [(wp.BACKGROUND, "mixar.exe", 101), (wp.BACKGROUND, "python.exe", 102)]


def test_a_windowless_orphan_mixar_is_background_work():
    # mixar.exe -b left running by an earlier session: its parent is gone.
    assert _holders(_row(300, 9999, "mixar.exe", MIXAR)) == [
        (wp.BACKGROUND, "mixar.exe", 300)]


def test_a_mixar_with_a_window_is_another_mixar_window():
    assert _holders(_row(300, 1, "mixar.exe", MIXAR, window=True)) == [
        (wp.MIXAR_WINDOW, "Mixar", 300)]


def test_a_connector_is_named_after_its_ai_app_through_shells():
    assert _holders(
        _row(300, 1, "Claude.exe", CLAUDE),
        _row(301, 300, "cmd.exe", CMD),
        _row(302, 301, "python.exe", PYTHON),
    ) == [(wp.CONNECTOR, "Claude", 302)]


def test_a_shell_and_the_python_it_starts_may_share_a_clock_tick():
    assert _holders(
        _row(300, 1, "Claude.exe", CLAUDE, created=5),
        _row(301, 300, "cmd.exe", CMD, created=7),
        _row(302, 301, "python.exe", PYTHON, created=7),
    ) == [(wp.CONNECTOR, "Claude", 302)]


def test_a_connector_whose_parent_is_gone_is_abandoned():
    assert _holders(_row(500, 9999, "python.exe", PYTHON)) == [
        (wp.ABANDONED_CONNECTOR, "python.exe", 500)]


def test_a_reused_parent_pid_does_not_adopt_the_connector():
    # PID 300 now belongs to a process started AFTER the python: not its parent.
    assert _holders(
        _row(300, 1, "explorer.exe", r"C:\Windows\explorer.exe", created=900),
        _row(500, 300, "python.exe", PYTHON, created=400),
    ) == [(wp.ABANDONED_CONNECTOR, "python.exe", 500)]


def test_a_connector_with_only_shells_left_above_it_is_abandoned():
    assert _holders(
        _row(301, 9999, "cmd.exe", CMD),
        _row(302, 301, "python.exe", PYTHON),
    ) == [(wp.ABANDONED_CONNECTOR, "python.exe", 302)]


def test_a_python_started_by_a_mixar_is_background_work():
    assert _holders(
        _row(200, 1, "mixar.exe", MIXAR, window=True),
        _row(201, 200, "python.exe", PYTHON),
    ) == [(wp.MIXAR_WINDOW, "Mixar", 200), (wp.BACKGROUND, "python.exe", 201)]


def test_a_host_windows_will_not_open_still_names_the_connector():
    # Another account's / elevated app: no path, no creation time.
    assert _holders(
        _row(300, 1, "Codex.exe", None, created=None),
        _row(302, 300, "python.exe", PYTHON),
    ) == [(wp.CONNECTOR, "Codex", 302)]


def test_our_own_launcher_is_left_out():
    # A launcher that waits on us (Steam, -b) ends when we do.
    us = _row(US, 50, "mixar.exe", MIXAR, window=True)
    assert _holders(_row(50, 1, "mixar-launcher.exe", LAUNCHER), us=us) == []


def test_anything_else_from_the_install_dir_is_named_by_basename():
    assert _holders(
        _row(700, 1, "crashpad_handler.exe", INSTALL_DIR + r"\crashpad_handler.exe"),
        _row(701, 1, "Code.exe", r"C:\Program Files\Mixar Tools\Code.exe"),  # prefix only
        _row(702, 1, "denied.exe", None, created=None),
    ) == [(wp.OTHER, "crashpad_handler.exe", 700)]


def test_what_the_user_must_close():
    assert wp.USER_CLOSABLE == {wp.MIXAR_WINDOW, wp.CONNECTOR, wp.OTHER}


def test_the_table_is_native_not_a_subprocess():
    """It runs on the UI thread: Win32 calls, never PowerShell or WMI."""
    source = (SCRIPTS / "mixar" / "modules" / "common" / "updates" / "core"
              / "win_processes.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    for call in ("CreateToolhelp32Snapshot", "QueryFullProcessImageNameW",
                 "GetProcessTimes", "EnumWindows", "TerminateProcess"):
        assert call in source
    # Every handle opened is closed.
    assert source.count("CloseHandle(") >= 3


def test_terminate_without_win32_reports_still_running():
    if sys.platform == "win32":
        return
    assert wp.terminate(wp.Holder(wp.ABANDONED_CONNECTOR, "python.exe", 1, 1)) is False
