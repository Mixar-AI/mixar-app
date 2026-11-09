# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Topbar update badge: state -> visibility, colour and label.

The badge is hidden while the installer stages in the background
(DOWNLOADING, including the signature check after the last byte) and
appears as "Restart to Update" once READY, the way Chrome / VS Code /
Slack download silently. Red (``row.alert``) reads as an error, so it is
reserved for a forced update the user has not started on; a staged
installer and an install under way draw as the regular theme button.
"""

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

from mixar.modules.common.updates.constants import InstallState
from mixar.modules.common.updates.core import toasts
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state
from mixar.modules.common.updates.ui.topbar_badge import (
    badge_alert,
    badge_label,
    draw_update_badge,
)

UPDATES = SCRIPTS / "mixar" / "modules" / "common" / "updates"
MB = 1024 * 1024


def _info(**overrides) -> UpdateInfo:
    defaults = dict(
        latest_version="4.1.3",
        current_version="4.1.2",
        download_url="https://cdn.example.com/Mixar-4.1.3.dmg",
        download_sha256="b" * 64,
        download_size=400 * MB,
        installer_type="dmg",
    )
    defaults.update(overrides)
    return UpdateInfo(**defaults)


def setup_function(_fn):
    get_update_state().set_idle()


def _enter(state, install_state):
    """Drive the singleton into *install_state* through its public setters."""
    if install_state is InstallState.IDLE:
        state.set_install_idle()
    elif install_state is InstallState.DOWNLOADING:
        state.set_downloading()
        state.set_download_progress(100 * MB, 400 * MB)
    elif install_state is InstallState.READY:
        state.set_ready("/tmp/Mixar-4.1.3.dmg", True)
    elif install_state is InstallState.INSTALLING:
        state.set_ready("/tmp/Mixar-4.1.3.dmg", True)
        state.set_installing()
    elif install_state is InstallState.FAILED:
        state.set_install_failed("Download failed")
    elif install_state is InstallState.UNSUPPORTED:
        state.set_install_unsupported("read-only install")
    assert state.install_state is install_state


# Every InstallState must appear in both tables, so a new state cannot
# silently inherit a colour.
FORCED_ALERT = {
    InstallState.IDLE: True,
    InstallState.DOWNLOADING: False,
    InstallState.READY: False,
    InstallState.INSTALLING: False,
    InstallState.FAILED: True,
    InstallState.UNSUPPORTED: True,
}


def test_alert_table_covers_every_install_state():
    assert set(FORCED_ALERT) == set(InstallState)


@pytest.mark.parametrize("install_state", list(InstallState))
def test_optional_update_is_never_red(install_state):
    state = get_update_state()
    info = _info()
    state.set_available(info)
    _enter(state, install_state)
    assert badge_alert(state, info) is False


@pytest.mark.parametrize("install_state", list(InstallState))
@pytest.mark.parametrize("flag", ["force_update", "unsupported"])
def test_forced_update_is_red_only_while_nothing_is_in_progress(install_state, flag):
    state = get_update_state()
    info = _info(**{flag: True})
    state.set_available(info)
    _enter(state, install_state)
    assert badge_alert(state, info) is FORCED_ALERT[install_state]


def _drawn_label(layout):
    """The badge text *layout* received, or None when nothing was drawn."""
    if not layout.row.called:
        return None
    return layout.row.return_value.operator.call_args.kwargs["text"]


# Mid-download, then every byte in and the worker still verifying.
STAGING_PROGRESS = [(0, 0), (0, 400 * MB), (200 * MB, 400 * MB), (400 * MB, 400 * MB)]


@pytest.mark.parametrize("flag", ["", "force_update", "unsupported"])
@pytest.mark.parametrize("transferred,total", STAGING_PROGRESS)
def test_badge_is_hidden_while_the_installer_stages(flag, transferred, total):
    state = get_update_state()
    state.set_available(_info(**({flag: True} if flag else {})))
    state.set_downloading()
    state.set_download_progress(transferred, total)

    layout = MagicMock()
    draw_update_badge(layout)
    layout.row.assert_not_called()
    layout.operator.assert_not_called()


@pytest.mark.parametrize("flag", ["", "force_update", "unsupported"])
def test_badge_appears_as_restart_to_update_once_ready(flag):
    state = get_update_state()
    info = _info(**({flag: True} if flag else {}))
    state.set_available(info)
    state.set_downloading()
    state.set_download_progress(400 * MB, 400 * MB)
    layout = MagicMock()
    draw_update_badge(layout)
    assert _drawn_label(layout) is None

    state.set_ready("/tmp/Mixar-4.1.3.dmg", True)
    layout = MagicMock()
    draw_update_badge(layout)
    row = layout.row.return_value
    assert _drawn_label(layout) == "Restart to Update"
    assert row.operator.call_args.args == ("mixar.restart_to_update",)
    assert row.alert is False  # under way: never the error red, forced or not


@pytest.mark.parametrize("install_state,label", [
    (InstallState.IDLE, "Update Available"),
    (InstallState.FAILED, "Update Available"),
    (InstallState.UNSUPPORTED, "Update Available"),
    (InstallState.READY, "Restart to Update"),
    (InstallState.INSTALLING, "Updating…"),
])
def test_states_the_user_acts_on_keep_their_badge(install_state, label):
    state = get_update_state()
    state.set_available(_info())
    _enter(state, install_state)
    layout = MagicMock()
    draw_update_badge(layout)
    assert _drawn_label(layout) == label
    assert badge_label(state) == label


def test_downloading_toast_body_says_verifying_once_bytes_are_in():
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()
    state.set_download_progress(200 * MB, 400 * MB)
    assert toasts._download_body(state).startswith("50%")
    state.set_download_progress(400 * MB, 400 * MB)
    assert toasts._download_body(state) == "Verifying download…"


def test_draw_update_badge_applies_badge_alert():
    state = get_update_state()
    info = _info(force_update=True)
    state.set_available(info)
    state.set_ready("/tmp/Mixar-4.1.3.dmg", True)

    layout = MagicMock()
    draw_update_badge(layout)
    row = layout.row.return_value
    assert row.alert is False
    row.operator.assert_called_once()

    state.set_install_failed("Download failed")
    layout = MagicMock()
    draw_update_badge(layout)
    assert layout.row.return_value.alert is True


def test_already_staged_installer_reports_full_progress_before_verifying():
    """Skipping the download must read "Verifying download…" in the toast a
    user waiting on Restart & Update sees, not "Starting download…"."""
    tree = ast.parse((UPDATES / "core" / "install_flow.py").read_text())
    worker = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_worker"
    )
    lines = {}
    for node in ast.walk(worker):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            lines.setdefault(node.func.attr, node.lineno)
    assert "set_download_progress" in lines
    assert lines["set_download_progress"] < lines["verify_installer"]


DRAWN_STATES = [s for s in InstallState if s is not InstallState.DOWNLOADING]


@pytest.mark.parametrize("install_state", DRAWN_STATES)
def test_badge_invokes_restart_only_when_installer_is_ready(install_state):
    state = get_update_state()
    state.set_available(_info())
    _enter(state, install_state)
    layout = MagicMock()
    # Headers can inherit EXEC_REGION_WIN, skipping the restart dialog.
    layout.row.return_value.operator_context = 'EXEC_REGION_WIN'
    draw_update_badge(layout)
    row = layout.row.return_value
    assert row.operator_context == 'INVOKE_DEFAULT'
    expected = (
        "mixar.restart_to_update" if install_state is InstallState.READY
        else "mixar.show_update_toast"
    )
    assert row.operator.call_args.args == (expected,)


def test_badge_does_not_draw_without_update_info():
    layout = MagicMock()
    draw_update_badge(layout)
    layout.row.assert_not_called()


# ---------------------------------------------------------------------------
# The badge appears without user input when staging ends
#
# Nothing redraws the topbar every second during a background download any
# more, so the hand-off back to the main thread at the end of _worker must
# tag it — or "Restart to Update" would wait for the mouse to move.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("toast_on_screen", [True, False])
@pytest.mark.parametrize("outcome,label", [
    ("ready", "Restart to Update"),
    ("failed", "Update Available"),
    ("cancelled", "Update Available"),
])
def test_end_of_staging_redraws_the_topbar(monkeypatch, tmp_path, outcome, label,
                                           toast_on_screen):
    from types import SimpleNamespace

    from mixar.modules.common.notifications.store import get_notification_store
    from mixar.modules.common.updates.core import install_flow, update_checker

    state = get_update_state()
    info = _info()
    state.set_available(info)
    state.set_downloading()
    get_notification_store().clear_all()
    if toast_on_screen:
        toasts.push_update_available_toast(info)

    timers = []
    monkeypatch.setattr(
        install_flow.bpy.app.timers, "register", lambda fn, **_kw: timers.append(fn))
    redraws = []
    monkeypatch.setattr(toasts, "tag_topbar_redraw", lambda: redraws.append(1))
    # Already announced: the READY toast must not be what redraws the badge.
    monkeypatch.setattr(update_checker, "get_announced_stage", lambda _v: "ready")
    monkeypatch.setattr(install_flow, "capture_download_outcome", lambda *_a: None)

    path = tmp_path / "Mixar-4.1.3.dmg"
    monkeypatch.setattr(install_flow, "_prepare_staging", lambda *_a: str(path))

    def fake_download(_url, dest, _sha, on_progress, should_cancel):
        if outcome == "cancelled":
            raise install_flow.download.UpdateDownloadCancelled()
        if outcome == "failed":
            raise install_flow.download.UpdateDownloadError("boom")
        Path(dest).write_bytes(b"x")
        on_progress(1, 1)

    monkeypatch.setattr(install_flow.download, "download_installer", fake_download)
    monkeypatch.setattr(
        install_flow.verify, "verify_installer",
        lambda *_a, **_kw: (install_flow.verify.VERIFIED, "", ""))

    install_flow._worker(info, SimpleNamespace(extension=".dmg", location=None), "")

    # The worker thread never touches bpy: the state has moved, but the
    # topbar only learns of it from the follow-up queued for the main thread.
    assert redraws == []
    assert timers, "no main-thread follow-up scheduled"

    for fn in timers:
        fn()

    assert redraws, "staging ended without tagging the topbar"
    layout = MagicMock()
    draw_update_badge(layout)
    assert _drawn_label(layout) == label
