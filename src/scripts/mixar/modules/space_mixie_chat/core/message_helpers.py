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

    # Start unified loader animation + drive frames for the slide-in
    start_loader_animation()
    from .animation_manager import start_slide_redraw_burst
    start_slide_redraw_burst()

    # Trigger redraw
    redraw_chat_areas()

    return bubble_id


def add_turn_placeholder(scene) -> None:
    """Optimistic "Thinking..." bubble for a turn that is about to stream.

    Shared by the composer send and socket-started (wake-up) turns. Clears a
    STALE loader first: a cancelled or client-closed previous turn can leave a
    "Thinking" loader — and its ghost placeholder — spinning forever because
    the backend cannot write a loader-off to a closed stream. Starting a new
    turn is the reliable point to clear it. The placeholder is replaced by the
    first real bubble the slot processor creates.
    """
    import uuid

    from ..constants import TEMP_PLACEHOLDER_PREFIX

    messages = scene.mixie_chat_messages
    stale = []
    for i, m in enumerate(messages):
        if getattr(m, 'loader_visible', False):
            m.loader_visible = False
        if getattr(m, 'bubble_id', '').startswith(TEMP_PLACEHOLDER_PREFIX):
            stale.append(i)
    for i in reversed(stale):
        messages.remove(i)

    placeholder = messages.add()
    placeholder.sender = 'AGENT'
    placeholder.bubble_id = f"{TEMP_PLACEHOLDER_PREFIX}{uuid.uuid4().hex[:12]}"
    placeholder.loader_visible = True
    placeholder.loader_texts = json.dumps(["Thinking..."])
    start_loader_animation()


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
            from .animation_manager import start_slide_redraw_burst
            start_slide_redraw_burst()
        else:
            logger.warning("Cannot add message - scene or property missing")
    except Exception as e:
        logger.error(f"Error adding agent message: {e}")
