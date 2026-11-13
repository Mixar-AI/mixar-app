# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows' reboot rename queue, read after an MSI 3010.

``PendingFileRenameOperations`` is a REG_MULTI_SZ of source/destination
pairs in NT form (``\\??\\C:\\...``); a destination may start with ``!``
(replace existing) and an empty one means delete. Only an entry under the
Mixar install directory means the update is unfinished; other programs'
entries and Windows Installer's clean-up deletes do not count.
"""

import sys
import types
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

import pytest

from mixar.modules.common.updates.core import pending_renames

INSTALL_DIR = r"C:\Program Files\Mixar"

# A held DLL written under a temp name, queued to replace the old one.
HELD_DLL = [
    r"\??\C:\Program Files\Mixar\~DF1A2B.tmp",
    r"!\??\C:\Program Files\Mixar\5.2\python\DLLs\_ssl.pyd",
]
# Windows Installer's renamed-aside old copy, deleted at reboot.
CONFIG_MSI = [r"\??\C:\Config.Msi\3a5f2e.rbf", ""]
OTHER_PROGRAMS = [
    r"\??\C:\Program Files (x86)\Other\update.tmp", r"!\??\C:\Program Files (x86)\Other\x.dll",
    r"\??\C:\Program Files\Mixar Beta\old.dll", "",
    r"\??\C:\Users\u\AppData\Local\Temp\a.tmp", "",
]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_pairs_lose_the_nt_prefix_and_the_replace_marker():
    assert pending_renames.parse_pending_renames(HELD_DLL + CONFIG_MSI) == [
        (r"C:\Program Files\Mixar\~DF1A2B.tmp",
         r"C:\Program Files\Mixar\5.2\python\DLLs\_ssl.pyd"),
        (r"C:\Config.Msi\3a5f2e.rbf", ""),
    ]


@pytest.mark.parametrize("values, pairs", [
    # An empty destination is a delete.
    ([r"\??\C:\x.dll", ""], [(r"C:\x.dll", "")]),
    # A trailing source with no destination is a delete too.
    ([r"\??\C:\a.tmp", r"!\??\C:\a.dll", r"\??\C:\b.tmp"],
     [(r"C:\a.tmp", r"C:\a.dll"), (r"C:\b.tmp", "")]),
    # A pair with no source is skipped.
    (["", "", r"\??\C:\x.dll", ""], [(r"C:\x.dll", "")]),
    ([r"\??\UNC\srv\share\Mixar\a.tmp", r"!\??\UNC\srv\share\Mixar\a.dll"],
     [(r"\\srv\share\Mixar\a.tmp", r"\\srv\share\Mixar\a.dll")]),
    ([r"\\?\C:\x.tmp", r"C:\x.dll"], [(r"C:\x.tmp", r"C:\x.dll")]),
    ([], []),
    (None, []),
])
def test_pair_parsing_edge_cases(values, pairs):
    assert pending_renames.parse_pending_renames(values) == pairs


# ---------------------------------------------------------------------------
# Matching the install directory
# ---------------------------------------------------------------------------


# Recorded on the Windows QA box (2026-11-11): a DLL held without delete
# sharing during a 4.4.0 -> 4.4.3 upgrade (exit 3010), and the uninstall's
# delete of a held file. Windows prefixes each path with "*1".
BOX_HELD_DLL = [
    r"*1\??\C:\Program Files\Mixar\TBM5862.tmp",
    r"*1\??\C:\Program Files\Mixar\blender_cpu_check.dll",
]
BOX_DELETE = [r"*1\??\C:\Program Files\Mixar\blender_cpu_check.dll", ""]


def test_the_star_flag_prefix_is_dropped():
    assert pending_renames.parse_pending_renames(BOX_HELD_DLL + BOX_DELETE) == [
        (r"C:\Program Files\Mixar\TBM5862.tmp", r"C:\Program Files\Mixar\blender_cpu_check.dll"),
        (r"C:\Program Files\Mixar\blender_cpu_check.dll", ""),
    ]
    assert pending_renames.touches(pending_renames.parse_pending_renames(BOX_HELD_DLL), INSTALL_DIR)
    assert not pending_renames.touches(pending_renames.parse_pending_renames(BOX_DELETE), INSTALL_DIR)


@pytest.mark.parametrize("values, location, touches", [
    (HELD_DLL, INSTALL_DIR, True),
    # Case and a trailing separator do not matter.
    (HELD_DLL, r"c:\PROGRAM FILES\mixar" + "\\", True),
    ([v.upper() for v in HELD_DLL], INSTALL_DIR, True),
    # Only the destination is in the install directory.
    ([r"\??\C:\Windows\Temp\x.tmp", r"!\??\C:\Program Files\Mixar\x.dll"], INSTALL_DIR, True),
    # A delete is clean-up, even inside the install directory (a held file
    # renamed aside there): the new file is already in place.
    ([r"\??\C:\Program Files\Mixar\stale.dll", ""], INSTALL_DIR, False),
    ([r"\??\C:\Program Files\Mixar\~RF1.TMP", ""], INSTALL_DIR, False),
    # Only the source is in the install directory: nothing lands there.
    ([r"\??\C:\Program Files\Mixar\a.tmp", r"!\??\C:\Other\a.dll"], INSTALL_DIR, False),
    (CONFIG_MSI, INSTALL_DIR, False),
    # Other programs, including a sibling folder whose name starts with ours.
    (OTHER_PROGRAMS, INSTALL_DIR, False),
    (OTHER_PROGRAMS + CONFIG_MSI + HELD_DLL, INSTALL_DIR, True),
    (HELD_DLL, r"D:\Apps\Mixar", False),
    (HELD_DLL, "", False),
])
def test_only_entries_under_the_install_directory_count(values, location, touches):
    pairs = pending_renames.parse_pending_renames(values)

    assert pending_renames.touches(pairs, location) is touches


# ---------------------------------------------------------------------------
# The registry read
# ---------------------------------------------------------------------------


class _Key:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _fake_winreg(values, open_error=None):
    def open_key(hive, path, reserved, access):
        assert (hive, reserved) == ("HKLM", 0)
        assert path == r"SYSTEM\CurrentControlSet\Control\Session Manager"
        if open_error:
            raise open_error
        return _Key()

    def query(_key, name):
        if name not in values:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return values[name], 7  # REG_MULTI_SZ

    return types.SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM", KEY_QUERY_VALUE=1, OpenKey=open_key, QueryValueEx=query,
    )


def test_both_queue_values_are_read_and_a_missing_one_is_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg({
        "PendingFileRenameOperations": OTHER_PROGRAMS,
        "PendingFileRenameOperations2": HELD_DLL,
    }))
    assert pending_renames.touches(pending_renames.read_pending_renames(), INSTALL_DIR)

    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg({}))
    assert pending_renames.read_pending_renames() == []


def test_files_pending_reboot_reads_only_on_windows(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(
        {"PendingFileRenameOperations": HELD_DLL}))

    monkeypatch.setattr(pending_renames, "_on_windows", lambda: False)
    assert pending_renames.files_pending_reboot(INSTALL_DIR) is False

    monkeypatch.setattr(pending_renames, "_on_windows", lambda: True)
    assert pending_renames.files_pending_reboot(INSTALL_DIR) is True
    assert pending_renames.files_pending_reboot(r"D:\Apps\Mixar") is False
    assert pending_renames.files_pending_reboot("") is False


def test_an_unreadable_registry_is_logged_and_counts_as_nothing_pending(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(
        {}, open_error=PermissionError(5, "Access is denied")))
    monkeypatch.setattr(pending_renames, "_on_windows", lambda: True)
    logger = MagicMock()
    monkeypatch.setattr(pending_renames, "logger", logger)

    assert pending_renames.files_pending_reboot(INSTALL_DIR) is False
    logger.warning.assert_called_once()
