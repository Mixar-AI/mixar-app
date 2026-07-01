# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Undo Guard for Mixie Chat Messages.

Prevents Blender's undo/redo from affecting chat messages.
Before any undo or redo, we snapshot the current messages.
After undo/redo completes, we restore them so chat history persists.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Temporary snapshot held between pre/post handler pairs.
_saved_messages = None


def _snapshot_single_scene(scene):
    """Deep-copy all chat message data from a single scene.

    Returns a list of plain dicts so the data is fully independent of
    the Blender datablock that undo is about to roll back.
    """
    if not scene or not hasattr(scene, 'mixie_chat_messages'):
        return []

    messages = []
    for msg in scene.mixie_chat_messages:
        msg_data = {
            'sender': msg.sender,
            'text': msg.text,
            'message_type': msg.message_type,
            'metadata': msg.metadata,
            'bubble_id': msg.bubble_id,
            'loader_visible': msg.loader_visible,
            'loader_texts': msg.loader_texts,
            'loader_rotate_ms': msg.loader_rotate_ms,
            'loader_current_index': msg.loader_current_index,
            'loader_spinner_index': msg.loader_spinner_index,
            'content': msg.content,
            'ephemeral': msg.ephemeral,
            'input_type': msg.input_type,
            'attachments': [
                {
                    'image_path': att.image_path,
                    'image_source': att.image_source,
                    'display_name': att.display_name,
                }
                for att in msg.attachments
            ],
            'todo_items': [
                {
                    'item_id': todo.item_id,
                    'text': todo.text,
                    'status': todo.status,
                }
                for todo in msg.todo_items
            ],
            'action_items': [
                {
                    'label': action.label,
                    'value': action.value,
                    'style': action.style,
                }
                for action in msg.action_items
            ],
            'image_items': [
                {
                    'url': img.url,
                    'alt': img.alt,
                    'caption': img.caption,
                    'thumbnail_url': img.thumbnail_url,
                    'local_path': img.local_path,
                    'width': img.width,
                    'height': img.height,
                }
                for img in msg.image_items
            ],
        }
        messages.append(msg_data)

    return messages


def _snapshot_all_scenes():
    """Snapshot chat messages from ALL scenes.

    Returns a dict of {scene_name: [messages]} so each scene's messages
    can be restored to the correct scene after undo/redo, even if the
    active scene changes during the operation.
    """
    snapshots = {}
    for scene in bpy.data.scenes:
        if hasattr(scene, 'mixie_chat_messages'):
            snapshots[scene.name] = _snapshot_single_scene(scene)
    return snapshots


def _restore_single_scene(scene, snapshot):
    """Write a snapshot back into a scene's chat message collection."""
    if not scene or not hasattr(scene, 'mixie_chat_messages'):
        return

    scene.mixie_chat_messages.clear()

    for msg_data in snapshot:
        msg = scene.mixie_chat_messages.add()
        msg.sender = msg_data['sender']
        msg.text = msg_data['text']
        msg.message_type = msg_data['message_type']
        msg.metadata = msg_data['metadata']
        msg.bubble_id = msg_data['bubble_id']
        msg.loader_visible = msg_data['loader_visible']
        msg.loader_texts = msg_data['loader_texts']
        msg.loader_rotate_ms = msg_data['loader_rotate_ms']
        msg.loader_current_index = msg_data['loader_current_index']
        msg.loader_spinner_index = msg_data['loader_spinner_index']
        msg.content = msg_data['content']
        msg.ephemeral = msg_data['ephemeral']
        msg.input_type = msg_data['input_type']

        for att_data in msg_data['attachments']:
            att = msg.attachments.add()
            att.image_path = att_data['image_path']
            att.image_source = att_data['image_source']
            att.display_name = att_data['display_name']

        for todo_data in msg_data['todo_items']:
            todo = msg.todo_items.add()
            todo.item_id = todo_data['item_id']
            todo.text = todo_data['text']
            todo.status = todo_data['status']

        for action_data in msg_data['action_items']:
            action = msg.action_items.add()
            action.label = action_data['label']
            action.value = action_data['value']
            action.style = action_data['style']

        for img_data in msg_data['image_items']:
            img = msg.image_items.add()
            img.url = img_data['url']
            img.alt = img_data['alt']
            img.caption = img_data['caption']
            img.thumbnail_url = img_data['thumbnail_url']
            img.local_path = img_data['local_path']
            img.width = img_data['width']
            img.height = img_data['height']


def _restore_all_scenes(snapshots):
    """Restore chat messages to ALL scenes from a snapshot dict."""
    for scene in bpy.data.scenes:
        if scene.name in snapshots:
            _restore_single_scene(scene, snapshots[scene.name])


# -- Handlers ----------------------------------------------------------------

@persistent
def _on_undo_pre(scene):
    """Snapshot messages from ALL scenes before undo."""
    global _saved_messages
    _saved_messages = _snapshot_all_scenes()


@persistent
def _on_undo_post(scene):
    """Restore messages to ALL scenes after undo."""
    global _saved_messages
    if _saved_messages is not None:
        _restore_all_scenes(_saved_messages)
        _saved_messages = None


@persistent
def _on_redo_pre(scene):
    """Snapshot messages from ALL scenes before redo."""
    global _saved_messages
    _saved_messages = _snapshot_all_scenes()


@persistent
def _on_redo_post(scene):
    """Restore messages to ALL scenes after redo."""
    global _saved_messages
    if _saved_messages is not None:
        _restore_all_scenes(_saved_messages)
        _saved_messages = None


# -- Registration ------------------------------------------------------------

_handlers = (
    (bpy.app.handlers.undo_pre, _on_undo_pre),
    (bpy.app.handlers.undo_post, _on_undo_post),
    (bpy.app.handlers.redo_pre, _on_redo_pre),
    (bpy.app.handlers.redo_post, _on_redo_post),
)


def register():
    """Install undo/redo handlers to protect chat messages."""
    for handler_list, fn in _handlers:
        if fn not in handler_list:
            handler_list.append(fn)
    logger.info("Chat undo guard registered")


def unregister():
    """Remove undo/redo handlers."""
    for handler_list, fn in _handlers:
        if fn in handler_list:
            handler_list.remove(fn)
    logger.info("Chat undo guard unregistered")
