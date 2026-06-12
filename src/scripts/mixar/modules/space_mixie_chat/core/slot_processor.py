# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Slot-based event processor for chat bubble rendering.

The slot-based architecture simplifies frontend logic by having the backend
send declarative UI updates. Each slot (loader, content, ephemeral, todo,
actions, images) is applied independently.
"""

from mixar.config.logging_config import get_logger
import json
from typing import Any, Optional

from ..constants import SessionState, TEMP_PLACEHOLDER_PREFIX
from .session import get_session_manager

logger = get_logger(__name__)


class SlotEventProcessor:
    """
    Processes slot-based SSE events for chat bubble rendering.

    Slot events contain a bubble_id and one or more slot updates:
    - loader: Animated loading indicator with rotating messages
    - content: Persistent message content (append/set/clear)
    - ephemeral: Temporary content with FIFO display (last 4 lines)
    - todo: List of todo items with status
    - actions: Action buttons for user interaction
    - images: Image gallery items

    The frontend simply renders whatever slots are present - no business logic
    about what to show based on event type.
    """

    def __init__(self) -> None:
        self._session = get_session_manager()

    def is_slot_event(self, event_data: dict) -> bool:
        """Check if event data is a slot-based event (has bubble_id)."""
        return "bubble_id" in event_data

    def apply_event(self, event_data: dict, scene) -> None:
        """
        Apply slot updates from an event to the corresponding bubble.

        Args:
            event_data: Event dict with bubble_id and slot updates
            scene: The Blender scene to operate on
        """
        # First slot event - reset drop count
        if self._session.get_state(scene) == SessionState.BUSY:
            from .queue_processor import reset_sse_drop_count
            reset_sse_drop_count()

        bubble_id = event_data.get("bubble_id")
        if not bubble_id:
            logger.warning("[SLOT] Event missing bubble_id, skipping")
            return

        bubble = self._get_or_create_bubble(bubble_id, scene)
        if not bubble:
            logger.error(f"[SLOT] Failed to get/create bubble: {bubble_id}")
            return

        # Apply each slot if present in the event.
        # Each slot is wrapped in try/except so one failure never blocks others.
        slot_handlers = [
            ("input_type", lambda: self._apply_input_type_slot(bubble, event_data["input_type"], scene)),
            ("loader", lambda: self._apply_loader_slot(bubble, event_data["loader"], scene)),
            ("content", lambda: self._apply_content_slot(bubble, event_data["content"])),
            ("ephemeral", lambda: self._apply_ephemeral_slot(bubble, event_data["ephemeral"])),
            ("todo", lambda: self._apply_todo_slot(bubble, event_data["todo"])),
            ("steps", lambda: self._apply_steps_slot(bubble, event_data["steps"])),
            ("actions", lambda: self._apply_actions_slot(bubble, event_data["actions"])),
            ("images", lambda: self._apply_images_slot(bubble, event_data["images"])),
        ]
        for slot_name, handler in slot_handlers:
            if slot_name in event_data:
                try:
                    handler()
                except Exception as e:
                    logger.error(f"[SLOT] Failed to apply {slot_name}: {e}")

    def _get_or_create_bubble(self, bubble_id: str, scene) -> Optional[Any]:
        """
        Get existing bubble by ID or create a new one.

        Args:
            bubble_id: Unique bubble identifier
            scene: The Blender scene to operate on

        Returns:
            MixieChatMessage PropertyGroup instance or None
        """
        if not scene or not hasattr(scene, 'mixie_chat_messages'):
            logger.error("[SLOT] Cannot access scene.mixie_chat_messages")
            return None

        # Search for existing bubble with this ID
        for idx, msg in enumerate(scene.mixie_chat_messages):
            if msg.bubble_id == bubble_id:
                return msg

        # Remove placeholder loader if it exists (optimistic UI cleanup)
        for idx in range(len(scene.mixie_chat_messages) - 1, -1, -1):
            if scene.mixie_chat_messages[idx].bubble_id.startswith(TEMP_PLACEHOLDER_PREFIX):
                scene.mixie_chat_messages.remove(idx)
                logger.debug("[SLOT] Removed placeholder loader")
                break

        # Create new bubble
        msg = scene.mixie_chat_messages.add()
        msg.bubble_id = bubble_id
        msg.sender = 'AGENT'  # Slot events are always from agent
        msg.message_type = 'AGENT'  # Slots determine rendering, type matches sender
        return msg

    def _apply_loader_slot(self, bubble: Any, loader_data: dict, scene=None) -> None:
        """
        Apply loader slot update.

        Args:
            bubble: Message PropertyGroup
            loader_data: Dict with visible, texts, rotate_ms
            scene: The Blender scene to operate on (optional)
        """
        was_visible = bubble.loader_visible
        # Handle None for boolean - default to False
        bubble.loader_visible = bool(loader_data.get("visible", False))

        texts_count = 0
        if "texts" in loader_data:
            texts = loader_data["texts"]
            # Handle None - default to empty list
            if texts is None:
                texts = []
            texts_count = len(texts) if isinstance(texts, list) else 0
            bubble.loader_texts = json.dumps(texts)
            bubble.loader_current_index = 0  # Reset on new texts

        if "rotate_ms" in loader_data:
            rotate_ms = loader_data["rotate_ms"]
            # Handle None - default to 2000
            bubble.loader_rotate_ms = int(rotate_ms) if rotate_ms is not None else 2000

        # Start/stop loader timer based on visibility change
        if bubble.loader_visible and not was_visible:
            self._start_loader_timer()
        elif not bubble.loader_visible and was_visible:
            if scene is not None:
                self._stop_loader_timer_if_no_active(scene)

    def _apply_content_slot(self, bubble: Any, content_data: dict) -> None:
        """
        Apply content slot update (persistent text).

        Args:
            bubble: Message PropertyGroup
            content_data: Dict with append/set/clear operations
        """
        prev_len = len(bubble.content)
        operation = "unknown"

        if content_data.get("clear"):
            bubble.content = ""
            operation = "clear"
        elif "set" in content_data:
            # Handle None values - Blender properties don't accept None
            set_text = content_data["set"] or ""
            bubble.content = set_text
            operation = f"set({len(set_text)} chars)"
        elif "append" in content_data:
            # Handle None values
            append_text = content_data["append"] or ""
            bubble.content += append_text
            operation = f"append({len(append_text)} chars)"

        # Also update legacy text field for backward compatibility
        bubble.text = bubble.content

        # Parse markdown segments for C++ rendering (incremental for streaming)
        try:
            if bubble.content:
                is_append = "append" in content_data
                bubble_id = bubble.bubble_id if hasattr(bubble, 'bubble_id') else ""

                if is_append and bubble_id:
                    from .markdown_parser import parse_markdown_incremental
                    segments = parse_markdown_incremental(
                        bubble.content, bubble_id, is_append=True
                    )
                else:
                    from .markdown_parser import parse_markdown_to_segments
                    segments = parse_markdown_to_segments(
                        bubble.content, streaming=False
                    )
                    if bubble_id:
                        from .markdown_parser import clear_incremental_cache
                        clear_incremental_cache(bubble_id)

                # Inline metadata update
                try:
                    metadata = json.loads(bubble.metadata) if bubble.metadata else {}
                except json.JSONDecodeError:
                    metadata = {}
                metadata["markdown_segments"] = segments
                bubble.metadata = json.dumps(metadata, ensure_ascii=False)
            else:
                # Clear only markdown segments, preserve other metadata
                try:
                    metadata = json.loads(bubble.metadata) if bubble.metadata else {}
                except json.JSONDecodeError:
                    metadata = {}
                metadata.pop("markdown_segments", None)
                bubble.metadata = json.dumps(metadata, ensure_ascii=False)
                # Clear incremental cache for this bubble
                bubble_id = bubble.bubble_id if hasattr(bubble, 'bubble_id') else ""
                if bubble_id:
                    from .markdown_parser import clear_incremental_cache
                    clear_incremental_cache(bubble_id)
        except Exception as e:
            logger.error(f"[SLOT:CONTENT] Markdown parsing failed: {e}")

    def _apply_ephemeral_slot(self, bubble: Any, ephemeral_data: dict) -> None:
        """
        Apply ephemeral slot update (temporary text with FIFO).

        Ephemeral content is displayed with FIFO (last 4 lines visible)
        and is cleared when the response completes.

        Args:
            bubble: Message PropertyGroup
            ephemeral_data: Dict with append/set/clear operations
        """
        prev_len = len(bubble.ephemeral)
        operation = "unknown"

        if ephemeral_data.get("clear"):
            bubble.ephemeral = ""
            operation = "clear"
        elif "set" in ephemeral_data:
            # Handle None values - Blender properties don't accept None
            set_text = ephemeral_data["set"] or ""
            bubble.ephemeral = set_text
            operation = f"set({len(set_text)} chars)"
        elif "append" in ephemeral_data:
            # Handle None values
            append_text = ephemeral_data["append"] or ""
            bubble.ephemeral += append_text
            operation = f"append({len(append_text)} chars)"


    def _apply_input_type_slot(self, bubble: Any, input_type: str, scene) -> None:
        """
        Apply input_type slot update and set appropriate session state.

        Args:
            bubble: Message PropertyGroup
            input_type: Type of input expected ('text', 'choice', 'approval')
            scene: The Blender scene to operate on
        """
        # Handle None - default to empty string
        input_type = input_type or ""
        bubble.input_type = input_type

        if input_type == 'text':
            # Agent wants free-form text input
            self._session.set_state(scene, SessionState.AWAITING_INPUT)
            logger.info(f"[SLOT:INPUT_TYPE] Set state to AWAITING_INPUT (agent requesting text input)")
        elif input_type in ('choice', 'approval'):
            # Agent wants button click only (disable text input)
            self._session.set_state(scene, SessionState.BUSY)
            logger.info(f"[SLOT:INPUT_TYPE] Set state to BUSY (showing {input_type} buttons, text input disabled)")
        else:
            logger.warning(f"[SLOT:INPUT_TYPE] Unknown input_type: {input_type}")

    def _apply_todo_slot(self, bubble: Any, todo_items: list) -> None:
        """
        Apply todo slot update (full replacement of todo items).

        Args:
            bubble: Message PropertyGroup
            todo_items: List of dicts with id, text, status
        """
        prev_count = len(bubble.todo_items)

        # Clear existing items
        bubble.todo_items.clear()

        # Track status counts for logging
        status_counts = {'PENDING': 0, 'IN_PROGRESS': 0, 'DONE': 0, 'FAILED': 0}

        # Add new items
        for idx, item_data in enumerate(todo_items):
            item = bubble.todo_items.add()
            # Handle None values - Blender properties don't accept None for strings
            item.item_id = item_data.get("id") or ""
            item.text = item_data.get("text") or ""

            # Map status string to enum
            status_str = item_data.get("status") or "pending"
            status = status_str.upper()
            if status in ('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED'):
                item.status = status
            else:
                item.status = 'PENDING'
                status = 'PENDING'

            status_counts[status] += 1

        # Start animation timer if any items are in_progress
        if status_counts['IN_PROGRESS'] > 0:
            self._start_loader_timer()

    def _apply_steps_slot(self, bubble: Any, steps_data: dict) -> None:
        """
        Apply steps slot update (full replacement of the steps block).

        NOTE: real-data path. Written but NOT exercised by the dev-data mock this
        phase (the mock writes step items directly). All branching logic lives in
        the unit-tested steps_format.apply_steps_to_bubble; this is a thin wrapper.

        Args:
            bubble: Message PropertyGroup
            steps_data: dict with optional "summary" and "items"
        """
        from .steps_format import apply_steps_to_bubble
        apply_steps_to_bubble(bubble, steps_data)

    def _apply_actions_slot(self, bubble: Any, actions: list) -> None:
        """
        Apply actions slot update (full replacement of action buttons).

        Args:
            bubble: Message PropertyGroup
            actions: List of dicts with label, value, style
        """
        prev_count = len(bubble.action_items)

        # Clear existing items
        bubble.action_items.clear()

        # Add new items
        action_labels = []
        for action_data in actions:
            action = bubble.action_items.add()
            # Handle None values - Blender properties don't accept None for strings
            action.label = action_data.get("label") or ""
            action.value = action_data.get("value") or ""

            # Map style string to enum
            style_str = action_data.get("style") or "default"
            style = style_str.upper()
            if style in ('PRIMARY', 'DEFAULT', 'DANGER'):
                action.style = style
            else:
                action.style = 'DEFAULT'

            action_labels.append(f"{action.label}({action.style})")

    def _apply_images_slot(self, bubble: Any, images: list) -> None:
        """
        Apply images slot update (full replacement of image gallery).

        Args:
            bubble: Message PropertyGroup
            images: List of dicts with url, alt, caption, thumbnail_url, width, height
        """
        # Clear existing items
        bubble.image_items.clear()

        # Add new items
        for img_data in images:
            img = bubble.image_items.add()
            # Handle None values - Blender properties don't accept None for strings
            img.url = img_data.get("url") or ""
            img.alt = img_data.get("alt") or ""
            img.caption = img_data.get("caption") or ""
            img.thumbnail_url = img_data.get("thumbnail_url") or ""
            img.local_path = img_data.get("local_path") or ""
            width = img_data.get("width")
            height = img_data.get("height")
            img.width = float(width) if isinstance(width, (int, float)) else 0.0
            img.height = float(height) if isinstance(height, (int, float)) else 0.0


    def _start_loader_timer(self) -> None:
        """Start the unified loader text rotation timer."""
        from .animation_manager import start_loader_animation
        start_loader_animation()

    def _stop_loader_timer_if_no_active(self, scene) -> None:
        """Stop loader timer if no bubbles have visible loaders."""
        if not scene or not hasattr(scene, 'mixie_chat_messages'):
            return

        # Check if any bubble still has loader visible
        for msg in scene.mixie_chat_messages:
            if msg.loader_visible:
                return

        # No active loaders, stop timer
        from .animation_manager import stop_loader_animation
        stop_loader_animation()


# Global slot processor instance
_slot_processor: Optional[SlotEventProcessor] = None


def get_slot_processor() -> SlotEventProcessor:
    """Get the global SlotEventProcessor instance."""
    global _slot_processor
    if _slot_processor is None:
        _slot_processor = SlotEventProcessor()
    return _slot_processor
