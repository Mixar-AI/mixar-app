# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install on quit, the supporting pieces: the macOS process table that
decides whether another Mixar runs from the bundle, the next launch's
report of a quit/launch install (trigger, failures, interruptions), and
the Preferences switch.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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

from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import INSTALL_ON_QUIT_CONFIG_KEY
from mixar.modules.common.updates.core import (
    install_flow,
    mac_processes,
    preferences,
    result_report,
    staged_record,
    toasts,
    update_checker,
)

BUNDLE = "/Applications/Mixar.app"
UPDATES = SCRIPTS / "mixar" / "modules" / "common" / "updates"


# ---------------------------------------------------------------------------
# macOS: who else runs from the bundle
# ---------------------------------------------------------------------------


def _row(pid, ppid, path, created=100.0):
    return {"pid": pid, "ppid": ppid, "path": path, "created": created}


def test_another_mixar_blocks_but_our_own_children_do_not():
    rows = [
        _row(1, 0, "/sbin/launchd", 0.0),
        _row(500, 1, BUNDLE + "/Contents/MacOS/Mixar"),           # this app
        _row(501, 500, BUNDLE + "/Contents/MacOS/Mixar", 200.0),  # its render worker
        _row(502, 501, BUNDLE + "/Contents/Resources/5.2/python/bin/python3.13", 300.0),
        _row(600, 1, BUNDLE + "/Contents/MacOS/Mixar"),           # a second Mixar
        _row(700, 1, "/Applications/Claude.app/Contents/MacOS/Claude"),
        _row(701, 700, BUNDLE + "/Contents/Resources/5.2/python/bin/python3.13", 300.0),
        _row(800, 1, BUNDLE + "/Contents/Resources/lib/tool"),
        _row(900, 1, "/Applications/Mixar.app.backup/Contents/MacOS/Mixar"),
    ]

    holders = mac_processes.classify(rows, BUNDLE, 500)

    assert sorted((h.kind, h.name, h.pid) for h in holders) == [
        (mac_processes.BACKGROUND, "tool", 800),
        (mac_processes.MIXAR, "Mixar", 600),
    ]


def test_a_reused_parent_pid_is_not_an_ancestor():
    """A "parent" started after its child is a reused PID: the orphan is
    not ours and blocks."""
    rows = [
        _row(500, 1, BUNDLE + "/Contents/MacOS/Mixar", 500.0),
        _row(501, 500, BUNDLE + "/Contents/MacOS/Mixar", 100.0),
    ]
    assert [h.pid for h in mac_processes.classify(rows, BUNDLE, 500)] == [501]


def test_another_account_s_mixar_still_counts():
    rows = [_row(500, 1, BUNDLE + "/Contents/MacOS/Mixar"),
            {"pid": 42, "ppid": None, "created": None, "path": BUNDLE + "/Contents/MacOS/Mixar"}]
    assert [h.pid for h in mac_processes.classify(rows, BUNDLE, 500)] == [42]


@pytest.mark.skipif(sys.platform != "darwin", reason="libproc")
def test_the_live_table_sees_this_process_and_its_children():
    child = subprocess.Popen(["/bin/sleep", "10"])
    try:
        rows = {row["pid"]: row for row in mac_processes.process_table()}
        assert rows[os.getpid()]["path"] == os.path.realpath(sys.executable) or (
            rows[os.getpid()]["path"])
        assert rows[child.pid]["ppid"] == os.getpid()
        assert rows[child.pid]["created"] >= rows[os.getpid()]["created"]
        bin_dir = os.path.dirname(rows[child.pid]["path"])
        # /bin/sleep is our child: it ends with us, so it never blocks.
        assert all(h.pid != child.pid for h in mac_processes.blocking_apps(bin_dir, os.getpid()))
    finally:
        child.kill()
        child.wait()


# ---------------------------------------------------------------------------
# The next launch's report
# ---------------------------------------------------------------------------


def _report(monkeypatch, result, running):
    monkeypatch.setattr(install_flow, "read_previous_result", lambda: dict(result))
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: running)
    monkeypatch.setattr(result_report, "_running_binary", lambda: "")
    monkeypatch.setattr(result_report, "_install_kind", lambda: "")
    get_notification_store().clear_all()
    with patch("mixar.modules.common.analytics.update_events.capture") as captured:
        toasts.report_previous_update_result()
    return captured.call_args.args[1], get_notification_store().get_visible()


def test_a_quit_install_reports_its_trigger_and_the_success_toast(monkeypatch):
    props, visible = _report(monkeypatch, {
        "version": "3.4.0", "stage": "install", "exit": "0", "trigger": "quit",
        "from_version": "3.3.6", "attempt_id": "a1"}, "3.4.0")

    assert props["trigger"] == "quit" and props["outcome"] == "success"
    assert props["attempt_id"] == "a1"
    assert [item.title for item in visible] == ["Updated to Mixar 3.4.0"]


def test_an_unknown_trigger_is_reported_as_the_click(monkeypatch):
    props, _ = _report(monkeypatch, {
        "version": "3.4.0", "stage": "install", "exit": "0", "trigger": "C:\\x"}, "3.4.0")
    assert props["trigger"] == "click"


def test_an_interrupted_install_is_reported_but_not_toasted_or_counted(monkeypatch, tmp_path):
    dmg = tmp_path / "Mixar-3.4.0.dmg"
    dmg.write_bytes(b"x")
    staged_record.write_ready(str(tmp_path), version="3.4.0", installer_path=str(dmg),
                              installer_type="dmg", download_url="u", sha256="s",
                              verified=False, signer="")
    props, visible = _report(monkeypatch, {
        "version": "3.4.0", "stage": "interrupted", "exit": "1", "trigger": "quit",
        "staging_dir": str(tmp_path)}, "3.3.6")

    assert props["outcome"] == "failed" and props["failure_reason"] == "interrupted"
    assert "staging_dir" not in props  # paths never leave the machine
    assert visible == []
    assert staged_record.read(str(tmp_path))["failures"] == 0


def test_a_failed_attempt_counts_against_silent_installs(monkeypatch, tmp_path):
    dmg = tmp_path / "Mixar-3.4.0.dmg"
    dmg.write_bytes(b"x")
    staged_record.write_ready(str(tmp_path), version="3.4.0", installer_path=str(dmg),
                              installer_type="dmg", download_url="u", sha256="s",
                              verified=False, signer="")
    _props, visible = _report(monkeypatch, {
        "version": "3.4.0", "stage": "copy", "exit": "1", "trigger": "quit",
        "staging_dir": str(tmp_path)}, "3.3.6")

    assert [item.title for item in visible] == ["Update was not installed"]
    assert staged_record.read(str(tmp_path))["failures"] == 1


def test_a_skipped_relaunch_is_a_known_kind(monkeypatch):
    props, _ = _report(monkeypatch, {
        "version": "3.4.0", "stage": "install", "exit": "0", "trigger": "quit",
        "relaunch_kind": "skipped"}, "3.4.0")
    assert props["relaunch_kind"] == "skipped"


def test_the_result_records_where_it_was_read(monkeypatch, tmp_path):
    from mixar.modules.common.updates.core import staging

    (tmp_path / "update-result.txt").write_text("version=3.4.0\nstage=install\nexit=0\n")
    monkeypatch.setattr(staging, "resolve_staging_dir",
                        lambda: staging.StagingDir(str(tmp_path), True))

    assert install_flow.read_previous_result()["staging_dir"] == str(tmp_path)


def test_the_download_records_the_copy_it_is_for(monkeypatch, tmp_path):
    """The record names the install location the worker checked, so only
    that copy installs it at a later launch."""
    from types import SimpleNamespace

    from mixar.modules.common.updates.core import app_paths, installer
    from mixar.modules.common.updates.core.state import UpdateInfo

    path = tmp_path / "Mixar-3.4.0.dmg"
    path.write_bytes(b"x")
    monkeypatch.setattr(install_flow, "_prepare_staging", lambda *_a: str(path))
    monkeypatch.setattr(install_flow, "_already_staged", lambda *_a: True)
    monkeypatch.setattr(install_flow.verify, "verify_installer",
                        lambda *_a, **_kw: (install_flow.verify.UNVERIFIED, "", ""))
    monkeypatch.setattr(install_flow, "_on_main_thread", lambda _fn: None)
    monkeypatch.setattr(install_flow, "get_update_state", lambda: SimpleNamespace(
        set_download_progress=lambda *_a: None, set_ready=lambda *_a: None))
    location = app_paths.InstallLocation(BUNDLE, True, needs_elevation=False)
    info = UpdateInfo(latest_version="3.4.0", current_version="3.3.6", download_url="u",
                      download_sha256="s", installer_type="dmg")

    install_flow._worker(info, installer.Eligibility(True, location=location, extension=".dmg"), "")

    assert staged_record.read(str(tmp_path))["target"] == BUNDLE


# ---------------------------------------------------------------------------
# The Preferences switch
# ---------------------------------------------------------------------------


def test_the_setting_is_on_by_default_and_persists_per_user(monkeypatch):
    config, written = {}, {}
    monkeypatch.setattr(preferences, "get_config", lambda: config)
    monkeypatch.setattr(preferences, "add_config",
                        lambda key, value: written.update({key: value}) or True)

    assert preferences.install_on_quit_enabled() is True
    assert preferences.set_install_on_quit(False) is True
    assert written == {INSTALL_ON_QUIT_CONFIG_KEY: False}
    config[INSTALL_ON_QUIT_CONFIG_KEY] = False
    assert preferences.install_on_quit_enabled() is False


def test_an_unreadable_config_keeps_installing(monkeypatch):
    monkeypatch.setattr(preferences, "get_config", MagicMock(side_effect=OSError))
    assert preferences.install_on_quit_enabled() is True


def _source(relative):
    return (UPDATES / relative).read_text(encoding="utf-8")


def test_the_switch_is_a_translatable_skip_save_preference():
    tree = ast.parse(_source("ui/properties/update_preferences.py"))
    call = next(node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "BoolProperty")
    keywords = {kw.arg: kw.value for kw in call.keywords}
    assert ast.literal_eval(keywords["name"]) == "Install updates when I quit Mixar"
    assert ast.literal_eval(keywords["options"]) == {"SKIP_SAVE"}
    assert {"get", "set"} <= set(keywords)
    assert "WindowManager.mixar_install_updates_on_quit" in _source(
        "ui/properties/update_preferences.py")


def test_the_switch_lives_in_preferences_system():
    source = _source("ui/panels/updates_panel.py")
    assert "bl_space_type = 'PREFERENCES'" in source and 'bl_context = "system"' in source
    assert '"mixar_install_updates_on_quit"' in source
    assert "classes = (" in source
