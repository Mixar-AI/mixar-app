# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Special Message Operators

Slot action button click handler.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from mixar.config.logging_config import get_logger

from ...core.ui_utils import bump_layout_epoch as _bump_layout_epoch
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)


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
            logger.warning("[SLOT ACTION] CANCELLED: Not connected to server")
            self.report({'WARNING'}, "Not connected to server. Please reconnect.")
            return {'CANCELLED'}

        logger.info(
            f"Slot action selected: bubble_id={self.bubble_id}, "
            f"value={self.action_value}"
        )

        scene = context.scene

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
                    self.report({'ERROR'}, "Failed to send action")

        except Exception as e:
            logger.error(f"Error dispatching slot action: {e}")
            self.report({'ERROR'}, f"Error: {e}")

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

        # Set the chat mode if provided
        if self.mode and self.mode in {'AGENT', 'GENERATE'}:
            context.scene.mixie_chat_mode = self.mode

        # Set the generate type if provided (only applies when mode is
        # GENERATE). The enum is catalog-driven, so validate by attempting
        # the assignment — an identifier missing from the current options
        # raises TypeError and we keep the current selection.
        if self.generate_type:
            try:
                context.scene.mixie_chat_generate_type = self.generate_type
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
        scene = context.scene
        gen_type = getattr(scene, 'mixie_chat_generate_type', '')

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
    MIXIE_CHAT_OT_cancel_generation,
    MIXIE_CHAT_OT_toggle_steps,
    MIXIE_CHAT_OT_toggle_step_row,
    MIXIE_CHAT_OT_toggle_thinking,
    MIXIE_CHAT_OT_dev_stream_demo,
)
