# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared project controls for the chat editor and floating Agent Bubble."""


_BUSY_STATES = {"BUSY", "MODIFYING", "CONNECTING"}
_MORE_MENU = "MIXAR_MT_addon_project_more"


def _compact_project_name(name: str, limit: int = 18) -> str:
    return name if len(name) <= limit else f"{name[:limit - 3]}..."


def draw_project_controls(
    layout,
    scene,
    *,
    compact=False,
    inline=False,
    setup_only=False,
) -> None:
    if scene is None or getattr(scene, "mixie_chat_mode", "") != "ADDON_PROJECT":
        return

    # The Agent Bubble tools region has a fixed two-row height.  Its compact
    # controls must therefore share the existing composer row instead of
    # allocating a third row that Blender clips below the window.
    row = layout if inline else layout.row(align=True)
    project_id = getattr(scene, "mixie_addon_project_id", "") or ""
    if not project_id:
        # Primary flow: name a new add-on inside the one-time projects root
        # (the operator opens the root picker first when none is saved yet).
        # Everything else (open existing, link arbitrary folder, change the
        # root) lives in the workspace menu — exactly two small buttons, so
        # the fixed-height Agent Bubble composer row never overflows. The
        # menu queries the workspace only when opened, keeping disk IO out
        # of this draw callback.
        row.operator(
            "mixar.addon_project_new",
            text="New Add-on",
            icon='FILE_NEW',
        )
        row.menu(
            "MIXAR_MT_addon_project_workspace",
            text="" if compact else "Add-on Projects",
            icon='DOWNARROW_HLT',
        )
        return
    if setup_only:
        return

    project_name = getattr(scene, "mixie_addon_project_name", "") or "Project linked"
    row.label(
        text=_compact_project_name(project_name) if compact else project_name,
        icon='FILE_SCRIPT',
    )
    # With the projects root linked as THE project, switching the active
    # add-on (and the other workspace actions) stays one icon away.
    row.menu(
        "MIXAR_MT_addon_project_workspace",
        text="",
        icon='DOWNARROW_HLT',
    )
    row.operator(
        "mixar.addon_project_open_entrypoint",
        text="Open" if compact else "Open Source",
        icon='TEXT',
    )

    mutable = row.row(align=True)
    mutable.enabled = getattr(scene, "mixie_chat_state", "IDLE") not in _BUSY_STATES
    mutable.operator(
        "mixar.addon_project_run_checks",
        text="Test" if compact else "Test & Reload",
        icon='CHECKMARK',
    )
    mutable.menu(
        _MORE_MENU,
        text="More",
        icon='DOWNARROW_HLT',
    )
