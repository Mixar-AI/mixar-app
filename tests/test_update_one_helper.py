# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One update helper per process (issue 2079). Whichever starts first —
the launch install, Restart & Update or the quit — no second one starts
while it waits: the macOS helper's script for a version is rewritten in
place while the first helper's shell still reads it, and both would swap
the bundle. The launch install's own quit can find the update READY:
Help > Check for Updates or an ``update`` notification during its wait
stages the same, already downloaded version within seconds.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from update_launch_fixtures import FakeTimers, _begin
from update_launch_fixtures import staged_fixture  # noqa: F401 - the `staged` fixture

import pytest

from mixar.modules.common.updates.constants import InstallState
from mixar.modules.common.updates.core import (
    install_flow,
    install_gate,
    install_start,
    launch_install,
    silent_install,
)
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state


@pytest.fixture(name="checked_again")
def checked_again_fixture(staged, monkeypatch):
    """Help > Check for Updates during the launch's wait: 3.4.0 offered,
    found already staged, verified again — READY in this process too."""
    monkeypatch.setattr(silent_install, "install_on_quit_enabled", lambda: True)
    monkeypatch.setattr(install_gate, "check", lambda eligibility: "")
    monkeypatch.setattr(install_flow, "bpy", SimpleNamespace(
        app=SimpleNamespace(timers=FakeTimers()), ops=MagicMock()))
    state = get_update_state()

    def ready():
        state.set_available(UpdateInfo(
            latest_version="3.4.0", current_version="3.3.6",
            download_url="https://cdn.example.com/Mixar-3.4.0.dmg",
            download_sha256="a" * 64, installer_type="dmg"))
        state.set_downloading()
        state.set_ready(str(staged.dmg), True, "TEAM123")

    yield ready
    state.set_idle()


def _triggers(staged):
    return [call.kwargs["trigger"] for call in staged.begin.call_args_list]


@pytest.mark.parametrize("ready_when", ["before", "after"])
def test_the_launch_install_s_quit_starts_no_second_helper(staged, checked_again, ready_when):
    """READY before the launch's helper starts, or after it (a download
    already under way when it did): its quit installs nothing more."""
    _begin(staged)
    if ready_when == "before":
        checked_again()
    launch_install._install()
    if ready_when == "after":
        checked_again()

    assert silent_install.install_on_quit(True) is False
    assert _triggers(staged) == ["launch"]


def test_restart_and_update_after_the_launch_s_helper_starts_none(staged, checked_again):
    _begin(staged)
    checked_again()
    launch_install._install()

    started, _message = install_flow.apply_and_restart()

    assert started is False
    assert _triggers(staged) == ["launch"]


def test_the_launch_starts_none_beside_restart_and_update_s(staged, checked_again):
    resume = _begin(staged)
    checked_again()
    assert install_flow.apply_and_restart() == (True, "")

    launch_install._install()

    assert _triggers(staged) == ["click"]
    resume.assert_called_once_with()  # stood down; the click's quit follows


def test_restart_and_update_s_own_quit_starts_none(staged, checked_again):
    """Already held by INSTALLING; the guard holds it too."""
    checked_again()
    assert install_flow.apply_and_restart() == (True, "")
    assert get_update_state().install_state is InstallState.INSTALLING

    assert silent_install.install_on_quit(True) is False
    assert _triggers(staged) == ["click"]


def test_a_helper_taken_back_lets_the_next_one_start(staged, checked_again):
    """The launch's quit never came: its watchdog kills the helper, and the
    update installs on the user's own quit later."""
    _begin(staged)
    launch_install._install()
    launch_install._quit_watchdog()
    assert not install_start.helper_started()
    checked_again()

    assert silent_install.install_on_quit(True) is True
    assert _triggers(staged) == ["launch", "quit"]


def test_a_helper_that_failed_to_start_leaves_none_waiting(staged, checked_again):
    """A spawn that raised started nothing: the next start is not refused."""
    checked_again()
    staged.begin.side_effect = [OSError("no /bin/sh"), staged.proc]

    assert silent_install.install_on_quit(True) is False
    assert not install_start.helper_started()
    assert silent_install.install_on_quit(True) is True
    assert _triggers(staged) == ["quit", "quit"]


def test_the_quit_beside_a_waiting_helper_checks_nothing_and_logs_no_error(
        staged, checked_again, monkeypatch):
    """Returned before the gate: no eligibility or process-table read, and
    no "Install on quit failed" from start_helper's refusal."""
    _begin(staged)
    launch_install._install()
    checked_again()
    eligibility_checks = len(staged.info)
    logger = MagicMock()
    monkeypatch.setattr(silent_install, "logger", logger)

    assert silent_install.install_on_quit(True) is False

    assert len(staged.info) == eligibility_checks
    logger.error.assert_not_called()
    assert _triggers(staged) == ["launch"]
