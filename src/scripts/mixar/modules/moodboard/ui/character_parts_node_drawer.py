# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The node settings popup retains the component controls formerly in N-panel."""


def draw_character_parts_node(layout, scene, node):
    from ..core.character_parts_node import source_item
    from .character_components_drawer import draw_character_components

    try:
        item = source_item(scene, node)
    except ValueError as exc:
        layout.label(text=str(exc), icon='INFO')
        return
    index = next((i for i, candidate in enumerate(scene.mixie_moodboard_images)
                  if candidate.node_id == item.node_id), -1)
    if index < 0:
        layout.label(text="The connected image is no longer available", icon='INFO')
        return
    if not item.segments:
        layout.label(text="No component masks yet", icon='INFO')
        layout.label(text="Select the source image and use Mask Tools")
        return
    settings = scene.mixie_moodboard_sidebar.tab_segment_to_3d.character_components
    draw_character_components(layout, index, item, settings)
