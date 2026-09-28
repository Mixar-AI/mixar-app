# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-before-copy detail view and explicit owner controls."""
from ...core.sharing_previews import icon
from .sharing_ui import action, draw_link, draw_notice, message


def draw_details(layout, context, index, record):
    wm = context.window_manager
    layout.operator('mixar.community_back', text='Back to results', icon='BACK')
    addon = record.get('kind') == 'addon'
    split = layout.split(factor=.3)
    cover = split.column().box()
    if icon(index):
        cover.template_icon(icon_value=icon(index), scale=10)
    else:
        row = cover.row(); row.scale_y = 3
        row.label(text='Made with Mixar', icon='PLUGIN' if addon else 'IMAGE_DATA')
    cover.label(text='Add-on' if addon else 'Moodboard')
    cover.label(text='By ' + record.get('author', 'Mixar creator')[:34])
    cover.label(text='Updated ' + record.get('updated_at', '')[:10])
    col = split.column()
    message(col, record.get('title', ''), 62, 2)
    message(col, record.get('description') or 'No description added yet.', 72, 7)
    details = record.get('details', {})
    if addon:
        col.separator()
        col.label(text=f"Version {details.get('version', '')} · {details.get('category', 'Other')}")
        col.label(text='License: ' + details.get('license', ''))
        col.label(text=f"{details.get('file_count', 0)} files · {details.get('download_size', 0) / 1024:.1f} KB ZIP")
        message(col, 'Download the source ZIP, then install it from Preferences → Add-ons → Install from Disk.', 72, 2)
        message(col, 'Add-ons run Python when enabled. Choose creators you trust; community code is not reviewed by Mixar.', 72, 2)
    else:
        col.label(text=f"{record.get('item_count', 0)} items")
        message(col, 'Open an editable copy in a new scene tab. Your changes stay with your copy.', 72, 2)
    actions = layout.row(align=True); actions.scale_y = 1.3
    actions.enabled = not wm.moodboard_community_busy
    if addon:
        actions.operator('mixar.community_download', text='Download ZIP', icon='IMPORT').index = index
    else:
        action(actions, 'Open Copy', index, 'open', 'DUPLICATE')
    if record.get('share_path'):
        action(actions, 'Copy Link', index, 'copy', 'COPYDOWN')
        from ...core.sharing_flow import url
        actions.operator('wm.url_open', text='View in Browser', icon='URL').url = url(record)
    if 'id' in record:
        box = layout.box()
        box.label(text='Your publication · ' + {'private': 'Private', 'unlisted': 'Link only', 'public': 'Public in Explore'}[record['visibility']])
        row = box.row(align=True); row.enabled = not wm.moodboard_community_busy
        for value, label in [('private', 'Make Private'), ('unlisted', 'Share by Link'), ('public', 'Publish in Explore')]:
            if value != record['visibility']:
                action(row, label, index, value)
        action(row, 'Delete', index, 'delete', 'TRASH')
        message(box, 'Changing visibility replaces the link. Copies already downloaded remain with their recipients.', 100, 2)
    draw_link(layout, wm)
    draw_notice(layout, wm)
