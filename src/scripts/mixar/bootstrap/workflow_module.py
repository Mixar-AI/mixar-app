# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Workflow Module Bootstrap.

Eagerly registers the dual-mode UI operators so the splash menu can call
them as soon as it is shown, before deferred UI module loading finishes.

This bootstrap deliberately does not activate any workspace on launch.
The startup splash owns the user's initial mode choice; switching the
workspace from a timer can dismiss the splash and can clone whatever
state was saved in the startup workspace.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.workflow.constants import PRO_DEFAULT_WORKSPACE_NAME
from mixar.modules.workflow.ui.headers.mode_filter_header import (
    install_topbar_filter,
    uninstall_topbar_filter,
)
from mixar.modules.workflow.ui.headers.view3d_header_filter import (
    install_view3d_header_filter,
    uninstall_view3d_header_filter,
)
from mixar.modules.workflow.ui.menus.mode_menu import (
    install_mode_menu_hook,
    uninstall_mode_menu_hook,
)
from mixar.modules.workflow.ui.operators.ui_mode_ops import classes as ui_mode_classes

logger = get_logger(__name__)

_all_classes = ui_mode_classes
_DEFAULT_MODELING_WORKSPACES = {PRO_DEFAULT_WORKSPACE_NAME, "Modelling"}
_OBJECT_MODE_RETRY_LIMIT = 20
_OBJECT_MODE_MSGBUS_OWNER = object()
_object_mode_retry_count = 0
_object_mode_done = False


def _ensure_modeling_workspace_object_mode():
    """Undo edit-mode state saved into Blender's default modeling workspace."""
    global _object_mode_done, _object_mode_retry_count
    if _object_mode_done:
        return None

    _object_mode_retry_count += 1

    try:
        window = bpy.context.window
        workspace = getattr(window, "workspace", None) if window is not None else None
        if workspace is None:
            return 0.2 if _object_mode_retry_count < _OBJECT_MODE_RETRY_LIMIT else None

        if workspace.name not in _DEFAULT_MODELING_WORKSPACES:
            return None

        obj = bpy.context.object
        if obj is None:
            return 0.2 if _object_mode_retry_count < _OBJECT_MODE_RETRY_LIMIT else None

        if getattr(obj, "mode", "OBJECT") != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            logger.info("workflow: reset default Modeling workspace to Object Mode")
        _object_mode_done = True
    except Exception as exc:  # noqa: BLE001 - startup guard must never break launch
        logger.debug("workflow: Object Mode startup reset skipped: %s", exc)
        if _object_mode_retry_count < _OBJECT_MODE_RETRY_LIMIT:
            return 0.2
    return None


def _schedule_object_mode_reset() -> None:
    global _object_mode_done, _object_mode_retry_count
    _object_mode_done = False
    _object_mode_retry_count = 0
    if not bpy.app.timers.is_registered(_ensure_modeling_workspace_object_mode):
        bpy.app.timers.register(_ensure_modeling_workspace_object_mode, first_interval=0.2)


def _on_workspace_change() -> None:
    _schedule_object_mode_reset()


def _subscribe_workspace_changes() -> None:
    bpy.msgbus.clear_by_owner(_OBJECT_MODE_MSGBUS_OWNER)
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Window, "workspace"),
            owner=_OBJECT_MODE_MSGBUS_OWNER,
            args=(),
            notify=_on_workspace_change,
        )
    except Exception as exc:  # noqa: BLE001 - never break startup
        logger.debug("workflow: workspace mode-reset msgbus skipped: %s", exc)


def register():
    """Eagerly register dual-mode operators used by the splash."""
    global _object_mode_done, _object_mode_retry_count
    _object_mode_done = False
    _object_mode_retry_count = 0

    for cls in _all_classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                logger.warning("Failed to register %s: %s", cls.__name__, e)

    # Install all UI patches synchronously so they are in place for the very
    # first paint. The patches only change drawing; they do not switch
    # workspace or mode during startup.
    install_topbar_filter()
    install_view3d_header_filter()
    install_mode_menu_hook()

    _subscribe_workspace_changes()
    _schedule_object_mode_reset()


def unregister():
    """Unregister dual-mode operators."""
    bpy.msgbus.clear_by_owner(_OBJECT_MODE_MSGBUS_OWNER)
    if bpy.app.timers.is_registered(_ensure_modeling_workspace_object_mode):
        bpy.app.timers.unregister(_ensure_modeling_workspace_object_mode)
    uninstall_mode_menu_hook()
    uninstall_view3d_header_filter()
    uninstall_topbar_filter()
    for cls in reversed(_all_classes):
        try:
            if getattr(cls, "is_registered", False):
                bpy.utils.unregister_class(cls)
        except Exception as e:  # noqa: BLE001 - defensive on shutdown
            logger.warning("Failed to unregister %s: %s", cls.__name__, e)
