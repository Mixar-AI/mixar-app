# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island header's scene-tab switcher (parallel scene tabs).

A chat island belongs to ONE scene tab. Its header names that tab and drops
down the other tabs, with the same status words the Scenes drawer shows, so
the user can jump between agents without leaving the chat. Rows call the
scene-tab operators (``mixie_chat.switch_scene_tab`` / ``new_scene_tab``);
the list is ``wm.mixar_scene_tabs`` (refreshed by ``scene_tabs_props``).
"""

import bpy
from bpy.types import Menu

_STATUS_ICON = {
    'IDLE': 'RADIOBUT_OFF',
    'WORKING': 'PLAY',
    'WAITING': 'QUESTION',
    'DONE': 'CHECKMARK',
}
_STATUS_WORD = {
    'WORKING': "working",
    'WAITING': "waiting for you",
    'DONE': "done",
}
_LABEL_MAX = 22


def tab_label(scene, window_manager=None) -> str:
    """The header button's text: the tab's name, a leading dot when another
    tab needs the user."""
    name = getattr(scene, "name", "") or ""
    if len(name) > _LABEL_MAX:
        name = name[:_LABEL_MAX - 1] + "…"
    attention = bool(getattr(window_manager, "mixar_scene_tabs_attention", False))
    return ("● " if attention else "") + name


class MIXIE_CHAT_MT_scene_tabs(Menu):
    bl_idname = "MIXIE_CHAT_MT_scene_tabs"
    bl_label = "Scenes"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        shown = getattr(context, "scene", None)
        tabs = list(getattr(wm, "mixar_scene_tabs", []) or [])
        for tab in tabs:
            status = str(tab.status)
            word = _STATUS_WORD.get(status, "")
            text = f"{tab.scene_name} — {word}" if word else tab.scene_name
            if tab.attention:
                text = "● " + text
            row = layout.row()
            row.enabled = shown is None or tab.scene_name != shown.name
            op = row.operator("mixie_chat.switch_scene_tab", text=text,
                              icon=_STATUS_ICON.get(status, 'RADIOBUT_OFF'))
            op.scene_name = tab.scene_name
        if tabs:
            layout.separator()
        layout.operator("mixie_chat.new_scene_tab", text="New scene", icon='ADD')
        others = [t for t in tabs if shown is None or t.scene_name != shown.name]
        if others and getattr(context, "selected_objects", None):
            layout.menu("MIXIE_CHAT_MT_send_to_scene_tab", text="Send selection to", icon='DUPLICATE')


class MIXIE_CHAT_MT_send_to_scene_tab(Menu):
    """The other tabs, as targets for a copy of the selection."""

    bl_idname = "MIXIE_CHAT_MT_send_to_scene_tab"
    bl_label = "Send selection to"

    def draw(self, context):
        layout = self.layout
        shown = getattr(context, "scene", None)
        for tab in list(getattr(context.window_manager, "mixar_scene_tabs", []) or []):
            if shown is not None and tab.scene_name == shown.name:
                continue
            op = layout.operator("mixie_chat.send_to_scene_tab", text=tab.scene_name, icon='SCENE_DATA')
            op.scene_name = tab.scene_name


classes = (MIXIE_CHAT_MT_scene_tabs, MIXIE_CHAT_MT_send_to_scene_tab)
