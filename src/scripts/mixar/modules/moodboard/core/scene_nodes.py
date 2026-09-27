# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scene nodes are image-output cards with a live local Scene reference."""
import uuid

import bpy

from .canvas_context import redraw_moodboard_canvases
from .node_graph import new_node_id
from mixar.modules.common.utils.image_utils import add_image_to_moodboard


def preview(source):
    from mixar.modules.space_mixie_chat.core.scene_tab_snapshot import zen_view3d_override
    override = zen_view3d_override()
    name = '.mixar-scene-preview-' + uuid.uuid4().hex
    if override:
        with bpy.context.temp_override(**override):
            try:
                bpy.ops.view3d.scenes_drawer_snapshot(scene_name=source.name, image_name=name)
            except (RuntimeError, TypeError):
                pass
    image = bpy.data.images.get(name)
    missing = image is None
    if image is None:
        image = bpy.data.images.new(name, width=320, height=180)
        image.generated_color = (.09, .13, .08, 1)
    image['_mixar_scene_preview_missing'] = missing
    image.name = ('Preview pending · ' if missing else 'Scene · ') + source.name
    image.pack()
    return image


def add_scene_node(board, source):
    from mixar.modules.space_mixie_chat.constants import is_lane_scene
    if source is None or is_lane_scene(source):
        raise ValueError("Choose a scene from this project")
    item = add_image_to_moodboard(preview(source), scene=board)
    item.node_id = new_node_id()
    item.scene_node, item.source_scene, item.scene_title = True, source, source.name
    for other in board.mixie_moodboard_images:
        other.selected = other.node_id == item.node_id
    redraw_moodboard_canvases()
    return item


def open_scene(item):
    from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import switch_scene_tab
    if not item.source_scene:
        raise ValueError("This is a scene preview; its source is not in this project")
    switch_scene_tab(item.source_scene, was=bpy.context.scene)
    return item.source_scene


def refresh(item):
    if not item.source_scene:
        raise ValueError("Open this scene first, then refresh its preview")
    image = preview(item.source_scene)
    old = item.image
    item.image = image
    item.scene_title = item.source_scene.name
    if old and old.users == 0:
        bpy.data.images.remove(old)
    redraw_moodboard_canvases()
