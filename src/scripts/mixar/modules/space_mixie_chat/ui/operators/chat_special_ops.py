# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Special Message Operators

Slot action button click handler.
"""

import queue
import threading

import bpy
from bpy.types import Operator
from bpy.props import IntProperty, StringProperty

from mixar.config.logging_config import get_logger

from ...constants import (
    FEEDBACK_STATUS_FAILED,
    FEEDBACK_STATUS_RECEIVED,
    FEEDBACK_STATUS_SENDING,
)
from ...core.feedback_policy import validate_feedback_comment
from ...core.ui_utils import bump_layout_epoch as _bump_layout_epoch
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)

_feedback_post_queue: queue.Queue = queue.Queue()
_feedback_worker_lock = threading.Lock()
_feedback_worker_started = False


def _feedback_worker() -> None:
    """Process feedback requests in click order on one daemon thread."""
    while True:
        post = _feedback_post_queue.get()
        try:
            post()
        except Exception as exc:
            # Each post also handles its own failure; keep the worker alive if
            # a future implementation accidentally lets an exception escape.
            logger.warning(f"Feedback worker recovered from an error: {exc}")
        finally:
            _feedback_post_queue.task_done()


def _enqueue_feedback_post(post) -> None:
    """Queue a post and lazily start the single FIFO feedback worker."""
    global _feedback_worker_started

    with _feedback_worker_lock:
        if not _feedback_worker_started:
            threading.Thread(
                target=_feedback_worker,
                name="MixarFeedback",
                daemon=True,
            ).start()
            _feedback_worker_started = True
    _feedback_post_queue.put(post)


def _post_feedback_async(scene, payload: dict, on_complete=None) -> bool:
    """Post agent feedback without blocking Blender's main thread.

    ``on_complete`` is always marshalled back to Blender's main thread and
    receives a boolean indicating whether the server accepted the request.
    """
    try:
        from ...core import get_session_manager

        session_id = get_session_manager().get_session_id(scene)
        if not session_id:
            logger.warning("Feedback send skipped: no session_id")
            return False

        from mixar.config.config import get_server_url
        from ...constants import AGENT_FEEDBACK_ENDPOINT

        base_url = get_server_url()

        try:
            from mixar.modules.auth.core.auth import get_access_token

            token = get_access_token() or ""
        except Exception:
            token = ""

        request_payload = {**payload, "session_id": session_id}

        def _notify(success: bool) -> None:
            if on_complete is None:
                return
            from ...core.main_thread_executor import run_on_main_thread

            run_on_main_thread(lambda: on_complete(success))

        def _post() -> None:
            success = False
            try:
                import httpx

                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                response = httpx.post(
                    f"{base_url}{AGENT_FEEDBACK_ENDPOINT}",
                    json=request_payload,
                    headers=headers,
                    # The backend forwards to Langfuse ingestion synchronously,
                    # which intermittently takes >10s — outlive its 20s worst
                    # case so a slow-but-successful push isn't reported as a
                    # failure. Runs on the FIFO feedback worker thread, so the
                    # wait never blocks Blender's UI.
                    timeout=30.0,
                )
                response.raise_for_status()
                success = True
            except Exception as exc:
                logger.warning(f"Feedback POST failed (non-critical): {exc}")
            finally:
                _notify(success)

        _enqueue_feedback_post(_post)
        return True
    except Exception as exc:
        logger.warning(f"Feedback send skipped: {exc}")
        return False


def _find_feedback_message(scene, bubble_id: str):
    """Return the message matching ``bubble_id``, if it still exists."""
    for msg in scene.mixie_chat_messages:
        if getattr(msg, 'bubble_id', '') == bubble_id:
            return msg
    return None


def _queue_feedback_comment(scene, msg) -> tuple[bool, str]:
    """Validate and queue a comment submission for one feedback message."""
    comment = msg.feedback_comment.strip()
    validation_error = validate_feedback_comment(
        msg.feedback_rating,
        comment,
        msg.feedback_comment_submitting,
    )
    if validation_error:
        return False, validation_error

    bubble_id = msg.bubble_id
    rating = int(msg.feedback_rating)
    msg.feedback_comment_submitting = True
    msg.feedback_status = FEEDBACK_STATUS_SENDING

    def _complete(success: bool) -> None:
        current = _find_feedback_message(scene, bubble_id)
        if current is None:
            return
        current.feedback_comment_submitting = False
        if success:
            current.feedback_comment = ""
            current.feedback_comment_expanded = False
            current.feedback_submitted_comment = comment
            current.feedback_status = FEEDBACK_STATUS_RECEIVED
        else:
            # Keep the authored text editable so a transient backend/network
            # failure is retryable without asking the user to reconstruct it.
            current.feedback_comment = comment
            current.feedback_comment_expanded = True
            current.feedback_status = FEEDBACK_STATUS_FAILED
        _bump_layout_epoch(scene)
        redraw_chat_areas()

    queued = _post_feedback_async(
        scene,
        {
            "bubble_id": bubble_id,
            "rating": rating,
            "comment": comment,
        },
        on_complete=_complete,
    )
    if not queued:
        msg.feedback_comment_submitting = False
        msg.feedback_comment = comment
        msg.feedback_comment_expanded = True
        msg.feedback_status = FEEDBACK_STATUS_FAILED
        _bump_layout_epoch(scene)
        return False, "Could not queue feedback. Please try again."

    _bump_layout_epoch(scene)
    logger.info(
        f"Feedback comment queued: bubble_id={bubble_id}, "
        f"comment_length={len(comment)}"
    )
    return True, ""


def _deferred_send_message():
    """Execute send_message via timer to avoid calling bpy.ops in operator exec."""
    try:
        if hasattr(bpy.ops.mixie_chat, 'send_message'):
            bpy.ops.mixie_chat.send_message()
    except Exception as e:
        logger.error(f"Deferred send_message failed: {e}")


class MIXIE_CHAT_OT_select_slot_action(Operator):
    """Handle slot action button click"""
    bl_idname = "mixie_chat.select_slot_action"
    bl_label = "Select Slot Action"
    bl_options = {'REGISTER'}

    bubble_id: StringProperty(
        name="Bubble ID",
        description="ID of the bubble containing the action",
        default=""
    )
    action_value: StringProperty(
        name="Action Value",
        description="Value of the selected action",
        default=""
    )

    @classmethod
    def poll(cls, context):
        """Allow button clicks whenever action buttons are visible.

        Previously required session.is_connected, but that caused buttons
        to silently fail if the connection dropped after they were displayed.
        The execute() method handles connection state internally.
        """
        return True

    def execute(self, context):
        logger.warning(
            f"[SLOT ACTION] execute called: bubble_id='{self.bubble_id}', "
            f"value='{self.action_value}'"
        )

        if not self.bubble_id or not self.action_value:
            logger.warning("[SLOT ACTION] CANCELLED: Missing bubble_id or action_value")
            self.report({'WARNING'}, "Missing bubble_id or action_value")
            return {'CANCELLED'}

        # Local intercept: "which model?" ask buttons (posted by
        # chat_props._ask_model_choice). Value shape:
        #   chat_model:<service_key>:<model_slug>
        # Stores the choice for the next generate send — no backend
        # round-trip, works while disconnected.
        if self.action_value.startswith("chat_model:"):
            return self._apply_model_choice(context)

        # Library mode: append the clicked asset into the scene locally — no
        # backend round-trip, works while disconnected. The asset identity rides
        # on the action item (asset_name/library/blend_file/asset_type).
        if self.action_value.startswith("lib_add:"):
            return self._add_library_asset(context)

        if self.action_value == "export_destination_selected":
            from ...core import get_session_manager
            from ...core.export_destination import has_destination
            session_id = get_session_manager().get_session_id(context.scene)
            if not has_destination(session_id):
                bubble = next((m for m in context.scene.mixie_chat_messages
                               if getattr(m, "bubble_id", "") == self.bubble_id), None)
                if bubble is None or getattr(bubble, "input_type", "") != "file_save":
                    self.report({'WARNING'}, "Export request is no longer available")
                    return {'CANCELLED'}
                return bpy.ops.mixie_chat.choose_export_location(
                    'INVOKE_DEFAULT', bubble_id=self.bubble_id,
                    session_id=session_id,
                    export_format=bubble.export_format,
                    target_scope=bubble.export_scope,
                    suggested_filename=bubble.export_suggested_filename,
                )

        # #1251 import picker: same two-pass bridge as the export picker. The
        # native open dialog stores the path in the process-local vault; the
        # re-dispatch POSTs only the action value — the path never travels.
        if self.action_value == "import_source_selected":
            from ...core import get_session_manager
            from ...core.import_source import has_source
            session_id = get_session_manager().get_session_id(context.scene)
            if not has_source(session_id):
                bubble = next((m for m in context.scene.mixie_chat_messages
                               if getattr(m, "bubble_id", "") == self.bubble_id), None)
                if bubble is None or getattr(bubble, "input_type", "") != "file_open":
                    self.report({'WARNING'}, "Import request is no longer available")
                    return {'CANCELLED'}
                return bpy.ops.mixie_chat.choose_import_file(
                    'INVOKE_DEFAULT', bubble_id=self.bubble_id,
                    session_id=session_id,
                    formats=getattr(bubble, "import_formats", ""),
                )

        # Credit-upgrade CTA: open the manage-subscription page via the shared
        # upgrade operator (seamless auth handoff) instead of dispatching the
        # value back to the backend. Handled before the connection check so it
        # works even when disconnected or out of credits.
        from mixar.modules.common.notifications.credit_upgrade import (
            CREDIT_UPGRADE_CHAT_ACTION,
        )
        if self.action_value == CREDIT_UPGRADE_CHAT_ACTION:
            try:
                bpy.ops.mixar.open_credit_upgrade('INVOKE_DEFAULT')
            except Exception as e:
                logger.error(f"[SLOT ACTION] Failed to open credit upgrade: {e}")
                self.report({'ERROR'}, "Couldn't open the upgrade page")
                return {'CANCELLED'}
            return {'FINISHED'}

        # Check connection before dispatching
        from ...core import get_session_manager
        session = get_session_manager()
        if not session.is_connected(context.scene):
            if self.action_value == "export_destination_selected":
                from ...core.export_destination import clear_destination
                clear_destination(session.get_session_id(context.scene))
            elif self.action_value == "import_source_selected":
                # A stale vault entry would skip the picker on the next click
                # and import a file the user did not just choose.
                from ...core.import_source import clear_source
                clear_source(session.get_session_id(context.scene))
            logger.warning("[SLOT ACTION] CANCELLED: Not connected to server")
            self.report({'WARNING'}, "Not connected to server. Please reconnect.")
            return {'CANCELLED'}

        logger.info(
            f"Slot action selected: bubble_id={self.bubble_id}, "
            f"value={self.action_value}"
        )

        scene = context.scene

        # A batched choice interrupt is a client-local wizard. Each click
        # updates the existing card immediately; only the final selection
        # resumes the backend graph, removing the network delay between cards.
        batch = self._advance_batched_choice(scene)
        if batch is not None and batch["handled"]:
            redraw_chat_areas()
            return {'FINISHED'}

        # Find the bubble by bubble_id and get the action label for user message
        action_label = self.action_value
        for msg in scene.mixie_chat_messages:
            if hasattr(msg, 'bubble_id') and msg.bubble_id == self.bubble_id:
                for action_item in msg.action_items:
                    if action_item.value == self.action_value:
                        action_label = action_item.label
                        break
                # Clear action items from the bubble
                msg.action_items.clear()
                break

        # Dispatch action
        try:
            from ...constants import SessionState
            from ...core.queue_processor import (
                queue_sse_event,
                queue_sse_error,
                queue_sse_complete,
            )
            from ...core.sse_handler import create_sse_handler
            from mixar.config.config import get_server_url

            # Handle modify action specially - user needs to type feedback first
            if self.action_value == "modify":
                session.set_state(scene, SessionState.MODIFYING)

                # Add hint instead of "Modify" user message
                hint_msg = scene.mixie_chat_messages.add()
                hint_msg.sender = 'AGENT'
                hint_msg.text = "Type your feedback below and press Enter to modify the plan."

                logger.info("Switched to MODIFYING state via slot action")
                self.report({'INFO'}, "Enter your feedback in the chat input")
            else:
                # Add user message showing the selected action
                user_msg = scene.mixie_chat_messages.add()
                user_msg.sender = 'USER'
                user_msg.text = action_label

                base_url = get_server_url()
                target_scene_name = scene.name
                sse_handler = create_sse_handler(
                    scene_name=target_scene_name,
                    host=base_url,
                    on_event=lambda event: queue_sse_event(event, target_scene_name),
                    on_error=lambda error: queue_sse_error(error, target_scene_name),
                    on_complete=lambda: queue_sse_complete(target_scene_name),
                )

                # Get auth token
                try:
                    from mixar.modules.auth.core.auth import get_access_token
                    auth_token = get_access_token() or ""
                except Exception:
                    auth_token = ""

                success = sse_handler.start_input_stream(
                    session_id=session.get_session_id(scene),
                    action=self.action_value,
                    auth_token=auth_token,
                )

                if success:
                    session.set_state(scene, SessionState.BUSY)
                    session.clear_streaming()
                else:
                    logger.error("Failed to start input stream for slot action")
                    if self.action_value == "export_destination_selected":
                        from ...core.export_destination import clear_destination
                        clear_destination(session.get_session_id(scene))
                    elif self.action_value == "import_source_selected":
                        from ...core.import_source import clear_source
                        clear_source(session.get_session_id(scene))
                    self.report({'ERROR'}, "Failed to send action")

        except Exception as e:
            logger.error(f"Error dispatching slot action: {e}")
            self.report({'ERROR'}, f"Error: {e}")

        redraw_chat_areas()
        return {'FINISHED'}

    def _add_library_asset(self, context):
        """Library mode: append the clicked asset into the scene at the 3D
        cursor. The asset identity lives on the clicked action item."""
        scene = context.scene
        action = None
        for msg in scene.mixie_chat_messages:
            if getattr(msg, "bubble_id", "") == self.bubble_id:
                for item in msg.action_items:
                    if item.value == self.action_value:
                        action = item
                        break
                break
        if action is None or not action.asset_name:
            self.report({'WARNING'}, "That asset is no longer available")
            return {'CANCELLED'}

        from ...core import library_browse
        ok, message = library_browse.add_asset_to_scene(
            context, action.library, action.blend_file,
            action.asset_name, action.asset_type,
        )
        if ok:
            self.report({'INFO'}, f"Added '{message}' to the scene")
            return {'FINISHED'}
        self.report({'WARNING'}, message)
        return {'CANCELLED'}

    def _advance_batched_choice(self, scene):
        """Advance a batch locally, returning None when this is a normal action."""
        from ...core import batched_choice

        bubble = next(
            (msg for msg in scene.mixie_chat_messages
             if getattr(msg, 'bubble_id', '') == self.bubble_id),
            None,
        )
        if bubble is None:
            return None
        step = batched_choice.record_choice(bubble, self.action_value)
        if step is None:
            return None

        if step["status"] == "stale":
            # Already answered and submitted — swallow so a button left on
            # screen by a re-delivered event cannot fire a stray single answer.
            return {'handled': True}

        if step["status"] == "advanced":
            # Draw the next card through the normal slot pipeline so it is
            # identical to a backend-sent one — a bare bubble.content write
            # leaves the old question rendered (stale markdown segments and
            # layout cache) and the wizard appears frozen.
            batched_choice.render_question(self.bubble_id, step["question"], scene)
            return {'handled': True}

        # The batch is complete. Submit exactly once, carrying its original
        # interrupt id so parallel pending prompts cannot be resumed by mistake.
        from ...constants import SessionState
        from ...core.queue_processor import queue_sse_event, queue_sse_error, queue_sse_complete
        from ...core.sse_handler import create_sse_handler
        from mixar.config.config import get_server_url
        from ...core import get_session_manager
        session = get_session_manager()
        try:
            from mixar.modules.auth.core.auth import get_access_token
            auth_token = get_access_token() or ''
        except Exception:
            auth_token = ''
        target_scene_name = scene.name
        handler = create_sse_handler(
            scene_name=target_scene_name,
            host=get_server_url(),
            on_event=lambda event: queue_sse_event(event, target_scene_name),
            on_error=lambda error: queue_sse_error(error, target_scene_name),
            on_complete=lambda: queue_sse_complete(target_scene_name),
        )
        if handler.start_input_stream(
            session_id=session.get_session_id(scene),
            action='submit',
            answers=step["answers"],
            interrupt_id=getattr(bubble, 'interrupt_id', '') or None,
            auth_token=auth_token,
        ):
            # Replace the last card with the answer recap (and drop the
            # buttons) so the transcript keeps what was chosen, the way the
            # single-choice flow echoes the clicked label.
            parsed = batched_choice.parse_batch(bubble)
            batched_choice.render_summary(
                self.bubble_id,
                parsed[0] if parsed else [],
                step["answers"],
                scene,
            )
            session.set_state(scene, SessionState.BUSY)
            session.clear_streaming()
        else:
            # The final answer was recorded before the network call. Leaving
            # it recorded would make the batch read fully-answered — every
            # later click swallowed as stale — while the interrupt is still
            # pending backend-side. Roll it back and put its card up again so
            # the final click can simply be retried.
            batched_choice.rollback_answer(bubble, step["answered"])
            batched_choice.render_question(self.bubble_id, step["answered"], scene)
            self.report({'ERROR'}, 'Failed to submit choices')
        return {'handled': True}

    def _apply_model_choice(self, context):
        """Handle a chat_model:<service>:<slug> button click locally."""
        from .generate_ops import normalize_generate_service

        scene = context.scene
        try:
            _, service_key, slug = self.action_value.split(":", 2)
        except ValueError:
            logger.warning("Malformed model choice value: %r", self.action_value)
            return {'CANCELLED'}

        current = normalize_generate_service(
            getattr(scene, 'mixie_chat_generate_type', ''))
        if service_key != current:
            # Stale ask from a previously selected type — don't cross wires.
            self.report(
                {'INFO'},
                "That model belongs to a different generate type — "
                "pick the type again to choose its model.",
            )
            return {'CANCELLED'}

        scene.mixie_chat_generate_model = slug

        # Clear the ask bubble's buttons and confirm the choice.
        label = slug
        try:
            from mixar.bootstrap.chat_generate_options_cache import (
                get_display_label,
                get_option,
            )
            option = get_option(service_key) or {}
            for model in option.get("models") or []:
                if model.get("slug") == slug:
                    label = model.get("label") or slug
                    break
            service_label = get_display_label(service_key)
        except Exception:
            service_label = service_key
        for msg in scene.mixie_chat_messages:
            if getattr(msg, 'bubble_id', "") == self.bubble_id:
                msg.action_items.clear()
                break

        confirm = scene.mixie_chat_messages.add()
        confirm.sender = 'AGENT'
        confirm.text = f"Got it — I'll use {label} for {service_label}."
        redraw_chat_areas()
        return {'FINISHED'}


class MIXIE_CHAT_OT_insert_prompt_text(Operator):
    """Insert prompt text into chat input and auto-submit"""
    bl_idname = "mixie_chat.insert_prompt_text"
    bl_label = "Insert Prompt Text"
    bl_options = {'REGISTER', 'INTERNAL'}

    text: StringProperty(
        name="Text",
        description="The prompt text to insert into the chat input",
        default="",
    )

    mode: StringProperty(
        name="Mode",
        description="The chat mode to switch to (AGENT, GENERATE)",
        default="",
    )

    generate_type: StringProperty(
        name="Generate Type",
        description="The generate sub-type — a generation-catalog service "
                    "key (e.g. image_gen, model_3d)",
        default="",
    )

    def execute(self, context):
        if not self.text:
            return {'CANCELLED'}

        # Set the chat mode if provided. LIBRARY is deliberately absent —
        # the mode is retired, so a quick prompt must not be able to put the
        # user into a mode the dropdown no longer offers.
        if self.mode and self.mode in {'AGENT', 'GENERATE'}:
            context.scene.mixie_chat_mode = self.mode

        # Set the generate type if provided (only applies when mode is
        # GENERATE). Legacy identifiers are mapped to service keys; the
        # enum is catalog-driven, so validate by attempting the assignment
        # — an identifier missing from the current options raises
        # TypeError and we keep the current selection.
        if self.generate_type:
            from .generate_ops import normalize_generate_service
            generate_type = normalize_generate_service(self.generate_type)
            try:
                context.scene.mixie_chat_generate_type = generate_type
            except TypeError:
                logger.warning(
                    "Unknown generate type %r — keeping current selection",
                    self.generate_type,
                )

        # Set the chat input to the prompt text
        context.scene.mixie_chat_input = self.text

        # Auto-submit: defer send to timer (same mechanism as Enter key submit)
        bpy.app.timers.register(
            lambda: _deferred_send_message() or None,
            first_interval=0.01,
        )

        redraw_chat_areas()

        logger.debug(f"Inserted and submitting: {self.text[:50]}... mode={self.mode}")
        return {'FINISHED'}


class MIXIE_CHAT_OT_toggle_plan_mode(Operator):
    """Plan Mode enables extensive thinking for the agent. This also lets you review and modify the plan before the agent executes it"""
    bl_idname = "mixie_chat.toggle_plan_mode"
    bl_label = "Toggle Plan Mode"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        scene.mixie_chat_plan_enabled = not scene.mixie_chat_plan_enabled

        for area in context.screen.areas:
            if area.type == 'MIXIE_CHAT':
                area.tag_redraw()
        return {'FINISHED'}


class MIXIE_CHAT_OT_set_feedback_rating(Operator):
    """Set star rating for an agent response"""
    bl_idname = "mixie_chat.set_feedback_rating"
    bl_label = "Rate Response"
    bl_options = {'REGISTER', 'INTERNAL'}

    bubble_id: StringProperty(
        name="Bubble ID",
        description="ID of the message bubble to rate",
        default="",
    )
    rating: IntProperty(
        name="Rating",
        description="Star rating (1-5)",
        default=0,
        min=1,
        max=5,
    )

    def execute(self, context):
        scene = context.scene
        bubble_id = self.bubble_id
        rating = self.rating
        for msg in scene.mixie_chat_messages:
            bid = getattr(msg, 'bubble_id', '')
            if bid and bid == bubble_id:
                # Submitted feedback is locked — no revisions once a rating
                # is in flight or accepted (only idle/failed accept clicks).
                if msg.feedback_status in (
                    FEEDBACK_STATUS_SENDING,
                    FEEDBACK_STATUS_RECEIVED,
                ):
                    logger.info(
                        f"Feedback rating ignored (locked): "
                        f"bubble_id={bubble_id}"
                    )
                    return {'CANCELLED'}
                msg.feedback_rating = rating
                logger.info(
                    f"Feedback rating set: bubble_id={bubble_id}, "
                    f"rating={rating}"
                )
                def _complete(success: bool) -> None:
                    current = _find_feedback_message(scene, bubble_id)
                    if (
                        current is None
                        or current.feedback_comment_submitting
                        or current.feedback_status != FEEDBACK_STATUS_SENDING
                    ):
                        # A newer comment submission owns the visible state.
                        return
                    current.feedback_status = (
                        FEEDBACK_STATUS_RECEIVED
                        if success else FEEDBACK_STATUS_FAILED
                    )
                    _bump_layout_epoch(scene)
                    redraw_chat_areas()

                queued = _post_feedback_async(
                    scene,
                    {
                        "bubble_id": bubble_id,
                        "rating": rating,
                    },
                    on_complete=_complete,
                )
                if queued:
                    msg.feedback_status = FEEDBACK_STATUS_SENDING
                else:
                    msg.feedback_status = FEEDBACK_STATUS_FAILED
                # Open the comment field right away so text feedback is
                # discoverable — there is no separate toggle to find.
                if not msg.feedback_comment_submitting:
                    msg.feedback_comment_expanded = True
                _bump_layout_epoch(scene)
                redraw_chat_areas()
                return {'FINISHED'}

        logger.warning(f"Feedback: bubble_id '{bubble_id}' not found")
        return {'CANCELLED'}

class MIXIE_CHAT_OT_toggle_feedback_comment(Operator):
    """Toggle inline comment field for feedback"""
    bl_idname = "mixie_chat.toggle_feedback_comment"
    bl_label = "Toggle Comment"
    bl_options = {'REGISTER', 'INTERNAL'}

    bubble_id: StringProperty(name="Bubble ID", default="")

    def execute(self, context):
        scene = context.scene
        for msg in scene.mixie_chat_messages:
            bid = getattr(msg, 'bubble_id', '')
            if bid and bid == self.bubble_id:
                was_expanded = msg.feedback_comment_expanded
                # Auto-submit on collapse if comment is non-empty
                if was_expanded and msg.feedback_comment.strip():
                    queued, error = _queue_feedback_comment(scene, msg)
                    if not queued:
                        self.report({'WARNING'}, error)
                        msg.feedback_comment_expanded = True
                        redraw_chat_areas()
                        return {'CANCELLED'}
                else:
                    msg.feedback_comment_expanded = not was_expanded
                    _bump_layout_epoch(scene)
                redraw_chat_areas()
                return {'FINISHED'}

        logger.warning(f"Toggle comment: bubble_id '{self.bubble_id}' not found")
        return {'CANCELLED'}


class MIXIE_CHAT_OT_submit_feedback_comment(Operator):
    """Submit feedback comment"""
    bl_idname = "mixie_chat.submit_feedback_comment"
    bl_label = "Submit Comment"
    bl_options = {'REGISTER', 'INTERNAL'}

    bubble_id: StringProperty(name="Bubble ID", default="")

    def execute(self, context):
        scene = context.scene
        for msg in scene.mixie_chat_messages:
            bid = getattr(msg, 'bubble_id', '')
            if bid and bid == self.bubble_id:
                if not msg.feedback_comment.strip():
                    msg.feedback_comment_expanded = False
                    _bump_layout_epoch(scene)
                    redraw_chat_areas()
                    return {'FINISHED'}
                queued, error = _queue_feedback_comment(scene, msg)
                if not queued:
                    self.report({'WARNING'}, error)
                    msg.feedback_comment_expanded = True
                    redraw_chat_areas()
                    return {'CANCELLED'}
                redraw_chat_areas()
                return {'FINISHED'}

        logger.warning(f"Feedback comment: bubble_id '{self.bubble_id}' not found")
        return {'CANCELLED'}

class MIXIE_CHAT_OT_cancel_generation(Operator):
    """Cancel the active generation"""
    bl_idname = "mixie_chat.cancel_generation"
    bl_label = "Cancel Generation"
    bl_description = "Stop the current generation"
    bl_options = {'REGISTER', 'INTERNAL'}

    # Map of generate type (catalog service key) -> (is_generating attr,
    # error attr). Keep in sync with the footer's spinner map in
    # mixie_chat_footer.cc and generate_ops routing.
    _GEN_FLAGS = {
        'depth_to_image':       ('mixie_lookdev_is_generating',       'mixie_lookdev_error'),
        'pbr_gen':              ('mixie_lookdev360_is_generating',    'mixie_lookdev360_error'),
        'model_3d':             ('mixie_image_to_3d_is_generating',   'mixie_image_to_3d_error'),
        'image_to_3d':          ('mixie_image_to_3d_is_generating',   'mixie_image_to_3d_error'),
        'hunyuan_rapid':        ('mixie_hunyuan_rapid_is_generating', 'mixie_hunyuan_rapid_error'),
        'image_gen':            ('mixie_imagegen_is_generating',      'mixie_imagegen_error'),
        'scene_reconstruction': ('mixie_scene_recon_is_generating',   'mixie_scene_recon_error'),
    }

    def execute(self, context):
        from .generate_ops import normalize_generate_service

        scene = context.scene
        gen_type = normalize_generate_service(
            getattr(scene, 'mixie_chat_generate_type', ''))

        # Cancel the specific generation type
        flag_info = self._GEN_FLAGS.get(gen_type)
        if flag_info:
            gen_attr, err_attr = flag_info
            if getattr(scene, gen_attr, False):
                setattr(scene, gen_attr, False)
                if hasattr(scene, err_attr):
                    setattr(scene, err_attr, "Cancelled by user")

        # Also reset progress
        try:
            from mixar.modules.moodboard.core.generate_progress import reset_progress
            progress_key = {
                'depth_to_image': 'lookdev',
                'pbr_gen': 'lookdev360',
                'model_3d': 'image_to_3d',
                'image_to_3d': 'image_to_3d',
                'hunyuan_rapid': 'hunyuan_rapid',
                'image_gen': 'imagegen',
                'scene_reconstruction': 'scene_recon',
            }.get(gen_type)
            if progress_key:
                reset_progress(progress_key)
        except Exception:
            pass

        # Redraw
        for area in context.screen.areas:
            if area.type in ('MIXIE_CHAT', 'MIXIE'):
                area.tag_redraw()

        return {'FINISHED'}


def _find_bubble(scene, bubble_id):
    """Linear scan for a message by bubble_id (mirrors slot_processor)."""
    for msg in scene.mixie_chat_messages:
        if getattr(msg, 'bubble_id', "") == bubble_id:
            return msg
    return None


class MIXIE_CHAT_OT_toggle_steps(Operator):
    """Collapse / expand the agent steps block"""
    bl_idname = "mixie_chat.toggle_steps"
    bl_label = "Toggle Steps Block"
    bl_options = {'REGISTER'}

    bubble_id: StringProperty(name="Bubble ID", default="")

    def execute(self, context):
        scene = context.scene
        msg = _find_bubble(scene, self.bubble_id)
        if msg is None:
            return {'CANCELLED'}
        msg.steps_collapsed = not msg.steps_collapsed
        _bump_layout_epoch(scene)
        redraw_chat_areas()
        return {'FINISHED'}


class MIXIE_CHAT_OT_toggle_step_row(Operator):
    """Expand / collapse a single step row's detail"""
    bl_idname = "mixie_chat.toggle_step_row"
    bl_label = "Toggle Step Row"
    bl_options = {'REGISTER'}

    bubble_id: StringProperty(name="Bubble ID", default="")
    item_id: StringProperty(name="Item ID", default="")

    def execute(self, context):
        scene = context.scene
        msg = _find_bubble(scene, self.bubble_id)
        if msg is None:
            return {'CANCELLED'}
        for row in msg.step_items:
            if row.item_id == self.item_id:
                row.expanded = not row.expanded
                _bump_layout_epoch(scene)
                redraw_chat_areas()
                return {'FINISHED'}
        return {'CANCELLED'}


class MIXIE_CHAT_OT_toggle_thinking(Operator):
    """Collapse / expand the finalized thinking dropdown"""
    bl_idname = "mixie_chat.toggle_thinking"
    bl_label = "Toggle Thinking"
    bl_options = {'REGISTER'}

    bubble_id: StringProperty(name="Bubble ID", default="")

    def execute(self, context):
        scene = context.scene
        msg = _find_bubble(scene, self.bubble_id)
        if msg is None:
            return {'CANCELLED'}
        msg.thinking_collapsed = not msg.thinking_collapsed
        _bump_layout_epoch(scene)
        redraw_chat_areas()
        return {'FINISHED'}


class MIXIE_CHAT_OT_dev_stream_demo(Operator):
    """Stream a scripted demo agent turn (thinking → plan → tools → answer).

    Dev/QA aid for evaluating the agent-output UI without a backend. Drives the
    real slot pipeline so what renders here matches live streaming.
    """
    bl_idname = "mixie_chat.dev_stream_demo"
    bl_label = "Dev: Stream Demo Turn"
    bl_options = {'REGISTER'}

    user_text: StringProperty(
        name="User Text",
        default="Make a woods scene with a cabin and an outdoor fireplace",
    )

    def execute(self, context):
        from ...core.dev_stream import start_demo_stream
        start_demo_stream(context.scene, self.user_text)
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_select_slot_action,
    MIXIE_CHAT_OT_insert_prompt_text,
    MIXIE_CHAT_OT_toggle_plan_mode,
    MIXIE_CHAT_OT_set_feedback_rating,
    MIXIE_CHAT_OT_toggle_feedback_comment,
    MIXIE_CHAT_OT_submit_feedback_comment,
    MIXIE_CHAT_OT_cancel_generation,
    MIXIE_CHAT_OT_toggle_steps,
    MIXIE_CHAT_OT_toggle_step_row,
    MIXIE_CHAT_OT_toggle_thinking,
    MIXIE_CHAT_OT_dev_stream_demo,
)
