# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native, theme-aware sharing dialogs; all controls are QA-targetable buttons."""
import textwrap

from ...core import sharing_flow as flow
from ...core.sharing_previews import icon


def message(layout, text, width=75):
    for line in textwrap.wrap(text, width=width):
        layout.label(text=line)


def action(layout, label, index, kind, icon_name='NONE'):
    button = layout.operator('mixie.moodboard_community_action', text=label, icon=icon_name)
    button.index, button.action = index, kind


def draw_notice(layout, wm):
    if wm.moodboard_community_notice:
        message(layout.box(), wm.moodboard_community_notice)


def draw_share(layout, context):
    surface = layout.mixar_surface(theme='ZEN', density='COMPACT')
    surface.operator_context = 'INVOKE_DEFAULT'
    wm, scene = context.window_manager, context.scene
    surface.label(text="Share your ideas", icon='URL')
    message(surface, "Save a snapshot of this board. People who can view it can open their own editable copy.", 68)
    col = surface.column()
    col.enabled = not wm.moodboard_community_busy and wm.mixie_chat_is_logged_in
    col.prop(scene, 'moodboard_share_title')
    col.prop(scene, 'moodboard_share_description')
    col.prop(scene, 'moodboard_share_visibility')
    message(col, "Includes images, notes, drawings, frames, node recipes and Scene previews. The 3D scenes and live jobs stay in your project.", 68)
    row = col.row()
    row.operator('mixie.moodboard_publish', text='Update Snapshot' if scene.moodboard_share_revision else 'Save Snapshot', icon='EXPORT')
    if scene.moodboard_share_id:
        row.operator('mixie.moodboard_new_share', text='Save as New', icon='DUPLICATE')
    if not wm.mixie_chat_is_logged_in:
        surface.label(text="Sign in to save or share a moodboard", icon='INFO')
    if wm.moodboard_community_link:
        row = surface.row()
        row.prop(wm, 'moodboard_community_link', text='')
        action(row, 'Copy', -1, 'copy', 'COPYDOWN')
    draw_notice(surface, wm)


def draw_explore(layout, context):
    surface = layout.mixar_surface(theme='ZEN', density='COMPACT')
    surface.operator_context = 'INVOKE_DEFAULT'
    wm = context.window_manager
    row = surface.row(align=True)
    for mode, label in [('explore', 'Explore'), ('mine', 'My Boards')]:
        cell = row.row()
        cell.enabled = mode != 'mine' or wm.mixie_chat_is_logged_in
        button = cell.operator('mixie.moodboard_explore_load', text=label, depress=wm.moodboard_community_mode == mode)
        button.mode = mode
    row = surface.row(align=True)
    row.prop(wm, 'moodboard_community_query', text='', icon='VIEWZOOM')
    row.operator('mixie.moodboard_explore_load', text='Search', icon='VIEWZOOM').mode = 'current'
    row = surface.row(align=True)
    row.prop(wm, 'moodboard_community_open_link', text='Paste a link')
    row.operator('mixie.moodboard_open_link', text='Open Link', icon='LINKED')
    surface.separator()
    allowed = flow._account == flow.identity()
    for index, record in enumerate(flow.records if allowed else []):
        if index % 3 == 0:
            grid = surface.row()
            grid.enabled = not wm.moodboard_community_busy
        card = grid.column().box()
        preview = icon(index)
        if preview:
            card.template_icon(icon_value=preview, scale=6)
        else:
            card.label(text='Moodboard', icon='IMAGE_DATA')
        title = record.get('title', '')
        card.label(text=title if len(title) < 32 else title[:29] + '…')
        card.label(text='By ' + record.get('author', 'Mixar creator')[:28])
        card.label(text=f"{record.get('item_count', 0)} items · {record.get('visibility', '')}")
        row = card.row(align=True)
        action(row, 'Open Copy', index, 'open', 'DUPLICATE')
        if record.get('share_path'):
            action(row, '', index, 'copy', 'COPYDOWN')
        if 'id' in record:
            row = card.row(align=True)
            if record['visibility'] == 'private':
                action(row, 'Share Link', index, 'unlisted')
                action(row, 'Publish', index, 'public')
            else:
                action(row, 'Make Private', index, 'private')
            action(row, '', index, 'delete', 'TRASH')
        if index == len(flow.records) - 1:
            for _ in range(2 - index % 3):
                grid.column().label(text='')
    row = surface.row(align=True)
    previous = row.row()
    previous.enabled = wm.moodboard_community_page > 0
    button = previous.operator('mixie.moodboard_explore_load', text='Previous', icon='TRIA_LEFT')
    button.page, button.mode = max(0, wm.moodboard_community_page - 1), 'current'
    row.label(text=f"Page {wm.moodboard_community_page + 1}")
    following = row.row()
    following.enabled = wm.moodboard_community_more
    button = following.operator('mixie.moodboard_explore_load', text='Next', icon='TRIA_RIGHT')
    button.page, button.mode = wm.moodboard_community_page + 1, 'current'
    draw_notice(surface, wm)
