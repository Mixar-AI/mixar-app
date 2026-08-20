# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared project controls for the chat editor and floating Agent Bubble."""


def draw_project_controls(layout, scene, *, compact=False) -> None:
    if scene is None or getattr(scene, "mixie_chat_mode", "") != "ADDON_PROJECT":
        return

    row = layout.row(align=True)
    project_id = getattr(scene, "mixie_addon_project_id", "") or ""
    if not project_id:
        row.operator(
            "mixar.addon_project_link",
            text="Link Project" if compact else "Link Project Folder",
            icon='FILE_FOLDER',
        )
        return

    project_name = getattr(scene, "mixie_addon_project_name", "") or "Project linked"
    if not compact:
        row.label(text=project_name, icon='FILE_SCRIPT')
    row.operator(
        "mixar.addon_project_open_entrypoint",
        text="" if compact else "Open",
        icon='TEXT',
    )

    mutable = row.row(align=True)
    mutable.enabled = getattr(scene, "mixie_chat_state", "IDLE") not in {
        "BUSY", "MODIFYING", "CONNECTING",
    }
    mutable.operator(
        "mixar.addon_project_set_entrypoint",
        text="",
        icon='PREFERENCES',
    )
    mutable.operator(
        "mixar.addon_project_run_checks",
        text="" if compact else "Check",
        icon='CHECKMARK',
    )
    mutable.operator(
        "mixar.addon_project_rollback_last",
        text="",
        icon='LOOP_BACK',
    )
    mutable.operator(
        "mixar.addon_project_unlink",
        text="",
        icon='UNLINKED',
    )
