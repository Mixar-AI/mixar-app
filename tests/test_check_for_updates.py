# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the manual Check for Updates flow (updates.core.trigger)."""

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

# mixie_space_utils introspects bpy.types.Panel.bl_rna at import time, which
# the bpy mock can't satisfy — stub it so the common.utils package can load.
sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
from mixar.modules.common.updates.core import toasts, trigger
from mixar.modules.common.updates.core.state import get_update_state


def setup_function(_fn):
    get_notification_store().clear_all()
    get_update_state().set_idle()
    trigger._interactive_check["active"] = False


def _toast():
    for item in get_notification_store().get_visible():
        if item.id == UPDATE_NOTIFICATION_ID:
            return item
    raise AssertionError("update toast not found in store")


def test_trigger_records_interactive_flag():
    assert trigger.trigger_update_check(interactive=True) is True
    assert trigger._interactive_check["active"] is True


def test_trigger_default_is_not_interactive():
    assert trigger.trigger_update_check() is True
    assert trigger._interactive_check["active"] is False


def test_trigger_skipped_while_active_keeps_flag_untouched():
    get_update_state().set_checking()
    assert trigger.trigger_update_check(interactive=True) is False
    assert trigger._interactive_check["active"] is False


def test_up_to_date_toast_is_transient_success():
    toasts.push_up_to_date_toast()
    item = _toast()
    assert item.type.value == "success"
    assert item.ttl_ms == 6000
    assert not item.is_sticky
    assert item.dismissible is True


def test_check_failed_toast_is_transient_error():
    toasts.push_check_failed_toast()
    item = _toast()
    assert item.type.value == "error"
    assert item.ttl_ms == 6000
    assert not item.is_sticky


def test_check_error_pushes_toast_only_when_interactive():
    trigger._interactive_check["active"] = False
    trigger._on_check_error(RuntimeError("offline"))
    store = get_notification_store()
    assert all(i.id != UPDATE_NOTIFICATION_ID for i in store.get_visible())

    trigger._interactive_check["active"] = True
    trigger._on_check_error(RuntimeError("offline"))
    assert _toast().title == "Could not check for updates"
    assert trigger._interactive_check["active"] is False


# ============================================================================
# Announce-once behaviour
#
# The topbar badge carries update status permanently, so the toast only
# announces a version — it does not re-announce it on every launch. What
# is recorded is "we already told them", not a user decision, which is why
# nothing needs an "unskip" affordance: the badge re-opens the toast.
# ============================================================================


class _FakeAnnouncements:
    """Stand-in for the on-disk announcement record."""

    def __init__(self):
        self.value = ""

    def get(self, version):
        recorded, _, stage = self.value.partition("=")
        return stage if recorded == version and version else ""

    def set(self, version, stage):
        self.value = f"{version}={stage}"


def _install_fake_announcements(monkeypatch):
    from mixar.modules.common.updates.core import update_checker

    fake = _FakeAnnouncements()
    monkeypatch.setattr(update_checker, "get_announced_stage", fake.get)
    monkeypatch.setattr(update_checker, "set_announced_stage", fake.set)
    return fake


def _response(version="3.9.0", **kwargs):
    payload = {
        "update_available": True,
        "latest_version": version,
        "current_version": "3.0.0",
        "severity": "recommended",
        "force_update": False,
        "unsupported": False,
    }
    payload.update(kwargs)
    return MagicMock(data={"data": payload})


def test_announced_stage_is_scoped_to_its_version():
    fake = _FakeAnnouncements()
    fake.set("3.9.0", "available")
    assert fake.get("3.9.0") == "available"
    # A newer release was never announced, so it still earns its toast
    # without anything having to be cleared first.
    assert fake.get("4.0.0") == ""


def test_first_check_announces_and_records(monkeypatch):
    fake = _install_fake_announcements(monkeypatch)
    monkeypatch.setattr(trigger, "_start_installer_download", lambda info: None)

    trigger._on_check_success(_response())

    assert _toast().title == "Mixar Update Available"
    assert fake.value == "3.9.0=available"


def test_second_check_of_the_same_version_shows_no_toast(monkeypatch):
    fake = _install_fake_announcements(monkeypatch)
    monkeypatch.setattr(trigger, "_start_installer_download", lambda info: None)
    fake.set("3.9.0", "available")

    trigger._on_check_success(_response())

    store = get_notification_store()
    assert all(i.id != UPDATE_NOTIFICATION_ID for i in store.get_visible())


def test_an_already_announced_version_still_stages_its_installer(monkeypatch):
    """Suppressing the toast must not suppress the download.

    The old Skip flow returned before staging, which is what made
    "Restart & Update" slow the next time the user changed their mind.
    """
    fake = _install_fake_announcements(monkeypatch)
    fake.set("3.9.0", "available")
    started = []
    monkeypatch.setattr(
        trigger, "_start_installer_download", lambda info: started.append(info),
    )

    trigger._on_check_success(_response())

    assert len(started) == 1


def test_interactive_check_re_announces(monkeypatch):
    """The user just asked — answer them, announced or not."""
    fake = _install_fake_announcements(monkeypatch)
    monkeypatch.setattr(trigger, "_start_installer_download", lambda info: None)
    fake.set("3.9.0", "available")
    trigger._interactive_check["active"] = True

    trigger._on_check_success(_response())

    assert _toast().title == "Mixar Update Available"


def test_forced_update_re_announces_every_check(monkeypatch):
    fake = _install_fake_announcements(monkeypatch)
    monkeypatch.setattr(trigger, "_start_installer_download", lambda info: None)
    fake.set("3.9.0", "available")

    trigger._on_check_success(_response(force_update=True))

    assert _toast().title == "Mixar Update Required"
