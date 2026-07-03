# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Message helper functions for Mixie Chat.

Provides utility functions for message CRUD operations on scene data,
shared helpers for slot loaders and authentication.
"""

import json
from mixar.config.logging_config import get_logger

import bpy

from .animation_manager import start_loader_animation
from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)


# ============================================================================
# Metadata Parsing Helper
# ============================================================================

def safe_parse_metadata(msg) -> dict:
    """Safely parse JSON metadata from a message property group.

    Args:
        msg: Message property group with a .metadata string attribute

    Returns:
        Parsed dict, or empty dict on missing/malformed metadata
    """
    if not msg.metadata:
        return {}
    try:
        result = json.loads(msg.metadata)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ============================================================================
# Metadata Write Helpers
# ============================================================================

def set_markdown_segments(msg, segments: list) -> None:
    """Store parsed markdown segments in message metadata for C++ rendering.

    Args:
        msg: Message property group object
        segments: List of segment dicts from markdown_parser
    """
    metadata = safe_parse_metadata(msg)
    metadata["markdown_segments"] = segments
    msg.metadata = json.dumps(metadata, ensure_ascii=False)


# ============================================================================
# Message CRUD
# ============================================================================

def add_slot_loader(scene, text):
    """Add a slot-based loader message.

    Creates a bubble with loader_visible=True and a unique bubble_id,
    using the unified slot-based loader animation system.

    Args:
        scene: Blender scene
        text: Loading message text (e.g., "Generating image...")

    Returns:
        The bubble_id string so callers can find and update the bubble on completion.
    """
    import uuid
    bubble_id = str(uuid.uuid4())

    msg = scene.mixie_chat_messages.add()
    msg.sender = 'AGENT'
    msg.bubble_id = bubble_id
    msg.loader_visible = True
    msg.loader_texts = json.dumps([text])

    # Start unified loader animation
    start_loader_animation()

    # Trigger redraw
    redraw_chat_areas()

    return bubble_id


def get_auth_token() -> str:
    """Get authentication token."""
    try:
        from mixar.modules.auth.core.auth import get_access_token
        return get_access_token() or ""
    except Exception:
        return ""


def add_agent_message(scene, text: str) -> None:
    """Add an agent message to the chat history.

    Args:
        scene: Blender scene (can be None)
        text: Message text (truncated to 4096 chars)
    """
    logger.debug(f"Adding agent message: {len(text)} chars")
    try:
        if scene and hasattr(scene, 'mixie_chat_messages'):
            agent_msg = scene.mixie_chat_messages.add()
            agent_msg.sender = 'AGENT'
            agent_msg.text = text[:4096]
        else:
            logger.warning("Cannot add message - scene or property missing")
    except Exception as e:
        logger.error(f"Error adding agent message: {e}")
