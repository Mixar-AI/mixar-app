# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Menus that belong to the node graph rather than to the canvas.

Split from ``moodboard_menus.py``, which owns the right-click menu and sits at
the 500-line ceiling. Adding a node and arranging nodes are each a
self-contained group of actions, so they read better apart from the contextual
menu's branching.
"""

from bpy.types import Menu

from mixar.modules.moodboard.ui.moodboard_menus import (
    MIXIE_SPACE_AVAILABLE,
    _MESH_CONTINUATIONS,
    _capability_available,
    _connected_action,
)


def _cursor_anchor(scene):
    """Canvas point the Shift+A Add menu was opened at.

    ``mixie.moodboard_add_menu`` records the cursor into the scene's context
    x/y just before opening this menu, so every entry lands under the pointer
    like the 3D viewport's Add menu. Read-only — this runs from a menu draw.
    """
    return (
        float(getattr(scene, "mixie_moodboard_context_x", 0.0)),
        float(getattr(scene, "mixie_moodboard_context_y", 0.0)),
    )


class MIXIE_MT_moodboard_add(Menu):
    """Shift+A add-node menu, like the 3D viewport's Add menu.

    Type to search (SEARCH_ON_KEY_PRESS). Each item drops a standalone node at
    the cursor; nodes that take an input (3D, mesh features) are wired up
    afterwards by dragging a connection into them.
    """

    bl_label = "Add Node"
    bl_idname = "MIXIE_MT_moodboard_add"
    bl_options = {'SEARCH_ON_KEY_PRESS'}

    def draw(self, context):
        layout = self.layout
        drop = _cursor_anchor(context.scene)

        layout.label(text="Generate")
        _connected_action(
            layout, 'IMAGE_GEN', "Generate Image", 'IMAGE_DATA',
            drop=drop, allow_empty=True,
        )
        if _capability_available("model_gen"):
            _connected_action(
                layout, 'MODEL_3D', "Generate to 3D", 'MESH_DATA',
                drop=drop, allow_empty=True,
            )
        if _capability_available("video_gen"):
            _connected_action(
                layout, 'VIDEO_GEN', "Generate Video", 'FILE_MOVIE',
                drop=drop, allow_empty=True,
            )

        # Mesh-feature nodes take a 3D mesh input (wire a mesh node into them).
        mesh_items = [
            (action_type, text, icon)
            for action_type, text, icon, capability in _MESH_CONTINUATIONS
            if _capability_available(capability)
        ]
        if mesh_items:
            layout.separator()
            layout.label(text="3D Mesh")
            for action_type, text, icon in mesh_items:
                _connected_action(
                    layout, action_type, text, icon, drop=drop, allow_empty=True
                )


_ALIGN_ITEMS = (
    ('LEFT', "Align Left", 'ANCHOR_LEFT'),
    ('CENTER_X', "Align Centre", 'ANCHOR_CENTER'),
    ('RIGHT', "Align Right", 'ANCHOR_RIGHT'),
    ('TOP', "Align Top", 'ANCHOR_TOP'),
    ('CENTER_Y', "Align Middle", 'ANCHOR_CENTER'),
    ('BOTTOM', "Align Bottom", 'ANCHOR_BOTTOM'),
)


class MIXIE_MT_moodboard_arrange(Menu):
    """Align, distribute and tidy the canvas.

    Every entry acts on the selection when several items are selected, and on
    the whole board otherwise: images and text boxes included, not just the
    inference nodes.
    """

    bl_label = "Arrange"
    bl_idname = "MIXIE_MT_moodboard_arrange"

    def draw(self, context):
        layout = self.layout

        # Tidy first: it is the one most people want, and the only one that
        # needs no prior selection.
        layout.operator("mixie.moodboard_tidy_nodes", text="Tidy", icon='NODETREE')
        layout.separator()

        for edge, text, icon in _ALIGN_ITEMS:
            layout.operator(
                "mixie.moodboard_align_nodes", text=text, icon=icon
            ).edge = edge
        layout.separator()

        layout.operator(
            "mixie.moodboard_distribute_nodes",
            text="Distribute Horizontally",
            icon='ARROW_LEFTRIGHT',
        ).axis = 'X'
        layout.operator(
            "mixie.moodboard_distribute_nodes",
            text="Distribute Vertically",
            icon='EMPTY_SINGLE_ARROW',
        ).axis = 'Y'


classes = (
    MIXIE_MT_moodboard_add,
    MIXIE_MT_moodboard_arrange,
) if MIXIE_SPACE_AVAILABLE else ()
