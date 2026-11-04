# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Topbar update badge: state -> colour and state -> label.

Red (``row.alert``) reads as an error, so it is reserved for a forced
update the user has not started on. A download in progress, a staged
installer and an install under way draw as the regular theme button.
After the last byte arrives the worker still runs the signature check
in DOWNLOADING, so the badge says "Verifying…" rather than sitting on
"Downloading 100%".
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


def test_forced_download_at_100_percent_is_not_red():
    """The Slack report: a forced update's badge sat on red "Downloading 100%"."""
    state = get_update_state()
    info = _info(force_update=True)
    state.set_available(info)
    state.set_downloading()
    state.set_download_progress(400 * MB, 400 * MB)
    assert badge_alert(state, info) is False
    assert badge_label(state) == "Verifying…"


def test_label_moves_from_percentage_to_verifying_to_restart():
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()
    assert badge_label(state) == "Downloading…"
    state.set_download_progress(399 * MB, 400 * MB)
    assert badge_label(state) == "Downloading 99%"  # floored: never 100% early
    state.set_download_progress(400 * MB, 400 * MB)
    assert badge_label(state) == "Verifying…"
    state.set_ready("/tmp/Mixar-4.1.3.dmg", True)
    assert badge_label(state) == "Restart to Update"


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
    state.set_downloading()

    layout = MagicMock()
    draw_update_badge(layout)
    row = layout.row.return_value
    assert row.alert is False
    row.operator.assert_called_once()
    assert row.operator.call_args.kwargs["text"] == "Downloading…"

    state.set_install_failed("Download failed")
    layout = MagicMock()
    draw_update_badge(layout)
    assert layout.row.return_value.alert is True


def test_already_staged_installer_reports_full_progress_before_verifying():
    """Skipping the download must still read "Verifying…", not "Downloading…"."""
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


@pytest.mark.parametrize("install_state", list(InstallState))
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
