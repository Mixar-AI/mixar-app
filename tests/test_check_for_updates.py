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
from mixar.modules.common.updates.core import trigger
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
    trigger._push_up_to_date_toast()
    item = _toast()
    assert item.type.value == "success"
    assert item.ttl_ms == 6000
    assert not item.is_sticky
    assert item.dismissible is True


def test_check_failed_toast_is_transient_error():
    trigger._push_check_failed_toast()
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
