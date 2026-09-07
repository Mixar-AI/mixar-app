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
from .ui_utils import bump_layout_epoch as _bump_layout_epoch

logger = get_logger(__name__)

# Mirrors the StringProperty maxlen on the message slot fields
# (chat_props.py). Hot-path writes below use ID-property subscript
# assignment (``bubble["content"] = ...``) which skips the RNA setter —
# and therefore its maxlen clamp — so we clamp here to keep behaviour
# identical to the previous attribute writes.
_SLOT_TEXT_MAXLEN = 65536


def _fast_set(bubble, prop_name: str, value) -> None:
    """Write a message slot property without firing RNA updates.

    Attribute assignment on Python-registered properties routes through
    ``rna_property_update`` which, for ID-properties, tags the owning
    Scene's depsgraph (TRANSFORM|GEOMETRY|PARAMETERS) and broadcasts
    ``NC_WINDOW`` + ``NC_ID`` notifiers — i.e. every streamed SSE chunk
    forced a full-app redraw and a scene re-evaluation. Subscript
    assignment writes the same underlying ID-property storage (the RNA
    reads used by the C++ renderer see it identically) but skips that
    global invalidation. The chat/bubble regions are redrawn explicitly
    via redraw_chat_areas() after each event batch, so nothing is lost.

    Only safe for properties without ``update=`` callbacks — true for
    all message slot fields.
    """
    bubble[prop_name] = value


def _extinguish_other_loaders(scene, keep_bubble_id: str) -> None:
    """Hide every visible loader except `keep_bubble_id`'s — one spinner, always."""
    for msg in getattr(scene, "mixie_chat_messages", []) or []:
        if (getattr(msg, "bubble_id", "") != keep_bubble_id
                and getattr(msg, "loader_visible", False)):
            msg.loader_visible = False


def collapse_live_thinking(bubble, scene=None) -> None:
    """Finalize the bubble's current live reasoning phase into the quiet
    '▸ Thought for Ns' dropdown — called when the next tool step starts (so
    reasoning collapses progressively) and on turn end. The pure lifecycle
    snapshots the live ephemeral FIFO into thinking_text and accumulates the
    duration; a later narration burst re-opens the panel live."""
    import time

    from .thinking_lifecycle import apply_ephemeral_to_bubble

    changed = False
    if getattr(bubble, "thinking_active", False):
        apply_ephemeral_to_bubble(bubble, {"clear": True}, time.time())
        changed = True
    if ((getattr(bubble, "thinking_text", "") or "").strip()
            and not getattr(bubble, "thinking_collapsed", False)):
        bubble.thinking_collapsed = True  # show as "▸ Thought for Ns"
        changed = True
    if changed and scene is not None:
        _bump_layout_epoch(scene)


def finalize_turn(scene) -> None:
    """End-of-turn cleanup, called on stream completion AND user abort.

    - Collapses each bubble's live thinking into the "Thought for Ns" dropdown.
    - Marks any still-RUNNING tool steps DONE so their animation settles.
    - Hides lingering loaders.
    A retry then starts from a clean, settled transcript instead of interleaving
    with a half-finished turn.
    """
    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages:
        return
    for msg in messages:
        collapse_live_thinking(msg)
        try:
            for row in msg.step_items:
                if row.status == "RUNNING":
                    row.status = "DONE"
        except Exception:  # noqa: BLE001
            pass
        if getattr(msg, "loader_visible", False):
            msg.loader_visible = False

    _bump_layout_epoch(scene)


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
            ("questions", lambda: self._apply_questions_slot(bubble, event_data["questions"])),
            ("interrupt_id", lambda: self._apply_interrupt_id_slot(bubble, event_data["interrupt_id"])),
            ("input_type", lambda: self._apply_input_type_slot(bubble, event_data["input_type"], scene)),
            ("interrupt_context", lambda: self._apply_interrupt_context_slot(bubble, event_data["interrupt_context"])),
            ("loader", lambda: self._apply_loader_slot(bubble, event_data["loader"], scene)),
            ("content", lambda: self._apply_content_slot(bubble, event_data["content"], scene)),
            ("ephemeral", lambda: self._apply_ephemeral_slot(bubble, event_data["ephemeral"], scene)),
            ("todo", lambda: self._apply_todo_slot(bubble, event_data["todo"])),
            ("steps", lambda: self._apply_steps_slot(bubble, event_data["steps"], scene)),
            ("actions", lambda: self._apply_actions_slot(bubble, event_data["actions"], scene)),
            ("images", lambda: self._apply_images_slot(bubble, event_data["images"])),
        ]
        for slot_name, handler in slot_handlers:
            if slot_name in event_data:
                try:
                    handler()
                except Exception as e:
                    logger.error(f"[SLOT] Failed to apply {slot_name}: {e}")

        # A re-delivered batch event's content/actions slots (applied above)
        # draw the backend's FIRST pending question, but the answers kept by
        # store_batch may put the wizard further along. Re-render the card the
        # stored state actually calls for — after every slot has been applied,
        # so the wire's own content/actions cannot overwrite it back.
        if "questions" in event_data:
            try:
                from .batched_choice import reconcile_rendered_card
                reconcile_rendered_card(bubble, scene)
            except Exception as e:
                logger.error(f"[SLOT] Failed to reconcile batched card: {e}")

    @staticmethod
    def _apply_questions_slot(bubble: Any, questions: list) -> None:
        """Store a batched-choice wizard payload, keeping answers already given.

        Re-delivery of the same interrupt (reconnect replay, or a still-pending
        interrupt re-emitted when a later stream leg ends) must not reset the
        user's progress — see batched_choice.store_batch.
        """
        from .batched_choice import store_batch

        store_batch(bubble, questions)

    @staticmethod
    def _apply_interrupt_id_slot(bubble: Any, interrupt_id: str) -> None:
        bubble.interrupt_id = interrupt_id or ""

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

        # Agent bubbles arrive with no input events flowing — drive redraws
        # briefly so the C++ slide-in animation gets frames.
        from .animation_manager import start_slide_redraw_burst
        start_slide_redraw_burst()
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

        if "texts" in loader_data:
            texts = loader_data["texts"]
            if texts is None:
                texts = []
            _fast_set(bubble, "loader_texts",
                      json.dumps(texts if isinstance(texts, list) else [])[:2048])
            _fast_set(bubble, "loader_current_index", 0)  # Reset on new texts

        if "rotate_ms" in loader_data:
            rotate_ms = loader_data["rotate_ms"]
            # Handle None - default to 2000. Clamp to the property's min
            # (the subscript write below bypasses RNA's min=100 clamp).
            value = int(rotate_ms) if rotate_ms is not None else 2000
            _fast_set(bubble, "loader_rotate_ms", max(100, value))

        # ONE spinner, always: whichever bubble's loader just turned visible is
        # the live indicator — extinguish every other bubble's. The backend
        # already moves its single loader between bubbles; this is the
        # client-side invariant should events race or drop.
        if bubble.loader_visible and scene is not None:
            _extinguish_other_loaders(scene, getattr(bubble, "bubble_id", ""))

        # Start/stop loader timer based on visibility change
        if bubble.loader_visible and not was_visible:
            self._start_loader_timer()
        elif not bubble.loader_visible and was_visible:
            if scene is not None:
                self._stop_loader_timer_if_no_active(scene)

    def _apply_content_slot(self, bubble: Any, content_data: dict, scene=None) -> None:
        """Apply a content slot update (persistent text).

        Content is curated by the backend (plan-free notices, interrupt
        questions, the final answer); live narration arrives via the ephemeral
        slot and is handled by the thinking lifecycle.
        """
        if content_data.get("clear"):
            _fast_set(bubble, "content", "")
        elif "set" in content_data:
            _fast_set(bubble, "content",
                      (content_data["set"] or "")[:_SLOT_TEXT_MAXLEN])
        elif "append" in content_data:
            _fast_set(
                bubble, "content",
                (bubble.content + (content_data.get("append") or ""))[:_SLOT_TEXT_MAXLEN],
            )

        # Also update legacy text field for backward compatibility
        _fast_set(bubble, "text", bubble.content)

        self._reparse_content_markdown(bubble, is_append=("append" in content_data))
        if scene is not None:
            _bump_layout_epoch(scene)

    def _reparse_content_markdown(self, bubble: Any, is_append: bool) -> None:
        """(Re)build the markdown_segments metadata from bubble.content."""
        bubble_id = bubble.bubble_id if hasattr(bubble, 'bubble_id') else ""
        try:
            if bubble.content:
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

                try:
                    metadata = json.loads(bubble.metadata) if bubble.metadata else {}
                except json.JSONDecodeError:
                    metadata = {}
                metadata["markdown_segments"] = segments
                _fast_set(
                    bubble, "metadata",
                    json.dumps(metadata, ensure_ascii=False)[:_SLOT_TEXT_MAXLEN],
                )
            else:
                try:
                    metadata = json.loads(bubble.metadata) if bubble.metadata else {}
                except json.JSONDecodeError:
                    metadata = {}
                metadata.pop("markdown_segments", None)
                _fast_set(
                    bubble, "metadata",
                    json.dumps(metadata, ensure_ascii=False)[:_SLOT_TEXT_MAXLEN],
                )
                if bubble_id:
                    from .markdown_parser import clear_incremental_cache
                    clear_incremental_cache(bubble_id)
        except Exception as e:
            logger.error(f"[SLOT:CONTENT] Markdown parsing failed: {e}")

    def _apply_ephemeral_slot(self, bubble: Any, ephemeral_data: dict, scene) -> None:
        """
        Apply ephemeral slot update (temporary text with FIFO).

        Ephemeral content is displayed with FIFO (last 4 lines visible) and is
        cleared when the response completes. The set/append/clear ops also
        drive the thinking lifecycle: live reasoning marks the bubble
        thinking_active; the closing `clear` snapshots the text into the
        finalized "Thought for Ns" dropdown (thinking_text + duration).

        Args:
            bubble: Message PropertyGroup
            ephemeral_data: Dict with append/set/clear operations
            scene: The Blender scene (for the layout-epoch bump on finalize)
        """
        import time

        from .thinking_lifecycle import apply_ephemeral_to_bubble

        finalized = apply_ephemeral_to_bubble(bubble, ephemeral_data, time.time())
        if finalized:
            # The dropdown is a new block — force a C++ layout rebuild.
            _bump_layout_epoch(scene)


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

        # 'confirm' is the Yes/No/Cancel prompt (request_user_input's fourth
        # input_type). Its omission here is why the actions slot grew a
        # derive-the-state-from-the-buttons fallback: without it a confirm
        # decayed to Idle on SSE-complete with its buttons still on screen,
        # and typed text went to /agent/chat instead of answering the question.
        if input_type in ('text', 'choice', 'confirm', 'approval',
                          'file_save', 'file_open'):
            # Agent has paused for the user — free-form text, a choice
            # button, or an approval button. All three use AWAITING_INPUT:
            # the state survives SSE stream completion (see
            # _handle_sse_complete_internal), so the status pill reads
            # "Awaiting input" instead of decaying BUSY -> IDLE while the
            # question is still on screen. Text typed while a choice /
            # approval prompt is up is routed as an input response
            # (start_input_stream), which the backend treats as the
            # answer to the pending question.
            self._session.set_state(scene, SessionState.AWAITING_INPUT)
            logger.info(
                f"[SLOT:INPUT_TYPE] Set state to AWAITING_INPUT "
                f"(agent requesting {input_type} input)"
            )
        else:
            logger.warning(f"[SLOT:INPUT_TYPE] Unknown input_type: {input_type}")

    @staticmethod
    def _apply_interrupt_context_slot(bubble: Any, context: dict) -> None:
        """Store only the non-sensitive picker configuration on a transient bubble."""
        context = context if isinstance(context, dict) else {}
        bubble.export_format = str(context.get("format") or "")[:8]
        bubble.export_scope = str(context.get("scope") or "")[:16]
        bubble.export_extension = str(context.get("extension") or "")[:8]
        bubble.export_suggested_filename = str(
            context.get("suggested_filename") or "export"
        )[:96]
        # #1251 import picker: the offered extensions (comma-separated), so
        # the native open dialog can filter. Never a path.
        bubble.import_formats = str(context.get("formats") or "")[:120]

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
            # Handle None values - Blender properties don't accept None for
            # strings. Clamps mirror the maxlens in chat_slot_types.py
            # (item_id=64 matches the C++ TodoItemSlotData::id buffer).
            _fast_set(item, "item_id", (item_data.get("id") or "")[:64])
            _fast_set(item, "text", (item_data.get("text") or "")[:512])

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

    def _apply_steps_slot(self, bubble: Any, steps_data: dict, scene) -> None:
        """
        Apply steps slot update (full replacement of the steps block).

        All branching logic lives in the unit-tested
        steps_format.apply_steps_to_bubble; this is a thin wrapper.

        Args:
            bubble: Message PropertyGroup
            steps_data: dict with optional "summary" and "items"
            scene: The Blender scene (for the layout-epoch bump)
        """
        from .steps_format import apply_steps_to_bubble
        apply_steps_to_bubble(bubble, steps_data)
        # Row count / detail text changed the block height.
        _bump_layout_epoch(scene)

    def _apply_actions_slot(self, bubble: Any, actions: list, scene=None) -> None:
        """
        Apply actions slot update (full replacement of action buttons).

        Args:
            bubble: Message PropertyGroup
            actions: List of dicts with label, value, style, and (for
                asset-picker options) asset_name/library/blend_file/asset_type
            scene: The Blender scene (for asset-picker preview generation)
        """
        from . import asset_choice_previews

        prev_count = len(bubble.action_items)

        # An answered picker is replaced with an empty actions list — that is
        # the moment its locally generated preview images become garbage.
        if prev_count and any(item.image for item in bubble.action_items):
            asset_choice_previews.cleanup_bubble(bubble)

        # Clear existing items
        bubble.action_items.clear()

        # Add new items
        action_labels = []
        has_asset_options = False
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

            # Asset-picker identity (multi-match HITL): lets the client
            # generate a local preview thumbnail for this option.
            action.asset_name = action_data.get("asset_name") or ""
            action.library = action_data.get("library") or ""
            action.blend_file = action_data.get("blend_file") or ""
            action.asset_type = action_data.get("asset_type") or ""
            if action.asset_name and action.blend_file:
                has_asset_options = True

            action_labels.append(f"{action.label}({action.style})")

        # Kick off local preview generation for asset-picker options (embedded
        # .blend preview first, render fallback) — thumbnails pop in per tick.
        if has_asset_options and scene is not None:
            asset_choice_previews.schedule(scene, bubble)

        # Buttons alone must NEVER drive the session state — _apply_input_type_slot
        # is the one owner of the AWAITING_INPUT transition. Every paused turn
        # carries its input_type in the SAME slot event as its actions (backend
        # SlotTransformer, INPUT_REQUIRED case), so nothing is lost; but buttons
        # also ride events where the turn is NOT paused — the post-turn
        # "Retry failed tasks" chip (turn_actions, graph already at END), the
        # credits-upgrade CTA, the turn-resume prompt, and the locally replayed
        # batched-choice cards. Deriving the state here flipped those into
        # AWAITING_INPUT, which SSE-complete deliberately refuses to reset
        # (queue_processor._handle_sse_complete_internal), stranding the pill on
        # "Awaiting Input" and making the retry chip's own IDLE-only handler
        # reject the click the chip exists to make.

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
