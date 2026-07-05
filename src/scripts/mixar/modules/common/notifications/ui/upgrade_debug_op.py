# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Credit-Upgrade Debug Operator

Dev-only helper to push the credit-upgrade toast without a backend trigger,
so the toast rendering + "Upgrade" handoff can be tested locally. Only
registers in non-production builds (``environment != "Prod"``).

Run from the Python console::

    import bpy
    bpy.ops.mixar.debug_push_credit_upgrade()

or via View3D ▸ View menu ▸ "Debug: Push Credit-Upgrade Toast".
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _is_dev() -> bool:
    """True when running a non-production build."""
    try:
        from mixar.config.config import get_environment

        return get_environment() != "Prod"
    except Exception:
        return False


class MIXAR_OT_debug_push_credit_upgrade(bpy.types.Operator):
    """Push a sample credit-upgrade toast (dev only)"""

    bl_idname = "mixar.debug_push_credit_upgrade"
    bl_label = "Debug: Push Credit-Upgrade Toast"
    bl_options = {"INTERNAL"}

    action_url: bpy.props.StringProperty(
        name="Action URL",
        description="Subscription URL the Upgrade button opens (blank = dashboard fallback)",
        default="",
    )

    def execute(self, context):
        from ..credit_upgrade import push_credit_upgrade

        push_credit_upgrade({
            "type": "credit_upgrade",
            "title": "You're out of credits",
            "body": "Upgrade your plan to keep generating.",
            "priority": "high",
            "action_url": self.action_url or None,
        })
        self.report({"INFO"}, "Pushed credit-upgrade toast")
        return {"FINISHED"}


def _draw_menu(self, context):
    self.layout.operator(
        MIXAR_OT_debug_push_credit_upgrade.bl_idname,
        icon="ERROR",
    )


def register():
    bpy.utils.register_class(MIXAR_OT_debug_push_credit_upgrade)
    if _is_dev():
        bpy.types.VIEW3D_MT_view.append(_draw_menu)


def unregister():
    if _is_dev():
        try:
            bpy.types.VIEW3D_MT_view.remove(_draw_menu)
        except Exception:
            pass
    bpy.utils.unregister_class(MIXAR_OT_debug_push_credit_upgrade)
