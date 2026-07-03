# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Send Message Operator

Core send-message operator for Agent/Ask modes with HTTP/SSE streaming.
Generate mode is delegated to generate_ops.py.
"""

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import bpy
from bpy.types import Operator

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger

from ...constants import DEV_MODE, MAX_MESSAGE_LENGTH, SessionState, TEMP_PLACEHOLDER_PREFIX
from ...core.performance_metrics import get_metrics
from ...core import (
    get_dummy_response,
    get_session_manager,
    image_to_base64,
)
from ...core.connection_manager import get_connection_manager
from ...core.jsonrpc_client import get_jsonrpc_client
from ...core.queue_processor import (
    queue_sse_event,
    queue_sse_error,
    queue_sse_complete,
)
from ...core.sse_handler import create_sse_handler
from ...core.animation_manager import start_loader_animation
from ...core.message_helpers import add_agent_message, get_auth_token
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


class MIXIE_CHAT_OT_send_message(Operator):
    """Send a chat message via HTTP/SSE"""
    bl_idname = "mixie_chat.send_message"
    bl_label = "Send Message"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """Allow sending when idle, modifying, or awaiting input."""
        session = get_session_manager()
        scene = context.scene
        return session.get_state(scene) in (SessionState.IDLE, SessionState.MODIFYING, SessionState.AWAITING_INPUT)

    def execute(self, context):
        metrics = get_metrics()
        metrics.start_timer('send_message_total')

        scene = context.scene

        # Check if Generate mode - delegate to generate_ops
        if scene.mixie_chat_mode == 'GENERATE':
            metrics.stop_timer('send_message_total')
            return generate_ops.execute_generate_mode(self, context)

        message_text = scene.mixie_chat_input.strip()
        session = get_session_manager()
        is_modify = (session.get_state(scene) == SessionState.MODIFYING)
        is_awaiting_input = (session.get_state(scene) == SessionState.AWAITING_INPUT)
        pending_attachments = scene.mixie_chat_pending_attachments

        if not message_text and (is_modify or is_awaiting_input or len(pending_attachments) == 0):
            self.report({'WARNING'}, "Cannot send empty message")
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

        # Clear any STALE loader left by a prior turn before starting a new one.
        # If the previous turn was cancelled or the stream was closed client-side,
        # the backend can't emit a loader-off (you can't write to a closed stream),
        # so a "Thinking" loader — and its ghost placeholder bubble — can spin
        # forever. Starting a NEW turn is the reliable point to clear it. Modify /
        # input-response turns continue an existing flow, so leave those untouched.
        if not is_modify and not is_awaiting_input:
            stale_placeholders = []
            for i, m in enumerate(scene.mixie_chat_messages):
                if getattr(m, 'loader_visible', False):
                    m.loader_visible = False
                if getattr(m, 'bubble_id', '').startswith(TEMP_PLACEHOLDER_PREFIX):
                    stale_placeholders.append(i)
            for i in reversed(stale_placeholders):
                scene.mixie_chat_messages.remove(i)

        # OPTIMISTIC UPDATE: Add user message immediately for instant feedback
        user_msg = scene.mixie_chat_messages.add()
        user_msg.sender = 'USER'
        user_msg.text = message_text

        if not is_modify and not is_awaiting_input:
            # Copy attachments to message history (not for modify/input responses)
            for att in pending_attachments:
                msg_att = user_msg.attachments.add()
                msg_att.image_path = att.image_path
                msg_att.image_source = att.image_source
                msg_att.display_name = att.display_name

        # Clear input field immediately for better UX
        scene.mixie_chat_input = ""

        # Add temporary placeholder loader for instant feedback (non-modify/input only)
        # Will be removed when first backend SSE event creates the real bubble
        if not is_modify and not is_awaiting_input:
            placeholder = scene.mixie_chat_messages.add()
            placeholder.sender = 'AGENT'
            placeholder.bubble_id = f"{TEMP_PLACEHOLDER_PREFIX}{uuid.uuid4().hex[:12]}"
            placeholder.loader_visible = True
            placeholder.loader_texts = json.dumps(["Thinking..."])
            start_loader_animation()

        # Trigger immediate redraw to show user message + loader together
        metrics.start_timer('optimistic_ui_redraw')
        redraw_chat_areas()
        metrics.stop_timer('optimistic_ui_redraw')

        # Create SSE handler with queue callbacks
        base_url = get_server_url()
        target_scene_name = scene.name
        sse_handler = create_sse_handler(
            scene_name=target_scene_name,
            host=base_url,
            on_event=lambda event: queue_sse_event(event, target_scene_name),
            on_error=lambda error: queue_sse_error(error, target_scene_name),
            on_complete=lambda: queue_sse_complete(target_scene_name),
        )
        auth_token = get_auth_token()

        # Encode pending attachments to base64 asynchronously
        encoded_attachments = []
        if not is_modify and not is_awaiting_input and len(pending_attachments) > 0:
            metrics.start_timer('image_encoding_total')
            executor = get_image_encoder()

            # Submit encoding tasks to thread pool
            encoding_futures = []
            attachment_data = []  # Store (path, source) tuples

            for att in pending_attachments:
                att_data = (att.image_path, att.image_source)
                attachment_data.append(att_data)

                if att.image_source == 'FILE':
                    # FILE images are safe to encode off the main thread
                    future = executor.submit(image_to_base64, att.image_path, att.image_source)
                    encoding_futures.append(future)
                else:
                    # BLEND_DATA images access bpy.data — must stay on main thread
                    encoding_futures.append(None)

            # Wait for all encodings with timeout (5s per image)
            timeout_per_image = 5.0

            try:
                for idx, future in enumerate(encoding_futures):
                    if future is None:
                        # BLEND_DATA: encode on main thread (bpy.data access)
                        att_path, att_source = attachment_data[idx]
                        b64 = image_to_base64(att_path, att_source)
                    else:
                        b64 = future.result(timeout=timeout_per_image)
                    if b64:
                        att_path, att_source = attachment_data[idx]
                        ext = os.path.splitext(att_path)[1].lower() if att_source == 'FILE' else '.png'
                        mime_map = {
                            '.png': 'image/png',
                            '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg',
                            '.bmp': 'image/bmp',
                            '.tiff': 'image/tiff',
                            '.tif': 'image/tiff'
                        }
                        mime_type = mime_map.get(ext, 'image/png')
                        encoded_attachments.append({"base64": b64, "mime_type": mime_type})
                    else:
                        logger.warning(f"Failed to encode attachment index {idx}")

            except FuturesTimeoutError:
                # Timeout - proceed without attachments
                logger.error("Image encoding timeout - sending without attachments")
                self.report({'WARNING'}, "Image encoding timeout - message sent without images")
                encoded_attachments = []
            except Exception as e:
                logger.error(f"Image encoding error: {e}")
                self.report({'WARNING'}, f"Image encoding failed: {str(e)}")
                encoded_attachments = []

            total_encode_time = metrics.stop_timer('image_encoding_total')
            if encoded_attachments and total_encode_time is not None:
                logger.info(f"Encoded {len(encoded_attachments)} image attachment(s) in {total_encode_time*1000:.1f}ms")

        # Resolve each attachment to a stable bpy.data.images name. BLEND_DATA
        # attachments already carry the name in image_path; FILE attachments
        # are loaded into bpy.data.images on the main thread (check_existing
        # reuses an entry if one already points at this filepath). Sending the
        # name in the payload lets the backend inline it into the user
        # message, so the agent can pass image_name to generation tools
        # without a get_last_user_message round-trip.
        attachment_names: list = []
        if not is_modify and not is_awaiting_input and len(pending_attachments) > 0:
            for att in pending_attachments:
                resolved_name = ""
                try:
                    if att.image_source == 'BLEND_DATA':
                        img = bpy.data.images.get(att.image_path)
                        if img is not None:
                            resolved_name = img.name
                    elif att.image_source == 'FILE':
                        # Prefer an existing entry that already points at this file
                        for candidate in bpy.data.images:
                            if (
                                candidate.filepath == att.image_path
                                or bpy.path.abspath(candidate.filepath) == att.image_path
                            ):
                                resolved_name = candidate.name
                                break
                        if not resolved_name and os.path.isfile(att.image_path):
                            try:
                                img = bpy.data.images.load(att.image_path, check_existing=True)
                                img.colorspace_settings.name = 'sRGB'
                                # Pack so a later move/delete of the source file
                                # doesn't break the agent's reference.
                                try:
                                    img.pack()
                                except RuntimeError:
                                    pass
                                resolved_name = img.name
                            except RuntimeError as e:
                                logger.warning(f"Could not load attachment {att.image_path}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to resolve attachment name for {att.image_path}: {e}")
                attachment_names.append(resolved_name)

        metrics.start_timer('sse_start')

        if is_modify or is_awaiting_input:
            # Send via input stream (modify feedback or user input response)
            action = "modify" if is_modify else "respond"
            success = sse_handler.start_input_stream(
                session_id=session.get_session_id(scene),
                action=action,
                text=message_text,
                auth_token=auth_token,
            )
            if not success:
                self.report({'ERROR'}, "Failed to send input")
                session.set_state(scene, SessionState.IDLE)  # Return to idle on error
                metrics.stop_timer('send_message_total')
                return {'CANCELLED'}
            session.set_state(scene, SessionState.BUSY)  # Set to busy after sending
            session.clear_streaming()
        else:
            # Normal message: start new session stream
            session_id = session.start_session(scene, message_text)

            is_ask_mode = scene.mixie_chat_mode == 'ASK'
            plan_enabled = getattr(scene, 'mixie_chat_plan_enabled', True)
            plan_required = (not is_ask_mode) and plan_enabled
            execution_required = not is_ask_mode

            success = sse_handler.start_stream(
                message=message_text,
                instance_id=ws_client.connection_id,
                session_id=session_id,
                plan_required=plan_required,
                execution_required=execution_required,
                approval_required=True,
                auth_token=auth_token,
                image_attachments=encoded_attachments if encoded_attachments else None,
                attachment_names=attachment_names if attachment_names else None,
            )
            if not success:
                self.report({'ERROR'}, "Failed to start chat stream")
                session.set_error(scene)
                metrics.stop_timer('send_message_total')
                return {'CANCELLED'}

        metrics.stop_timer('sse_start')

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
        """Handle message sending in dev mode with simulated response."""
        scene = context.scene
        pending_attachments = scene.mixie_chat_pending_attachments

        # Add user message to history
        user_msg = scene.mixie_chat_messages.add()
        user_msg.sender = 'USER'
        user_msg.text = message_text

        # Copy attachments to message history
        for att in pending_attachments:
            msg_att = user_msg.attachments.add()
            msg_att.image_path = att.image_path
            msg_att.image_source = att.image_source
            msg_att.display_name = att.display_name

        # Add simulated agent response
        agent_msg = scene.mixie_chat_messages.add()
        agent_msg.sender = 'AGENT'
        agent_msg.text = get_dummy_response(message_text)

        # Clear input field and pending attachments
        scene.mixie_chat_input = ""
        pending_attachments.clear()

        # Notify UI to refresh
        redraw_chat_areas()

        logger.debug(f"Dev mode: Simulated response for: {message_text[:50]}...")
        self.report({'INFO'}, "Dev Mode: Message sent")
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_send_message,
)
