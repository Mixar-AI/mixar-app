# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The zero-question first-Send bootstrap for Add-on Project Mode.

The chat is the mode's only control: the agent creates, selects, enables,
disables, uninstalls and rolls back add-on packages through its own
``addon_project_v1`` RPC tools, and the projects root is the Mixar
Preference "Add-on Projects Folder". Nothing here registers a UI class;
the Send operator (``space_mixie_chat/ui/operators/chat_ops.py``) calls this
helper before its first ``build_project_context``.
"""

import bpy

from ..service import get_addon_project_service


def ensure_addon_project_ready(operator) -> bool:
    """Make an unlinked project-mode Send proceed in the SAME action.

    Zero questions: the projects root is the ``addon_projects_dir``
    Preference (default ``~/Mixar Addons``), created on first use by
    link_workspace_root, linked as THE project (idempotent), and the scene
    props are set, so the caller falls straight through to
    build_project_context. False only on real failures, with the error
    reported.
    """
    try:
        service = get_addon_project_service()
        first_time = service.get_workspace_root() is None
        result = service.link_workspace_root()
    except Exception as exc:
        operator.report({'ERROR'}, getattr(exc, "message", str(exc)))
        return False
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        scene.mixie_addon_project_id = result["project_id"]
        scene.mixie_addon_project_name = result["name"]
        scene.mixie_chat_mode = 'ADDON_PROJECT'
    if first_time:
        operator.report(
            {'INFO'},
            f"Add-ons will be created in '{result['name']}' — change the "
            "folder under Mixar Preferences",
        )
    return True
