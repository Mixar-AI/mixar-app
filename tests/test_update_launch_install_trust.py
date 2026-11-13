# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What install at launch must never install (issue 2079 review): a
download verified more than a day ago, a release the update check no
longer offers, or an installer this launch has not verified itself
against a pinned Team ID — the staged record is the user's to edit, so
its own "verified" and signer never count."""

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from update_launch_fixtures import HELPER_PID, _begin, _record
from update_launch_fixtures import staged_fixture, this_copy_fixture  # noqa: F401 - fixtures

import pytest

from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import HELPER_MARKER_NAME, UPDATE_NOTIFICATION_ID
from mixar.modules.common.updates.core import (
    app_paths,
    install_marker,
    launch_install,
    staged_record,
    update_checker,
    verify,
)
from mixar.modules.common.updates.core.state import UpdateInfo


def _offered(version, sha256="a" * 64):
    """An update check's parsed answer (the staged installer's sha256)."""
    return UpdateInfo(latest_version=version, current_version="3.3.6",
                      download_sha256=sha256, installer_type="dmg")


@pytest.mark.parametrize("age", [24 * 3600 + 60, 30 * 24 * 3600, -3600, None])
def test_an_old_download_is_not_installed_at_launch(staged, age):
    """Never an old download: one verified more than a day ago (or with a
    clock that says the future, or no time at all) waits for the update
    check to re-verify it."""
    written = None if age is None else time.time() - age
    _record(staged.directory, staged.dmg, written_at=written)

    assert launch_install.launch_install_request() is None
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 0


def test_a_download_from_today_still_installs(staged):
    _record(staged.directory, staged.dmg, written_at=time.time() - 23 * 3600)
    assert launch_install.launch_install_request() is not None


@pytest.mark.parametrize("offered", [
    None, _offered("3.4.1"), _offered("3.3.9"), _offered("3.4.0", sha256="b" * 64),
])
def test_an_update_check_that_no_longer_offers_it_forgets_it(this_copy, offered):
    """A pulled release (nothing offered; a platform without an artifact is
    answered the same way), a superseded one, a rollback, or the same
    version re-published as another installer: the record and its
    installer go, so no later launch installs them."""
    launch_install.forget_unoffered(offered)

    assert staged_record.read(str(this_copy.directory)) is None
    assert not this_copy.dmg.exists()
    assert launch_install.launch_install_request() is None


def test_an_offer_that_does_not_say_which_installer_forgets_nothing(this_copy):
    """``download: null``: the backend could not presign the installer (no
    CDN) and still offers the version. Unknown is not unoffered."""
    launch_install.forget_unoffered(_offered("3.4.0", sha256=""))

    assert staged_record.read(str(this_copy.directory))["version"] == "3.4.0"
    assert this_copy.dmg.exists()


def test_an_update_check_offering_it_again_keeps_it(this_copy):
    launch_install.forget_unoffered(_offered("3.4"))  # 3.4 is 3.4.0

    assert staged_record.read(str(this_copy.directory))["version"] == "3.4.0"
    assert this_copy.dmg.exists()


def test_another_copy_s_check_leaves_its_download_alone(this_copy, monkeypatch):
    monkeypatch.setattr(app_paths, "running_target", lambda: "/Users/u/build/Mixar.app")

    launch_install.forget_unoffered(None)

    assert staged_record.read(str(this_copy.directory)) is not None and this_copy.dmg.exists()


def test_a_helper_installing_from_the_directory_keeps_it(this_copy, monkeypatch):
    record = {"helper_pid": HELPER_PID, "helper_created": None, "target_version": "3.4.0",
              "attempt_id": "a1", "written_at": time.time()}
    (this_copy.directory / HELPER_MARKER_NAME).write_text(json.dumps(record))
    monkeypatch.setattr(install_marker, "process_identity", lambda pid: (True, None))

    launch_install.forget_unoffered(None)

    assert this_copy.dmg.exists()


def test_forgetting_never_deletes_outside_the_staging_directory(this_copy, tmp_path):
    elsewhere = tmp_path / "keep.dmg"
    elsewhere.write_bytes(b"user file")
    _record(this_copy.directory, this_copy.dmg, installer=str(elsewhere))

    launch_install.forget_unoffered(None)

    assert elsewhere.exists()
    assert staged_record.read(str(this_copy.directory)) is None


@pytest.mark.parametrize("payload, offered", [
    ({"update_available": False}, None),
    ({"update_available": True, "latest_version": "3.5.0"}, "3.5.0"),
])
def test_every_answered_update_check_tidies_the_staged_download(monkeypatch, payload, offered):
    from mixar.modules.common.updates.core import state as update_state
    from mixar.modules.common.updates.core import toasts, trigger

    seen = []
    monkeypatch.setattr(launch_install, "forget_unoffered", seen.append)
    monkeypatch.setattr(trigger, "_start_installer_download", lambda info: None)
    monkeypatch.setattr(toasts, "push_update_available_toast", lambda info: None)
    monkeypatch.setattr(toasts, "tag_topbar_redraw", lambda: None)
    monkeypatch.setattr(update_checker, "get_announced_stage", lambda version: "")
    monkeypatch.setattr(update_checker, "set_announced_stage", lambda *a: None)

    trigger._on_check_success(SimpleNamespace(data=payload))

    assert [getattr(info, "latest_version", None) for info in seen] == [offered]
    update_state.get_update_state().set_idle()


@pytest.mark.parametrize("verdict", [
    (verify.UNVERIFIED, "This app has no readable Team ID to pin the update to", ""),
    (verify.REJECTED, "Disk image was not signed by this app's Apple team", ""),
    (verify.VERIFIED, "TEAM123", ""),
])
def test_the_launch_checks_the_signature_itself(staged, verdict):
    """The record is the user's to edit: it saying "verified" by a signer
    is never enough. The launch's own check must verify and pin a team."""
    staged.verdict[0] = verdict
    resume = MagicMock()
    launch_install.begin_launch_install(launch_install.launch_install_request(), resume)

    assert launch_install._await_verdict() is None

    resume.assert_called_once_with()
    staged.begin.assert_not_called()
    assert launch_install._install not in staged.timers.registered
    assert not get_notification_store().contains(UPDATE_NOTIFICATION_ID)
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 0
    # Stood down before its update check was due: that check asks nothing
    # (the resumed start-up runs the normal one).
    assert launch_install._check_offer() is None
    assert staged.asked == []


# ---------------------------------------------------------------------------
# This launch's own update check must still offer the staged version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer, forgotten", [
    ({"update_available": False}, True),                               # pulled, or nothing newer
    ({"update_available": True, "latest_version": "3.5.0"}, True),     # superseded
    ({"update_available": True, "latest_version": "3.3.9"}, True),     # rolled back
    # The same version re-published as another installer: the sha256 names
    # the file (the URL may be presigned per check).
    ({"update_available": True, "latest_version": "3.4.0", "download": {"sha256": "b" * 64}},
     True),
    # download: null (presigning failed without a CDN): which installer is
    # unknown, so it stands down and forgets nothing.
    ({"update_available": True, "latest_version": "3.4.0", "download": None}, False),
    (ConnectionError("offline"), False),                               # the check failed
    ("cannot_start", False),                                           # it could not even ask
])
def test_the_launch_installs_only_what_its_own_update_check_offers(staged, monkeypatch,
                                                                   answer, forgotten):
    """A verified download a day old may be a release the backend has since
    pulled or replaced: the launch installs only once this launch's own
    check has answered with the staged version, and a check that fails
    stands it down too (it forgets nothing: it learned nothing)."""
    if answer == "cannot_start":
        from mixar.modules.common.updates.core import trigger

        def broken(on_success, on_error):
            raise RuntimeError("no API client")

        monkeypatch.setattr(trigger, "request_update_check", broken)
    else:
        staged.offer[0] = answer
    resume = MagicMock()
    launch_install.begin_launch_install(launch_install.launch_install_request(), resume)
    assert launch_install._await_verdict() == launch_install._VERIFY_POLL_S  # verified, waiting

    launch_install._check_offer()
    assert launch_install._await_verdict() is None

    resume.assert_called_once_with()
    staged.begin.assert_not_called()
    assert launch_install._install not in staged.timers.registered
    assert not get_notification_store().contains(UPDATE_NOTIFICATION_ID)
    assert (staged_record.read(str(staged.directory)) is None) == forgotten
    assert staged.dmg.exists() != forgotten


def test_versions_compare_by_value_not_as_text(staged):
    """A record naming 3.4 is the offered 3.4.0 (``installer._same_version``)."""
    _record(staged.directory, staged.dmg, version="3.4")

    _begin(staged)  # announced: this launch's check still offers it

    assert staged_record.read(str(staged.directory))["version"] == "3.4"


def test_another_version_on_offer_stands_down_before_the_signature_check_ends(staged, monkeypatch):
    monkeypatch.setattr(launch_install, "_in_background", lambda fn, *args: None)
    staged.offer[0] = {"update_available": True, "latest_version": "3.5.0"}
    resume = MagicMock()
    launch_install.begin_launch_install(launch_install.launch_install_request(), resume)

    launch_install._check_offer()
    assert launch_install._await_verdict() is None

    resume.assert_called_once_with()


def test_an_update_check_that_never_answers_stands_down(staged):
    staged.offer[0] = None  # asked, never answered
    resume = MagicMock()
    launch_install.begin_launch_install(launch_install.launch_install_request(), resume)
    launch_install._check_offer()
    assert launch_install._await_verdict() == launch_install._VERIFY_POLL_S
    assert not get_notification_store().contains(UPDATE_NOTIFICATION_ID)

    launch_install._pending["check"]["started"] -= launch_install._VERIFY_DEADLINE_S + 1
    assert launch_install._await_verdict() is None

    resume.assert_called_once_with()
    staged.begin.assert_not_called()
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 0


def test_the_helper_pins_the_launch_s_own_signer_not_the_record_s(staged):
    _record(staged.directory, staged.dmg, signer="FORGED")
    staged.verdict[0] = (verify.VERIFIED, "TEAM123", "TEAM123")
    _begin(staged)

    launch_install._install()

    kwargs = staged.begin.call_args.kwargs
    assert kwargs["verified"] is True and kwargs["signer_thumbprint"] == "TEAM123"


def test_a_signature_check_that_never_ends_stands_down(staged, monkeypatch):
    monkeypatch.setattr(launch_install, "_in_background", lambda fn, *args: None)
    resume = MagicMock()
    launch_install.begin_launch_install(launch_install.launch_install_request(), resume)
    assert launch_install._await_verdict() == launch_install._VERIFY_POLL_S  # still running

    launch_install._pending["check"]["started"] -= launch_install._VERIFY_DEADLINE_S + 1
    assert launch_install._await_verdict() is None

    resume.assert_called_once_with()
    staged.begin.assert_not_called()


def test_the_signature_worker_never_raises(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("codesign exploded")

    monkeypatch.setattr(verify, "verify_installer", broken)
    check = {"verdict": None}
    launch_install._verify_worker(check, "/u/Mixar.dmg", "/Applications/Mixar.app", "")
    assert check["verdict"][0] == verify.UNVERIFIED
