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
from mixar.modules.common.updates.core.trigger import _push_update_toast, is_forced


def _info(**overrides) -> UpdateInfo:
    defaults = dict(
        latest_version="9.9.9",
        current_version="1.0.0",
        severity="recommended",
        force_update=False,
        unsupported=False,
        changelog_summary="",
        changelog_url="",
        download_url="https://example.com/x.dmg",
        download_size_bytes=1,
        sha256="a" * 64,
        installer_type="dmg",
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


def test_is_forced_flags():
    assert is_forced(_info()) is False
    assert is_forced(_info(force_update=True)) is True
    assert is_forced(_info(unsupported=True)) is True


def test_normal_toast_has_skip_and_is_dismissible():
    _push_update_toast(_info(), ready=True)
    item = _pushed_item()
    assert item.dismissible is True
    assert item.title == "Mixar Update Ready"
    assert [a.label for a in item.actions] == ["Skip", "Install Update"]


def test_forced_toast_has_no_skip_and_is_not_dismissible():
    _push_update_toast(_info(force_update=True), ready=True)
    item = _pushed_item()
    assert item.dismissible is False
    assert item.title == "Mixar Update Required"
    assert item.priority == "critical"
    assert [a.label for a in item.actions] == ["Install Update"]
    assert "required" in item.body


def test_unsupported_toast_is_treated_as_forced():
    _push_update_toast(_info(unsupported=True), ready=False)
    item = _pushed_item()
    assert item.dismissible is False
    assert [a.label for a in item.actions] == ["Install Update"]


def test_available_wording_when_not_ready():
    _push_update_toast(_info(), ready=False)
    item = _pushed_item()
    assert item.title == "Mixar Update Available"
    assert "available" in item.body
