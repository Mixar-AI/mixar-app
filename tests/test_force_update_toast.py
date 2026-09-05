# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for forced-update toast behavior (updates.core.trigger)."""

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
from mixar.modules.common.updates.core.state import UpdateInfo
from mixar.modules.common.updates.core.state import get_update_state
from mixar.modules.common.updates.core.toasts import push_update_available_toast
from mixar.modules.common.updates.core.update_checker import is_forced


def _info(**overrides) -> UpdateInfo:
    defaults = dict(
        latest_version="9.9.9",
        current_version="1.0.0",
        severity="recommended",
        force_update=False,
        unsupported=False,
        changelog_summary="",
        changelog_url="",
        browser_download_url="https://example.com/downloads",
    )
    defaults.update(overrides)
    return UpdateInfo(**defaults)


def _pushed_item():
    store = get_notification_store()
    for item in store.get_visible():
        if item.id == UPDATE_NOTIFICATION_ID:
            return item
    raise AssertionError("update toast not found in store")


def setup_function(_fn):
    get_notification_store().clear_all()
    # The toast renders from install state as well as from the info it is
    # handed; reset it so each case starts from "nothing staged".
    get_update_state().set_install_idle()


def test_is_forced_flags():
    assert is_forced(_info()) is False
    assert is_forced(_info(force_update=True)) is True
    assert is_forced(_info(unsupported=True)) is True


def test_normal_toast_is_dismissible_and_offers_only_the_action():
    push_update_available_toast(_info())
    item = _pushed_item()
    assert item.dismissible is True
    assert item.title == "Mixar Update Available"
    assert "available" in item.body
    assert [a.label for a in item.actions] == ["Download"]


def test_forced_toast_is_not_dismissible():
    push_update_available_toast(_info(force_update=True))
    item = _pushed_item()
    assert item.dismissible is False
    assert item.title == "Mixar Update Required"
    assert item.priority == "critical"
    assert [a.label for a in item.actions] == ["Download"]
    assert "required" in item.body


def test_unsupported_toast_is_treated_as_forced():
    push_update_available_toast(_info(unsupported=True))
    item = _pushed_item()
    assert item.dismissible is False
    assert [a.label for a in item.actions] == ["Download"]


def test_download_action_opens_downloads_page_operator():
    push_update_available_toast(_info())
    item = _pushed_item()
    download = next(a for a in item.actions if a.label == "Download")
    assert download.operator == "mixar.open_downloads_page"
