# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every alert is a notification in the viewport's bottom-left toast lane.

Completion summaries, generation errors and refusals used to open a
``window_manager.popup_menu`` under the cursor ("Image to 3D batch complete",
"Auto Rig complete", "Detect Views Error", "Blender Plugin Import",
"Message not sent"), so alerts showed up wherever the pointer happened to be
and in a different style from the toasts. They are pushed to the notification
store now. ``popup_menu`` stays only for menus the user opened on purpose and
acts in; that allowlist is pinned here, so a new alert popup fails this test.
"""

import ast
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.notifications.store import get_notification_store

# Interactive menus: each is opened by a click and its rows are operators.
INTERACTIVE_POPUP_MENUS = {
    "src/scripts/mixar/modules/director/ui/operators/strip_ops.py",
    "src/scripts/mixar/modules/director/ui/operators/surface_ops.py",
    "src/scripts/mixar/modules/moodboard/ui/operators/mesh_reference_ops.py",
    "src/scripts/mixar/modules/paint/ui/operators/layer_selection_ops.py",
}


def _popup_menu_callers():
    callers = set()
    for path in sorted((SCRIPTS / "mixar").rglob("*.py")):
        if "tests" in path.parts:
            continue
        with warnings.catch_warnings():
            # Unrelated modules carry invalid-escape string literals.
            warnings.simplefilter("ignore")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "popup_menu"
            ):
                callers.add(path.relative_to(ROOT).as_posix())
    return callers


def test_only_interactive_menus_use_popup_menu():
    assert _popup_menu_callers() == INTERACTIVE_POPUP_MENUS


def _run_timers_now(monkeypatch, module):
    monkeypatch.setattr(
        module.bpy.app.timers, "register",
        lambda fn, first_interval=0: fn(), raising=False,
    )


def _pushed(title):
    return [i for i in get_notification_store().get_visible() if i.title == title]


def test_generation_error_is_a_sticky_error_toast(monkeypatch):
    from mixar.modules.common.utils import mixie_space_utils as utils

    get_notification_store().clear_all()
    _run_timers_now(monkeypatch, utils)
    scene = SimpleNamespace(running=True, status="")

    utils.show_generation_error(
        scene, "Detect Views", "Could not reach the server", "running", "status",
    )

    [item] = _pushed("Detect Views failed")
    assert item.type.value == "error"
    assert item.body == "Could not reach the server"
    assert item.is_sticky
    assert (scene.running, scene.status) == (False, "Could not reach the server")


def test_scene_recon_submit_error_is_a_toast(monkeypatch):
    from mixar.modules.moodboard.core import scene_recon_submission as recon

    get_notification_store().clear_all()
    _run_timers_now(monkeypatch, recon)
    scene = SimpleNamespace(mixie_scene_recon_is_generating=True)

    recon.on_prompt_error(scene, None, "Failed to submit reconstruction job")

    [item] = _pushed("Scene Reconstruction failed")
    assert item.body == "Failed to submit reconstruction job"


def test_plugin_import_summary_is_a_toast():
    from mixar.modules.plugin_import.ui.operators import plugin_import_ops as ops

    store = get_notification_store()
    store.clear_all()
    clean = SimpleNamespace(
        imported=3, already_present=1, enabled=2, failed=0, enable_failed=0,
    )
    ops._notify_summary(clean, "")
    [item] = _pushed("Blender Plugin Import")
    assert item.type.value == "success"
    assert item.body == "Imported: 3\nAlready in Mixar: 1\nEnabled: 2"
    assert not item.is_sticky

    broken = SimpleNamespace(
        imported=1, already_present=0, enabled=0, failed=0, enable_failed=1,
    )
    ops._notify_summary(broken, "node_wrangler: missing dependency")
    [item] = _pushed("Blender Plugin Import")  # replaced, not stacked
    assert item.type.value == "warning"
    assert item.is_sticky
    assert item.body.endswith("Couldn't enable: 1\nnode_wrangler: missing dependency")


def test_refused_send_is_a_toast():
    from mixar.modules.space_mixie_chat.ui.properties import chat_props

    get_notification_store().clear_all()
    chat_props._report_send_refused("A turn is still running")
    chat_props._report_send_refused("A turn is still running")

    [item] = _pushed("Message not sent")
    assert item.type.value == "warning"
    assert item.body == "A turn is still running"
    assert not item.is_sticky
