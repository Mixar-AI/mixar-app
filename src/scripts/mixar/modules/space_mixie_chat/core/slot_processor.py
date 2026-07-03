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


# Bubbles whose ephemeral stream has been classified as a raw JSON payload.
# Sticky for the life of the stream — see _apply_ephemeral_slot.
_json_ephemeral_bubbles: set = set()

# Bubbles past the plan boundary: their further content (the narration) streams
# into the LIVE thinking panel (thinking_text + thinking_active). On turn end
# finalize_turn flips them to the collapsed "Thought for Ns" dropdown.
_narration_bubbles: set = set()

# bubble_id -> wall-clock time the narration began, for the "Thought for Ns"
# duration reported on finalize.
_narration_start: dict = {}

# The scaffold's cute pre-plan spinner ("Calling Mixie…/She's here…"), captured
# when it's hidden, to bridge onto the response bubble so the live indicator
# stays animated from the plan until the response's own working loader arrives
# (~2-3s later) — without it there's a dead, un-animated window.
_bridge_loader: Optional[str] = None


# A single empty paragraph: forces the C++ renderer onto the markdown path
# (has_markdown_segments == true) where an empty-text segment draws nothing,
# so raw text is never shown via the plain-text bubble fallback. This is how we
# *hide* a leaked payload without destroying the underlying content value.
_HIDE_SEGMENTS = [{"type": "paragraph", "text": ""}]


def _split_plan_narration(content: str):
    """Split a content blob into (plan, narration) the first time the boundary
    appears, else return None.

    The backend streams the plan ("**Plan** (confidence …):\\n1. …") and then,
    after a blank line, the human narration ("Built a rustic cabin…"). The first
    blank line after the plan marker is the boundary: everything before stays as
    the persistent Plan; everything after becomes the live thinking stream.
    """
    if not content:
        return None
    plan_idx = content.find("**Plan**")
    if plan_idx == -1:
        return None
    nb = content.find("\n\n", plan_idx)
    if nb == -1:
        return None
    plan_part = content[:nb]
    narration_part = content[nb:].lstrip("\n")
    if not narration_part:
        return None
    return plan_part, narration_part


def _extinguish_other_loaders(scene, keep_bubble_id: str) -> None:
    """Hide every visible loader except `keep_bubble_id`'s — one spinner, always."""
    for msg in getattr(scene, "mixie_chat_messages", []) or []:
        if (getattr(msg, "bubble_id", "") != keep_bubble_id
                and getattr(msg, "loader_visible", False)):
            msg.loader_visible = False


def _find_response_bubble(scene):
    """The main turn bubble — the most recent AGENT bubble that is NOT a
    JSON-intent scaffold — onto which working status is consolidated."""
    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages:
        return None
    for idx in range(len(messages) - 1, -1, -1):
        m = messages[idx]
        bid = getattr(m, "bubble_id", "")
        if getattr(m, "sender", "") == "AGENT" and bid and bid not in _json_ephemeral_bubbles:
            return m
    return None


def collapse_live_thinking(bubble, scene=None) -> None:
    """Collapse a bubble's LIVE thinking panel into the quiet '▸ Thought for Ns'
    dropdown — called when the next tool step starts (so reasoning collapses
    progressively) and on turn end. A later narration burst re-opens it live."""
    import time
    if not getattr(bubble, "thinking_active", False):
        return
    if (getattr(bubble, "thinking_text", "") or "").strip():
        bubble.thinking_active = False
        bubble.thinking_collapsed = True
        bid = getattr(bubble, "bubble_id", "")
        start = _narration_start.get(bid)
        dur = int((time.time() - start) * 1000) if start else 1000
        bubble.thinking_duration_ms = max(1000, dur)
    else:
        bubble.thinking_active = False
    if scene is not None:
        _bump_layout_epoch(scene)


def finalize_turn(scene) -> None:
    """End-of-turn cleanup, called on stream completion AND user abort.

    - Collapses each bubble's LIVE thinking panel (already in thinking_text)
      into the quiet "Thought for Ns" dropdown.
    - Marks any still-RUNNING tool steps DONE so their animation settles.
    - Hides lingering loaders.
    A retry then starts from a clean, settled transcript instead of interleaving
    with a half-finished turn.
    """
    import time

    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages:
        return
    for msg in messages:
        bid = getattr(msg, "bubble_id", "")

        # Collapse the live thinking panel into the "Thought for Ns" dropdown.
        if (bid in _narration_bubbles) or getattr(msg, "thinking_active", False):
            if (getattr(msg, "thinking_text", "") or "").strip():
                msg.thinking_active = False
                msg.thinking_collapsed = True  # show as "▸ Thought for Ns"
                if not getattr(msg, "thinking_duration_ms", 0):
                    start = _narration_start.get(bid)
                    dur = int((time.time() - start) * 1000) if start else 1000
                    msg.thinking_duration_ms = max(1000, dur)
            else:
                msg.thinking_active = False
        _narration_bubbles.discard(bid)
        _narration_start.pop(bid, None)

        try:
            for row in msg.step_items:
                if row.status == "RUNNING":
                    row.status = "DONE"
        except Exception:  # noqa: BLE001
            pass
        if getattr(msg, "loader_visible", False):
            msg.loader_visible = False

    _bump_layout_epoch(scene)


def _looks_like_json_payload(text: str) -> bool:
    """True when text is (or is becoming) a raw JSON object/array dump.

    Agent prose effectively never starts with ``{`` or ``[``, so a leading
    brace/bracket reliably flags a structured payload the backend streamed into
    a prose slot (plan/tool-use JSON). Matching on the first char — rather than
    a full ``json.loads`` — also catches *partial* JSON mid-stream, which is
    exactly when the old guard let the leak through.
    """
    stripped = text.lstrip()
    return bool(stripped) and stripped[0] in "{["


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
            ("content", lambda: self._apply_content_slot(bubble, event_data["content"], scene)),
            ("ephemeral", lambda: self._apply_ephemeral_slot(bubble, event_data["ephemeral"], scene)),
            ("todo", lambda: self._apply_todo_slot(bubble, event_data["todo"])),
            ("steps", lambda: self._apply_steps_slot(bubble, event_data["steps"], scene)),
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

        # The backend drives WORKING status on BOTH the JSON-intent bubble and
        # the response bubble, and never hides one until the end (see app.log) —
        # which doubled the spinner and, when hidden outright, left the first
        # couple of tools with no indicator. Consolidate to ONE indicator: mirror
        # the intent bubble's status onto the main response bubble (stable, at the
        # bottom) and hide it on the intent bubble itself.
        bid = getattr(bubble, "bubble_id", "")
        if bid and bid in _json_ephemeral_bubbles and scene is not None:
            main = _find_response_bubble(scene)
            if (main is not None and getattr(main, "bubble_id", "") != bid
                    and bubble.loader_visible):
                main.loader_texts = bubble.loader_texts
                main.loader_current_index = 0
                if not main.loader_visible:
                    main.loader_visible = True
                self._start_loader_timer()  # ensure the spinner animates
                _extinguish_other_loaders(scene, getattr(main, "bubble_id", ""))
            bubble.loader_visible = False

        # ONE spinner, always: whichever bubble's loader just turned visible is
        # the live indicator — extinguish every other bubble's. The synced
        # backend already moves its single loader between bubbles; this is the
        # client-side invariant for older backends that stack them.
        if bubble.loader_visible and scene is not None:
            _extinguish_other_loaders(scene, bid)

        # Start/stop loader timer based on visibility change
        if bubble.loader_visible and not was_visible:
            self._start_loader_timer()
        elif not bubble.loader_visible and was_visible:
            if scene is not None:
                self._stop_loader_timer_if_no_active(scene)

    def _apply_content_slot(self, bubble: Any, content_data: dict, scene=None) -> None:
        """Apply a content slot update (persistent text).

        Live thinking: the Plan stays as content; everything after it (the
        narration) streams into the LIVE thinking panel (thinking_text +
        thinking_active), pinned at the bottom of the turn, and collapses to
        "Thought for Ns" on completion (see finalize_turn).
        """
        import time
        bubble_id = getattr(bubble, "bubble_id", "")

        # Past the plan boundary → stream further content into the live panel.
        if (bubble_id and bubble_id in _narration_bubbles
                and scene is not None and "append" in content_data):
            self._append_live_thinking(bubble, content_data.get("append") or "", scene)
            return

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

        # Bridge the scaffold's spinner onto the response bubble the moment the
        # plan starts landing, so the live indicator animates continuously until
        # this bubble's own working loader arrives (it lags the plan by ~2-3s).
        global _bridge_loader
        if (_bridge_loader and scene is not None and bubble_id
                and bubble_id not in _json_ephemeral_bubbles
                and not getattr(bubble, "loader_visible", False)
                and getattr(bubble, "content", "")):
            bubble.loader_texts = _bridge_loader
            bubble.loader_current_index = 0
            bubble.loader_visible = True
            _bridge_loader = None
            self._start_loader_timer()

        # First time the plan→narration boundary appears: keep the plan as
        # content, move the narration into the live panel, and route the rest
        # there too.
        if scene is not None and bubble_id and bubble_id not in _narration_bubbles:
            split = _split_plan_narration(bubble.content)
            if split is not None:
                plan_part, narration_part = split
                bubble.content = plan_part
                bubble.text = plan_part
                _narration_bubbles.add(bubble_id)
                _narration_start[bubble_id] = time.time()
                self._reparse_content_markdown(bubble, is_append=False)
                if narration_part.strip():
                    self._append_live_thinking(bubble, narration_part, scene)
                return

        self._reparse_content_markdown(bubble, is_append=("append" in content_data))

    def _append_live_thinking(self, bubble: Any, text: str, scene) -> None:
        """Append narration to the live thinking panel and keep it streaming."""
        if not text:
            return
        _fast_set(bubble, "thinking_text",
                  ((bubble.thinking_text or "") + text)[:_SLOT_TEXT_MAXLEN])
        # Guarded attribute writes: these fire RNA updates, so only flip on a
        # real transition — not per streamed token.
        if not bubble.thinking_active:
            bubble.thinking_active = True
        if bubble.thinking_collapsed:
            bubble.thinking_collapsed = False
        if scene is not None:
            _bump_layout_epoch(scene)

    def _reparse_content_markdown(self, bubble: Any, is_append: bool) -> None:
        """(Re)build the markdown_segments metadata from bubble.content."""
        bubble_id = bubble.bubble_id if hasattr(bubble, 'bubble_id') else ""
        try:
            if bubble.content:
                # Safety net: a raw JSON dump in the content slot is hidden,
                # never rendered as broken prose (see _looks_like_json_payload).
                if _looks_like_json_payload(bubble.content):
                    segments = _HIDE_SEGMENTS
                    logger.info(
                        "[SLOT:CONTENT] hid JSON-leading payload bubble=%s len=%d",
                        bubble_id, len(bubble.content),
                    )
                    if bubble_id:
                        from .markdown_parser import clear_incremental_cache
                        clear_incremental_cache(bubble_id)
                elif is_append and bubble_id:
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

        bid = getattr(bubble, "bubble_id", "")

        # The backend streams a raw JSON intent/plan into the ephemeral/thinking
        # slot, token-by-token (`{` `"` `int` `ents` …). It must never surface as
        # leaked prose. Suppression has to be STICKY: blanking per-append fails
        # because the next token rebuilds a brace-less string the per-call guard
        # misses. So once a bubble's ephemeral is classified JSON, drop the whole
        # stream until it clears.
        if ephemeral_data.get("clear"):
            was_json = bid in _json_ephemeral_bubbles
            _json_ephemeral_bubbles.discard(bid)
            finalized = apply_ephemeral_to_bubble(bubble, ephemeral_data, time.time())
            if was_json:
                # Never surface JSON as a finalized "Thought" dropdown.
                if _looks_like_json_payload(bubble.thinking_text):
                    bubble.thinking_text = ""
                bubble.thinking_active = False
            if finalized:
                _bump_layout_epoch(scene)
            return

        if bid in _json_ephemeral_bubbles:
            return  # already classified as JSON — drop this token

        finalized = apply_ephemeral_to_bubble(bubble, ephemeral_data, time.time())
        if _looks_like_json_payload(bubble.ephemeral):
            logger.info("[SLOT:EPHEMERAL] suppressing JSON stream bubble=%s", bid)
            _json_ephemeral_bubbles.add(bid)
            bubble.ephemeral = ""
            bubble.thinking_active = False
            # A loader can land on this intent bubble a tick BEFORE it's classified
            # as JSON (the cute "Calling Mixie…/She's here…" texts arrive just
            # before the suppression marker). At loader time the mirror in
            # _apply_loader_slot couldn't fire (bid wasn't in the set yet), so the
            # loader stayed visible and the intent scaffold renders as a tall
            # ephemeral bubble — the big empty gap above the plan on follow-up
            # turns. Hide it now; the real working-status loaders that follow are
            # mirrored onto the response bubble in _apply_loader_slot.
            if getattr(bubble, "loader_visible", False):
                bubble.loader_visible = False
                # Keep the spinner texts to bridge onto the response bubble so the
                # live indicator doesn't go dead between the plan and the first
                # working loader.
                global _bridge_loader
                _bridge_loader = getattr(bubble, "loader_texts", "") or None
                if scene is not None:
                    self._stop_loader_timer_if_no_active(scene)

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

        # De-duplicate against the plan: the backend sends the plan BOTH as
        # markdown in `content` and again as a todo with the identical sentence,
        # which renders as a stacked duplicate. Drop any todo item whose text is
        # already shown in this bubble's content.
        content_text = (getattr(bubble, "content", "") or "")

        # Track status counts for logging
        status_counts = {'PENDING': 0, 'IN_PROGRESS': 0, 'DONE': 0, 'FAILED': 0}

        # Add new items
        for idx, item_data in enumerate(todo_items):
            item_text = item_data.get("text") or ""
            # Case-insensitive: the todo capitalizes its first letter while the
            # plan line keeps the raw scope ("Greeting / small talk" vs
            # "… — greeting / small talk"), which broke the exact match.
            if (item_text and item_text.strip()
                    and item_text.strip().casefold() in content_text.casefold()):
                continue  # duplicate of the plan already in content — skip
            item = bubble.todo_items.add()
            # Handle None values - Blender properties don't accept None for
            # strings. Clamps mirror the maxlens in chat_slot_types.py
            # (item_id=64 matches the C++ TodoItemSlotData::id buffer).
            _fast_set(item, "item_id", (item_data.get("id") or "")[:64])
            _fast_set(item, "text", item_text[:512])

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
