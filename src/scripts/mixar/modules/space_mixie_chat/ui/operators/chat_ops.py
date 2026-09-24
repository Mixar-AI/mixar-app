# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Send Message Operator

Core send-message operator for Agent mode with WebSocket streaming.
Generate mode is delegated to generate_ops.py.
"""

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.analytics.capture import capture
from mixar.modules.common.analytics.constants import EVENT_MESSAGE_SENT

from ...constants import DEV_MODE, MAX_MESSAGE_LENGTH, SessionState
from ...core.performance_metrics import get_metrics
from ...core import (
    encode_attachment_for_upload,
    get_session_manager,
)
from ...core.attachment_names import resolve_attachment_names
from ...core.composer_send import (
    HINT_QUEUED,
    OutgoingMessage,
    can_send,
    model_change_pending,
    is_interjection,
    send_user_message,
)
from ...core.connection_manager import get_connection_manager
from ...core.jsonrpc_client import get_jsonrpc_client
from ...core.message_helpers import add_turn_placeholder
from ...core.ui_utils import redraw_chat_areas
from . import generate_ops

logger = get_logger(__name__)


# Thread pool for parallel image encoding.
# Note: future.result() blocks the main thread, but multiple images encode
# concurrently (max_workers=2). The optimistic UI update (user message +
# loader shown before encoding) provides the real perceived-latency win.
_image_encoder_executor = None


def get_image_encoder():
    """Get or create the image encoding thread pool executor."""
    global _image_encoder_executor
    if _image_encoder_executor is None:
        _image_encoder_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="mixie_image_encoder"
        )
    return _image_encoder_executor


def cleanup_image_encoder():
    """Cleanup executor on module unload."""
    global _image_encoder_executor
    if _image_encoder_executor is not None:
        _image_encoder_executor.shutdown(wait=True, cancel_futures=True)
        _image_encoder_executor = None


def _send_when_handwriting_lands():
    """Re-run the send once Scribble's last recognition request has landed.

    Runs from an app timer (see ``scribble.defer_until_idle``), the same way
    the Enter key reaches the operator, so every pre-flight check runs again
    against the composer as it is NOW — with the transcription in it.
    """
    try:
        if hasattr(bpy.ops.mixie_chat, 'send_message'):
            bpy.ops.mixie_chat.send_message()
    except Exception as e:  # noqa: BLE001
        logger.debug("deferred send after handwriting failed: %s", e, exc_info=True)


class MIXIE_CHAT_OT_send_message(Operator):
    """Send a chat message via WebSocket"""
    bl_idname = "mixie_chat.send_message"
    bl_label = "Send Message"
    bl_options = {'REGISTER'}

    message_override: bpy.props.StringProperty(
        options={'HIDDEN', 'SKIP_SAVE'},
        description="Send shortcut text while preserving the main composer draft",
    )

    @classmethod
    def poll(cls, context):
        """Idle, modifying, awaiting input — or busy while the run is open
        (the message joins the run). One predicate for every send surface."""
        allowed, reason = can_send(context.scene)
        if not allowed:
            cls.poll_message_set(reason)
        return allowed

    def execute(self, context):
        from ...core.attachment_validation import pending_video_attachments
        if model_change_pending(context.scene) or pending_video_attachments(context.scene):
            self.report({'WARNING'}, can_send(context.scene)[1])
            return {'CANCELLED'}
        metrics = get_metrics()
        metrics.start_timer('send_message_total')

        scene = context.scene

        # Check if Generate mode - delegate to generate_ops
        if scene.mixie_chat_mode == 'GENERATE':
            capture(EVENT_MESSAGE_SENT, {
                "mode": "generate",
                "has_attachments": bool(len(scene.mixie_chat_pending_attachments)),
                "generate_type": getattr(scene, "mixie_chat_generate_type", "") or None,
            }, context=context)
            metrics.stop_timer('send_message_total')
            return generate_ops.execute_generate_mode(self, context)

        # Library mode: the typed text searches the asset library (empty = show
        # everything); results render as clickable thumbnails, no backend call.
        if scene.mixie_chat_mode == 'LIBRARY':
            from ...core import library_browse
            capture(EVENT_MESSAGE_SENT, {"mode": "library"}, context=context)
            metrics.stop_timer('send_message_total')
            return library_browse.execute_library_mode(self, context)

        if not self.message_override:
            from ...core import voice as voice_input
            if voice_input.defer_send(context):
                metrics.stop_timer('send_message_total')
                return {'CANCELLED'}

        session = get_session_manager()
        is_modify = (session.get_state(scene) == SessionState.MODIFYING)
        is_awaiting_input = (session.get_state(scene) == SessionState.AWAITING_INPUT)
        # A turn is streaming and the run is open: this message joins it. The
        # streaming turn's loader and bubbles stay untouched.
        interjecting = is_interjection(scene)

        # Scribble: handwriting still on the chat canvas, or still being
        # converted, belongs to THIS message. Flush the canvas and, if a
        # recognition request is in flight, send again once it has landed.
        # This sits ABOVE the empty-message check on purpose: a prompt
        # written entirely by hand is empty until its last batch lands, and
        # bouncing it as "empty" would throw away what the user just wrote.
        if not (is_modify or is_awaiting_input or self.message_override):
            try:
                from ...core import scribble
                from ...core import voice as voice_input
                scribble.flush_pending_ink()
                if scribble.defer_until_idle(_send_when_handwriting_lands):
                    self.report({'INFO'}, "Converting handwriting…")
                    metrics.stop_timer('send_message_total')
                    return {'CANCELLED'}
            except Exception as e:  # noqa: BLE001
                # Never lose a message over its optional handwriting.
                logger.debug("scribble flush before send skipped: %s", e, exc_info=True)

        message_text = (self.message_override or scene.mixie_chat_input).strip()
        pending_attachments = scene.mixie_chat_pending_attachments

        if not (is_modify or is_awaiting_input):
            try:
                from mixar.modules.scribble_mark.core import chat_bridge
                chat_bridge.flush_for_send(context)
                if not message_text:
                    message_text = chat_bridge.default_message(scene, context.window_manager)
            except Exception:  # Optional ink must never discard the user's words.
                logger.debug("Could not flush viewport ink for send", exc_info=True)

        # An empty Send while the agent's asset picker is up ANSWERS with the
        # selected pick — the best match unless a tile was clicked — exactly
        # as the picker's "Use This Asset" does. Pressing Send (or Enter) on
        # the highlighted tile is how people accept it; it used to warn.
        if not message_text and is_awaiting_input and not self.message_override:
            from ...core import asset_picker
            live = asset_picker.live_asset_picker(scene)
            if live is not None and live.picks:
                selected = getattr(context.window_manager, asset_picker.SELECTED_PROP, "") or ""
                pick = next((p for p in live.picks if p.value == selected), live.picks[0])
                metrics.stop_timer('send_message_total')
                return bpy.ops.mixie_chat.select_slot_action(
                    bubble_id=live.bubble_id, action_value=pick.value)

        if not message_text and (is_modify or is_awaiting_input or len(pending_attachments) == 0):
            self.report({'WARNING'}, "Cannot send empty message")
            return {'CANCELLED'}

        mark_context = None

        project_context = None
        if scene.mixie_chat_mode == 'ADDON_PROJECT' and not (is_modify or is_awaiting_input):
            if not str(getattr(scene, "mixie_addon_project_id", "") or ""):
                from mixar.modules.addon_project.ui.operators import (
                    ensure_addon_project_ready,
                )
                # Zero-question setup: default root + link, then this SAME
                # send proceeds to build_project_context below.
                if not ensure_addon_project_ready(self):
                    metrics.stop_timer('send_message_total')
                    return {'CANCELLED'}
            try:
                from mixar.modules.addon_project.context import build_project_context
                project_context = build_project_context(scene)
            except Exception as exc:
                self.report({'ERROR'}, getattr(exc, "message", str(exc)))
                metrics.stop_timer('send_message_total')
                return {'CANCELLED'}

        # Mark the user as engaged so the "Hi I'm Mixie" greeting
        # stops re-appearing whenever the message list transiently
        # empties (e.g. moodboard sync growing the bubble past the
        # empty-state height threshold). Resets on new_session.
        scene.mixie_chat_user_has_engaged = True

        # Security: Validate message length to prevent memory/performance issues
        if len(message_text) > MAX_MESSAGE_LENGTH:
            self.report(
                {'WARNING'},
                f"Message too long: {len(message_text)} chars (max {MAX_MESSAGE_LENGTH})"
            )
            return {'CANCELLED'}

        capture(EVENT_MESSAGE_SENT, {
            "mode": "addon_project" if scene.mixie_chat_mode == 'ADDON_PROJECT' else "agent",
            "has_attachments": bool(len(pending_attachments)),
            "is_modify": is_modify,
            "is_awaiting_input": is_awaiting_input,
            "plan_enabled": bool(getattr(scene, "mixie_chat_plan_enabled", False)),
            "auto_mode": bool(getattr(scene, "mixie_chat_auto_mode", False)),
            "model": getattr(scene, "mixie_chat_model", "") or None,
        }, context=context)

        # Dev mode: simulate response without backend
        if DEV_MODE:
            return self._execute_dev_mode(context, message_text)

        connection_manager = get_connection_manager()
        ws_client = get_jsonrpc_client()

        if not connection_manager.is_connected or not ws_client:
            self.report({'ERROR'}, "Not connected to server")
            return {'CANCELLED'}

        if not ws_client.connection_id:
            self.report({'ERROR'}, "WebSocket not ready — no connection ID")
            return {'CANCELLED'}

        # Finalize the annotated previews after preflight. Clean companions
        # belong only to the outgoing encoding list, never the composer/history.
        outgoing_attachments = list(pending_attachments)
        if not (is_modify or is_awaiting_input):
            try:
                from mixar.modules.scribble_mark.core import chat_bridge
                mark_context, mark_notes = chat_bridge.prepare_for_send(scene)
                outgoing_attachments = chat_bridge.preview.outgoing_attachments(scene)
                for note in mark_notes:
                    self.report({'INFO'}, f"Marks: {note}")
            except Exception as e:  # noqa: BLE001
                # The words are a complete request on their own; never lose a
                # message because the marks could not be assembled.
                logger.debug("scribble marks skipped on send: %s", e, exc_info=True)

        fresh_turn = not (is_modify or is_awaiting_input or interjecting)
        if fresh_turn:
            # A fresh turn is the reliable point to sweep asset-picker
            # preview thumbnails no bubble references anymore (an abandoned
            # picker never gets the empty-actions replacement that normally
            # cleans them).
            try:
                from ...core import asset_choice_previews
                asset_choice_previews.cleanup_orphans(scene)
            except Exception:
                pass

        # Turn checkpoint: the document exactly as it is before this fresh
        # turn (core/turn_checkpoints.py). Taken before the user bubble is
        # added so a restore shows the chat up to the previous reply. Never
        # blocks the send.
        checkpoint = None
        if fresh_turn:
            from ...core import turn_checkpoints
            checkpoint = turn_checkpoints.capture(scene, message_text)

        # OPTIMISTIC UPDATE: Add user message immediately for instant feedback
        user_msg = scene.mixie_chat_messages.add()
        user_msg.sender = 'USER'
        user_msg.text = message_text
        if interjecting:
            # Settled by the backend's `joined` ack (composer_send).
            user_msg.delivery_hint = HINT_QUEUED

        if not is_modify and not is_awaiting_input:
            # Copy attachments to message history (not for modify/input responses)
            for att in pending_attachments:
                msg_att = user_msg.attachments.add()
                msg_att.image_path = att.image_path
                msg_att.image_source = att.image_source
                msg_att.display_name = "Sketch" if att.scribble_view else att.display_name

        # Clear input field immediately for better UX
        if not self.message_override:
            scene.mixie_chat_input = ""

        # Temporary "Thinking..." placeholder (clears a stale loader first);
        # replaced when the first backend slot event creates the real bubble.
        # Modify / input-response turns continue an existing flow, and an
        # interjection answers inside the turn already streaming.
        if fresh_turn:
            add_turn_placeholder(scene)

        # Trigger immediate redraw to show user message + loader together
        metrics.start_timer('optimistic_ui_redraw')
        redraw_chat_areas()
        metrics.stop_timer('optimistic_ui_redraw')

        # Encode pending attachments to base64 asynchronously
        encoded_attachments = []
        if not is_modify and not is_awaiting_input and len(outgoing_attachments) > 0:
            metrics.start_timer('image_encoding_total')
            executor = get_image_encoder()

            # Submit encoding tasks to thread pool
            encoding_futures = []
            attachment_data = []  # Store (path, source) tuples

            for att in outgoing_attachments:
                att_data = (att.image_path, att.image_source)
                attachment_data.append(att_data)

                if att.image_source == 'FILE':
                    # FILE images (read + PIL compress) are safe off the main thread
                    future = executor.submit(
                        encode_attachment_for_upload, att.image_path, att.image_source
                    )
                    encoding_futures.append(future)
                else:
                    # BLEND_DATA images access bpy.data — must stay on main thread
                    encoding_futures.append(None)

            # Per-image budget. Compression bounds the work (a 12MP photo is
            # decoded at reduced scale and re-encoded in well under a second),
            # so a timeout here means something is genuinely wrong with that
            # one image — drop it and send the rest, never the whole set.
            timeout_per_image = 10.0

            for idx, future in enumerate(encoding_futures):
                att_path, att_source = attachment_data[idx]
                try:
                    if future is None:
                        # BLEND_DATA: encode on main thread (bpy.data access)
                        encoded = encode_attachment_for_upload(att_path, att_source)
                    else:
                        encoded = future.result(timeout=timeout_per_image)
                except FuturesTimeoutError:
                    logger.error(f"Image encoding timeout for {att_path}")
                    self.report({'WARNING'},
                                f"Skipped slow image: {os.path.basename(att_path)}")
                    continue
                except Exception as e:
                    logger.error(f"Image encoding error for {att_path}: {e}")
                    self.report({'WARNING'}, f"Image encoding failed: {str(e)}")
                    continue

                if encoded:
                    b64, mime_type = encoded
                    encoded_attachments.append({"base64": b64, "mime_type": mime_type})
                else:
                    logger.warning(f"Failed to encode attachment index {idx}")

            total_encode_time = metrics.stop_timer('image_encoding_total')
            if encoded_attachments and total_encode_time is not None:
                logger.info(f"Encoded {len(encoded_attachments)} image attachment(s) in {total_encode_time*1000:.1f}ms")

        # Stable bpy.data.images names (and #1268 imported object names) the
        # backend inlines into the user message — core/attachment_names.py.
        attachment_names: list = []
        imported_object_names: list = []
        if not is_modify and not is_awaiting_input and len(outgoing_attachments) > 0:
            attachment_names, imported_object_names = resolve_attachment_names(
                outgoing_attachments
            )

        metrics.start_timer('agent_send')

        # ONE choice point (core/composer_send.py): input answer, interjection
        # into the open run, or a fresh socket turn. The optimistic user bubble
        # above keeps the raw message_text; the wire message is composed there.
        success, error = send_user_message(scene, OutgoingMessage(
            text=message_text,
            image_attachments=encoded_attachments,
            attachment_names=attachment_names,
            imported_object_names=imported_object_names,
            project_context=project_context,
            mark_context=mark_context,
            user_message=user_msg,
        ))
        if not success:
            self.report({'ERROR'}, error)
            metrics.stop_timer('send_message_total')
            return {'CANCELLED'}

        metrics.stop_timer('agent_send')

        # The turn's command id is the backend's request id: bind the
        # checkpoint to it so a restore can rewind the conversation too.
        if checkpoint is not None:
            from ...core import turn_checkpoints
            from ...core.turn_transport import get_turn_handler
            handler = get_turn_handler(scene.name)
            request_id = (getattr(handler, "last_command_id", "") if handler else "") \
                or getattr(user_msg, "bubble_id", "")
            turn_checkpoints.bind_request(checkpoint, request_id)

        # Drop the moodboard selection for any images we just sent.
        # Without this the moodboard's polling sync would re-add them
        # to pending_attachments on the next tick, making it look like
        # the user is still queueing the same images for the next
        # message. The moodboard is the source of truth — once a
        # message goes out, those moodboard images have served their
        # purpose for *this* turn. Must run BEFORE the clear() below
        # so we can still see which attachments were moodboard-origin.
        try:
            from mixar.modules.moodboard.core.chat_sync import (
                deselect_all_moodboard_origin_attachments,
            )
            deselect_all_moodboard_origin_attachments(scene)
        except Exception as e:  # noqa: BLE001
            # Moodboard module may not be loaded — never block the send.
            logger.debug(
                "moodboard deselect on send skipped: %s", e, exc_info=True
            )

        # Settle the marks that just went out and lower the freeze. The marks
        # themselves are KEPT — a follow-up turn refers back to them, and the
        # vertex groups and cameras they name are still live in the scene.
        # Unconditional: sending is the end of the gesture whether or not
        # anything was drawn. Gated on mark_context, arming and then sending
        # without marking left the viewport frozen with no marks to explain it.
        if not is_modify and not is_awaiting_input:
            try:
                from mixar.modules.scribble_mark.core import chat_bridge
                chat_bridge.finish_send(scene)
            except Exception as e:  # noqa: BLE001
                logger.debug("scribble mark settle skipped: %s", e, exc_info=True)

        # Clear pending attachments (input already cleared above for optimistic update)
        pending_attachments.clear()

        # Final UI refresh (already did optimistic redraw above)
        metrics.start_timer('final_ui_redraw')
        redraw_chat_areas()
        metrics.stop_timer('final_ui_redraw')

        total_time = metrics.stop_timer('send_message_total')
        if total_time:
            logger.info(f"Send message took {total_time*1000:.1f}ms total (with async encoding)")

        self.report({'INFO'}, "Message sent")
        return {'FINISHED'}

    def _execute_dev_mode(self, context, message_text: str):
        """Handle message sending in dev mode with a scripted streaming turn.

        Streams a realistic agent turn (thinking → plan → tools → Markdown
        answer) through the real slot pipeline so the output UI can be
        evaluated without a backend.
        """
        from ...core.dev_stream import start_demo_stream

        scene = context.scene
        pending_attachments = scene.mixie_chat_pending_attachments

        # Copy any pending attachments onto a user bubble before streaming,
        # matching the live path. start_demo_stream adds the user text bubble.
        if len(pending_attachments) > 0:
            user_msg = scene.mixie_chat_messages.add()
            user_msg.sender = 'USER'
            user_msg.text = message_text
            for att in pending_attachments:
                msg_att = user_msg.attachments.add()
                msg_att.image_path = att.image_path
                msg_att.image_source = att.image_source
                msg_att.display_name = "Sketch" if att.scribble_view else att.display_name
            start_demo_stream(scene, user_text="")
        else:
            start_demo_stream(scene, user_text=message_text)

        # Clear input field and pending attachments
        scene.mixie_chat_input = ""
        pending_attachments.clear()
        redraw_chat_areas()

        logger.debug(f"Dev mode: streaming demo turn for: {message_text[:50]}...")
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_send_message,
)
