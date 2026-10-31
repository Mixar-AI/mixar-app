# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The splash offers the autosave of a session that crashed (cs-go-3, 28 Oct)."""

import os

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.bootstrap import crash_recovery as CR  # noqa: E402

NOW = 1_800_000_000.0


def _touch(folder, name, mtime):
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(b"x")
    os.utime(path, (mtime, mtime))
    return path


def test_a_dead_session_newer_than_the_last_clean_quit_is_offered(tmp_path):
    _touch(tmp_path, "quit.blend", NOW - 3600)
    crashed = _touch(tmp_path, "64632_autosave.mixar", NOW - 60)
    _touch(tmp_path, "cs-go-2_62209_autosave.mixar", NOW - 7200)  # before the clean quit
    found = CR.crashed_autosaves(str(tmp_path), own_pid=1, now=NOW, alive=lambda pid: False)
    assert [f["path"] for f in found] == [crashed]
    assert found[0]["name"] == ""


def test_newest_first_with_the_project_name(tmp_path):
    _touch(tmp_path, "older_100_autosave.mixar", NOW - 600)
    _touch(tmp_path, "cs-go-3_200_autosave.mixar", NOW - 60)
    found = CR.crashed_autosaves(str(tmp_path), own_pid=1, now=NOW, alive=lambda pid: False)
    assert [f["name"] for f in found] == ["cs-go-3", "older"]
    assert CR.label(found[0]).startswith("cs-go-3 · ")


def test_own_running_and_stale_autosaves_are_not_offered(tmp_path):
    _touch(tmp_path, "mine_10_autosave.mixar", NOW - 60)
    _touch(tmp_path, "other_20_autosave.mixar", NOW - 60)
    _touch(tmp_path, "ancient_30_autosave.mixar", NOW - CR.MAX_AGE_S - 1)
    _touch(tmp_path, "notes.mixar", NOW - 60)
    found = CR.crashed_autosaves(str(tmp_path), own_pid=10, now=NOW, alive=lambda pid: pid == 20)
    assert found == []


def test_a_missing_temp_folder_offers_nothing(tmp_path):
    assert CR.crashed_autosaves(str(tmp_path / "gone"), own_pid=1, now=NOW) == []
