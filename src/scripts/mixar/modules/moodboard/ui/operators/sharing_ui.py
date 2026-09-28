# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Theme-aware community cards and publishing, using native accessible controls."""
import textwrap

from ...core import sharing_flow as flow
from ...core.sharing_previews import icon

VISIBILITY_HELP = {
    'private': 'Only you can access this saved publication.',
    'unlisted': 'Anyone with the link can view and download a copy. Hidden from Explore.',
    'public': 'Everyone can discover this in Explore and download their own copy.',
}


def message(layout, text, width=75, lines=None):
    wrapped = textwrap.wrap(text, width=width) or ['']
    if lines and len(wrapped) > lines:
        wrapped = wrapped[:lines]
        wrapped[-1] = wrapped[-1].rstrip(' .') + '…'
    for line in wrapped:
        layout.label(text=line)


def action(layout, label, index, kind, icon_name='NONE'):
    button = layout.operator('mixie.moodboard_community_action', text=label, icon=icon_name)
    button.index, button.action = index, kind


def draw_notice(layout, wm):
    if wm.moodboard_community_notice:
        box = layout.box()
        if wm.moodboard_community_busy:
            box.label(text=wm.moodboard_community_notice, icon='SORTTIME')
        else:
            message(box, wm.moodboard_community_notice, 100, 3)


def draw_link(layout, wm):
    if wm.moodboard_community_link:
        box = layout.box()
        box.label(text='Ready to share', icon='CHECKMARK')
        row = box.row(align=True)
        row.prop(wm, 'moodboard_community_link', text='')
        action(row, 'Copy', -1, 'copy', 'COPYDOWN')


def visibility(layout, data, prop):
    layout.label(text='Who can see this?')
    layout.prop(data, prop, text='')
    message(layout, VISIBILITY_HELP[getattr(data, prop)], 74, 2)


def draw_share(layout, context):
    surface = layout.mixar_surface(theme='ZEN', density='DEFAULT')
    surface.operator_context = 'INVOKE_DEFAULT'
    wm, scene = context.window_manager, context.scene
    surface.label(text='Give your ideas a place to travel', icon='URL')
    surface.separator(factor=.5)
    split = surface.split(factor=.32)
    preview = split.column().box()
    if icon(0):
        preview.template_icon(icon_value=icon(0), scale=8)
    else:
        preview.label(text='Your moodboard', icon='IMAGE_DATA')
    preview.label(text='Snapshot preview')
    for label, field in [('Images', 'images'), ('Notes', 'textboxes'), ('Nodes', 'action_nodes'), ('Frames', 'frames')]:
        count = len(getattr(scene, 'mixie_moodboard_' + field))
        preview.label(text=f'{count} {label.lower() if count != 1 else label.lower()[:-1]}')
    col = split.column()
    col.enabled = not wm.moodboard_community_busy and wm.mixie_chat_is_logged_in
    col.prop(scene, 'moodboard_share_title')
    col.prop(scene, 'moodboard_share_description')
    col.separator(factor=.6)
    visibility(col, scene, 'moodboard_share_visibility')
    col.separator(factor=.5)
    message(col, 'People open an editable copy. Your original stays yours.', 53, 2)
    message(col, 'Includes images, notes and node recipes. Scene nodes share their previews; 3D scenes and live jobs stay here.', 53, 3)
    surface.separator(factor=.6)
    row = surface.row()
    row.enabled = col.enabled
    row.scale_y = 1.3
    label = ('Update Snapshot' if scene.moodboard_share_revision else
             {'private': 'Save Private Snapshot', 'unlisted': 'Create Share Link', 'public': 'Publish to Explore'}[scene.moodboard_share_visibility])
    row.operator('mixie.moodboard_publish', text=label, icon='EXPORT')
    if scene.moodboard_share_revision:
        row.operator('mixie.moodboard_new_share', text='Save as New', icon='DUPLICATE')
    if not wm.mixie_chat_is_logged_in:
        surface.operator('mixie_chat.login', text='Sign in to publish', icon='USER')
    draw_link(surface, wm)
    draw_notice(surface, wm)


def draw_card(grid, index, record):
    card = grid.column().box()
    addon = record.get('kind') == 'addon'
    details = record.get('details', {})
    preview = icon(index)
    if preview:
        row = card.row(); row.alignment = 'CENTER'
        row.template_icon(icon_value=preview, scale=4)
    else:
        row = card.row(); row.scale_y = 2
        row.label(text=details.get('category', 'Moodboard'), icon='PLUGIN' if addon else 'IMAGE_DATA')
    card.label(text=textwrap.shorten(record.get('title', ''), width=34, placeholder='…'))
    card.label(text='By ' + textwrap.shorten(record.get('author', 'Mixar creator'), width=27, placeholder='…'))
    message(card, record.get('description') or ('A tool made in Mixar' if addon else 'A visual starting point'), 35, 2)
    card.label(text=('v' + details.get('version', '') + ' · ' + details.get('category', 'Other')) if addon
               else f"{record.get('item_count', 0)} items · Updated {record.get('updated_at', '')[:10]}")
    if 'id' in record:
        card.label(text={'private': 'Private', 'unlisted': 'Link only', 'public': 'Public in Explore'}[record['visibility']], icon='LOCKED' if record['visibility'] == 'private' else 'URL')
    row = card.row(align=True)
    action(row, 'Details', index, 'details', 'INFO')
    if not addon:
        action(row, 'Open Copy', index, 'open', 'DUPLICATE')
    else:
        row.operator('mixar.community_download', text='Download ZIP', icon='IMPORT').index = index


def draw_explore(layout, context):
    surface = layout.mixar_surface(theme='ZEN', density='COMPACT')
    surface.operator_context = 'INVOKE_DEFAULT'
    wm = context.window_manager
    allowed = flow._account == flow.identity()
    selected = wm.moodboard_community_selected
    if allowed and 0 <= selected < len(flow.records):
        from .sharing_details import draw_details
        draw_details(surface, context, selected, flow.records[selected])
        return
    row = surface.row()
    row.label(text='Find a starting point for your next idea', icon='WORLD')
    publish = row.row(); publish.enabled = wm.mixie_chat_is_logged_in and not wm.moodboard_community_busy
    if wm.moodboard_community_kind == 'addon':
        publish.operator('mixar.addon_share', text='Publish Add-on', icon='ADD')
    else:
        publish.operator('mixie.moodboard_share', text='Share this Board', icon='ADD')
    row = surface.row(align=True)
    row.enabled = not wm.moodboard_community_busy
    for kind, label in [('moodboard', 'Moodboards'), ('addon', 'Add-ons')]:
        button = row.operator('mixie.moodboard_explore_load', text=label, depress=wm.moodboard_community_kind == kind)
        button.kind, button.mode = kind, 'current'
    row.separator()
    for mode, label in [('explore', 'Community'), ('mine', 'My Library')]:
        cell = row.row(); cell.enabled = mode != 'mine' or wm.mixie_chat_is_logged_in
        button = cell.operator('mixie.moodboard_explore_load', text=label, depress=wm.moodboard_community_mode == mode)
        button.mode = mode
    row = surface.row(align=True)
    row.enabled = not wm.moodboard_community_busy
    row.prop(wm, 'moodboard_community_query', text='', icon='VIEWZOOM')
    row.operator('mixie.moodboard_explore_load', text='Search').mode = 'current'
    row.prop(wm, 'moodboard_community_sort', text='')
    row = surface.row(align=True)
    row.prop(wm, 'moodboard_community_open_link', text='Have a link?')
    row.operator('mixie.moodboard_open_link', text='Open Link', icon='LINKED')
    surface.separator(factor=.4)
    records = flow.records if allowed else []
    if records:
        surface.label(text=f'{wm.moodboard_community_total} results · Select Details to learn more or manage a publication')
    for index, record in enumerate(records):
        if index % 3 == 0:
            grid = surface.row(align=False)
            grid.enabled = not wm.moodboard_community_busy
        draw_card(grid, index, record)
        if index == len(records) - 1:
            for _ in range(2 - index % 3):
                grid.column().label(text='')
    if not records and not wm.moodboard_community_busy:
        box = surface.box()
        box.label(text='No matches yet' if wm.moodboard_community_query else 'Your next idea could start here', icon='VIEWZOOM')
        message(box, 'Try another search, or publish your first creation from Mixar. Public work appears in Community; everything you publish is in My Library.', 96, 2)
    row = surface.row(align=True)
    previous = row.row(); previous.enabled = wm.moodboard_community_page > 0
    button = previous.operator('mixie.moodboard_explore_load', text='Previous', icon='TRIA_LEFT')
    button.page, button.mode = max(0, wm.moodboard_community_page - 1), 'current'
    row.label(text=f'Page {wm.moodboard_community_page + 1} of {max(1, (wm.moodboard_community_total + 5) // 6)}')
    following = row.row(); following.enabled = wm.moodboard_community_more
    button = following.operator('mixie.moodboard_explore_load', text='Next', icon='TRIA_RIGHT')
    button.page, button.mode = wm.moodboard_community_page + 1, 'current'
    draw_notice(surface, wm)
