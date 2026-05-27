# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Properties

Property definitions for the Mixie Chat space.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from mixar.config.logging_config import get_logger
from ...core.ui_utils import redraw_chat_areas
from .chat_slot_types import MixieChatTodoItem, MixieChatActionItem, MixieChatImageItem
from ...constants import SESSION_STATE_ITEMS, CHAT_INPUT_MAXLEN

logger = get_logger(__name__)


# =============================================================================
# Legacy PropertyGroups (kept for backward compatibility during migration)
# =============================================================================

class MixieChatAttachment(PropertyGroup):
    """Property group for a chat image attachment"""
    image_path: StringProperty(
        name="Image Path",
        description="File path or blend image name",
        default="",
        subtype='FILE_PATH'
    )
    image_source: EnumProperty(
        name="Image Source",
        items=[
            ('FILE', "File", "Image from file system"),
            ('BLEND_DATA', "Blend Data", "Image from blend file")
        ],
        default='FILE'
    )
    display_name: StringProperty(
        name="Display Name",
        description="Display name for the attachment",
        default=""
    )
    # Marks attachments that were auto-added by the moodboard selection sync.
    # The sync code uses this flag to know which pending attachments it owns
    # — manually added FILE / BLEND_DATA attachments are never touched.
    # SKIP_SAVE because the moodboard selection drives this; persisting it
    # across save/load would just go stale.
    is_moodboard: BoolProperty(
        name="From Moodboard",
        description="True when this attachment is mirrored from a selected moodboard image",
        default=False,
        options={'SKIP_SAVE'},
    )


class MixieChatMessage(PropertyGroup):
    """Property group for a single chat message.

    Supports both legacy event-type rendering and new slot-based rendering.
    Slot-based fields (bubble_id, loader_*, content, ephemeral, *_items)
    take precedence when populated.
    """
    # -------------------------------------------------------------------------
    # Legacy fields (kept for backward compatibility during migration)
    # -------------------------------------------------------------------------
    sender: EnumProperty(
        name="Sender",
        items=[
            ('USER', "User", "Message from user"),
            ('AGENT', "Agent", "Message from AI agent")
        ],
        default='USER'
    )
    text: StringProperty(
        name="Text",
        description="Message content (DEPRECATED - use content slot)",
        default="",
        maxlen=65536
    )
    attachments: CollectionProperty(
        type=MixieChatAttachment,
        name="Attachments",
        description="Image attachments for this message (user uploads)"
    )
    message_type: EnumProperty(
        name="Message Type",
        items=[
            ('USER', 'User', 'User message'),
            ('AGENT', 'Agent', 'Agent response'),
            ('ASSISTANT', 'Assistant', 'Assistant message'),
            ('ERROR', 'Error', 'Error message'),
            ('PLAN', 'Plan', 'Generated plan'),
        ],
        default='USER'
    )
    metadata: StringProperty(
        name="Metadata",
        description="JSON metadata (DEPRECATED - use slot fields)",
        default="{}",
        maxlen=65536
    )

    # -------------------------------------------------------------------------
    # Slot-based fields (new architecture)
    # -------------------------------------------------------------------------

    # Bubble identifier for slot updates
    bubble_id: StringProperty(
        name="Bubble ID",
        description="Unique identifier for this message bubble",
        default=""
    )

    # Loader slot - animated loading indicator
    # SKIP_SAVE: all loader fields are ephemeral runtime state; if the app
    # crashes mid-request they must not persist into the .blend file or a
    # stale spinning bubble will appear on every subsequent startup.
    loader_visible: BoolProperty(
        name="Loader Visible",
        description="Whether to show the loading indicator",
        default=False,
        options={'SKIP_SAVE'},
    )
    loader_texts: StringProperty(
        name="Loader Texts",
        description="JSON array of rotating loader messages",
        default="[]",
        maxlen=2048,
        options={'SKIP_SAVE'},
    )
    loader_rotate_ms: IntProperty(
        name="Loader Rotate Ms",
        description="Milliseconds between loader text rotation",
        default=2000,
        min=100,
        options={'SKIP_SAVE'},
    )
    loader_current_index: IntProperty(
        name="Loader Current Index",
        description="Current index in loader_texts array",
        default=0,
        options={'SKIP_SAVE'},
    )
    loader_spinner_index: IntProperty(
        name="Loader Spinner Index",
        description="Current spinner animation frame (rotates at 0.5s)",
        default=0,
        options={'SKIP_SAVE'},
    )

    # Content slot - persistent message content (markdown)
    content: StringProperty(
        name="Content",
        description="Persistent message content (supports markdown)",
        default="",
        maxlen=65536
    )

    # Ephemeral slot - temporary content (cleared on completion, FIFO display)
    ephemeral: StringProperty(
        name="Ephemeral",
        description="Temporary content (thinking text, cleared on completion)",
        default="",
        maxlen=65536
    )

    # Input type slot - indicates what kind of input the agent expects
    input_type: StringProperty(
        name="Input Type",
        description="Type of input expected: 'text', 'choice', 'approval'",
        default="",
        maxlen=32,
        options={'SKIP_SAVE'}
    )

    # Collection slots
    todo_items: CollectionProperty(
        type=MixieChatTodoItem,
        name="Todo Items",
        description="Todo/step items with status indicators"
    )
    action_items: CollectionProperty(
        type=MixieChatActionItem,
        name="Action Items",
        description="Action buttons for user interaction"
    )
    image_items: CollectionProperty(
        type=MixieChatImageItem,
        name="Image Items",
        description="Image gallery items"
    )


classes = (
    MixieChatAttachment,
    MixieChatMessage,
)


def on_chat_input_changed(self, context):
    """Auto-submit when Enter is pressed (detected by \\x1F marker).

    The C++ interface_handlers.cc inserts a \\x1F marker into the text buffer
    when Enter is pressed (without Shift) on a text button with
    UI_BUT_TEXTEDIT_UPDATE flag in SPACE_MIXIE_CHAT. Shift+Enter inserts a
    real newline for multi-line input. This callback detects the marker and
    triggers submit. Focus loss does NOT insert the marker.
    """
    if self.mixie_chat_input.endswith("\x1F"):
        # Strip the submit marker and submit
        self.mixie_chat_input = self.mixie_chat_input.rstrip("\x1F")

        # Defer operator call to timer to avoid calling bpy.ops inside property update
        bpy.app.timers.register(
            lambda: _execute_send_message() or None,
            first_interval=0.001
        )


def _execute_send_message():
    """Execute send_message (called from timer to avoid calling bpy.ops in property update)."""
    try:
        if hasattr(bpy.ops.mixie_chat, 'send_message'):
            bpy.ops.mixie_chat.send_message()
    except Exception:
        pass  # Operator may not be available


def on_quick_prompt_input_changed(self, context):
    """Auto-submit quick prompt when Enter is pressed (detected by \\x1F marker).

    The C++ interface_handlers.cc inserts a \\x1F marker when Enter is
    pressed (without Shift) on this property. We detect it here and submit.
    """
    if hasattr(self, 'mixie_chat_quick_prompt_input'):
        quick_input = self.mixie_chat_quick_prompt_input
        if quick_input.endswith("\x1F"):
            # Strip submit marker
            self.mixie_chat_quick_prompt_input = quick_input.rstrip("\x1F")
            # Execute the quick prompt operator directly
            bpy.app.timers.register(
                lambda: _execute_quick_prompt() or None,
                first_interval=0.001
            )


def _execute_quick_prompt():
    """Execute quick prompt submission (called from timer to avoid callback issues)."""
    try:
        # Use EXEC_DEFAULT to call execute() directly without invoke()
        bpy.ops.mixie_chat.quick_prompt('EXEC_DEFAULT')
    except Exception:
        pass  # Operator may not be available


def on_generate_type_changed(self, context):
    """Show instruction message when Lookdev 360 or Image to 3D is selected."""
    scene = context.scene
    gen_type = scene.mixie_chat_generate_type

    if gen_type == 'LOOKDEV_360':
        # Add agent instruction message
        msg = scene.mixie_chat_messages.add()
        msg.sender = 'AGENT'
        msg.text = "Please enter your prompt and select the mesh objects in the 3D viewport before hitting send."
        # Trigger redraw
        redraw_chat_areas()

    elif gen_type == 'IMAGE_TO_3D':
        # Add agent instruction message
        msg = scene.mixie_chat_messages.add()
        msg.sender = 'AGENT'
        msg.text = "Attach a reference image or select one in the moodboard, then hit send. A prompt is optional."
        # Trigger redraw
        redraw_chat_areas()

    elif gen_type == 'SCENE_RECON':
        # Add agent instruction message
        msg = scene.mixie_chat_messages.add()
        msg.sender = 'AGENT'
        msg.text = "Attach an image to reconstruct it into a 3D scene, or enter a prompt to generate one from a description. You can also combine both."
        # Trigger redraw
        redraw_chat_areas()


def register():
    # Install undo/redo guard so chat messages persist through undo
    from ...core.undo_guard import register as register_undo_guard
    register_undo_guard()

    # Install load_pre handler to abort agent sessions on file open
    from ...core.file_handlers import register as register_file_handlers
    register_file_handlers()

    # Register slot type dependencies first (MixieChatMessage uses them in CollectionProperty)
    from .chat_slot_types import classes as slot_classes
    for cls in slot_classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass  # Already registered by bootstrap

    for cls in classes:
        bpy.utils.register_class(cls)

    # Scene-level properties
    bpy.types.Scene.mixie_chat_input = StringProperty(
        name="Chat Input",
        description="Type your message here",
        default="",
        maxlen=CHAT_INPUT_MAXLEN,
        options={'TEXTEDIT_UPDATE'},  # Triggers update callback on each keystroke
        update=on_chat_input_changed,  # Detects Enter key via \x1F marker
    )

    bpy.types.Scene.mixie_chat_messages = CollectionProperty(
        type=MixieChatMessage,
        name="Chat Messages",
        description="Collection of chat messages"
    )

    # Pending attachments are inherently ephemeral — they describe the
    # in-flight composer state, not a property of the saved scene.
    # Persisting them caused duplication on reload when combined with
    # moodboard sync (the rehydrated attachments lost their is_moodboard
    # flag and the next poll added a second copy of each) and orphan
    # moodboard attachments whose X-button no longer routed through
    # the moodboard deselect path. SKIP_SAVE makes the collection
    # start empty on every file load.
    bpy.types.Scene.mixie_chat_pending_attachments = CollectionProperty(
        type=MixieChatAttachment,
        name="Pending Attachments",
        description="Attachments for the message being composed",
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.mixie_chat_mode = EnumProperty(
        name="Chat Mode",
        description="Current chat interaction mode",
        items=[
            ('AGENT', "Agent", "AI agent for general tasks and assistance", 'AGENT', 0),
            ('GENERATE', "Generate", "Generate creative content (images, 3D models, textures)", 'GENERATE', 1),
            ('ASK', "Ask", "Ask questions and get answers", 'ASK', 2),
        ],
        default='AGENT',
    )

    bpy.types.Scene.mixie_chat_plan_enabled = BoolProperty(
        name="Plan Mode",
        description="When enabled, the agent creates a plan before executing. "
                    "When disabled, the agent executes directly",
        default=False,
    )

    bpy.types.Scene.mixie_chat_is_busy = BoolProperty(
        name="Mixie Is Busy",
        description="True when the agent is processing a request (BUSY state)",
        default=False,
        options={'SKIP_SAVE'},  # Never persist — always False on startup
    )

    bpy.types.Scene.mixie_chat_state = EnumProperty(
        name="Session State",
        description="Current agent session state for this scene",
        items=SESSION_STATE_ITEMS,
        default='OFFLINE',
        options={'SKIP_SAVE'},  # Never persist — always OFFLINE on startup
    )

    bpy.types.Scene.mixie_chat_generate_type = EnumProperty(
        name="Generate Type",
        description="Type of content to generate",
        items=[
            ('LOOKDEV', "Blockout to Render", "Generate images from scene depth map", 'SCENE_DATA', 0),
            ('LOOKDEV_360', "Generate PBR Maps", "Generate 360 textures for selected meshes", 'SPHERE', 1),
            ('IMAGE_TO_3D', "Image to 3D", "Generate 3D model from image", 'MESH_CUBE', 2),
            ('IMAGE_GEN', "Generate Image", "Generate AI images from prompt", 'IMAGE_DATA', 3),
            ('SCENE_RECON', "Generate Scene", "Generate 3D scene from text description", 'SCENE', 4),
        ],
        default='IMAGE_GEN',
        update=on_generate_type_changed,
    )

    bpy.types.Scene.mixie_chat_model = EnumProperty(
        name="Model",
        description="AI model to use for chat",
        items=[
            ('SONNET', "Sonnet", "Claude Sonnet 4.5 - Balanced performance"),
            ('OPUS', "Opus", "Claude Opus 4.5 - Most capable"),
            ('HAIKU', "Haiku", "Claude Haiku 4.0 - Fast and efficient"),
        ],
        default='SONNET',
    )

    # Login/Account properties
    bpy.types.Scene.mixie_chat_user_id = StringProperty(
        name="User ID",
        description="User ID for Mixie Chat login",
        default="",
        maxlen=256,
        options={'SKIP_SAVE'},  # Prevent leaking email in .blend files
    )

    # Security: password and login state on WindowManager (session-only, never saved to .blend)
    bpy.types.WindowManager.mixie_chat_password = StringProperty(
        name="Password",
        description="Password for Mixie Chat login",
        default="",
        maxlen=256,
        subtype='PASSWORD',
    )

    bpy.types.WindowManager.mixie_chat_is_logged_in = BoolProperty(
        name="Is Logged In",
        description="Whether user is currently logged in",
        default=False,
    )

    bpy.types.WindowManager.mixie_chat_is_logging_in = BoolProperty(
        name="Is Logging In",
        description="Whether login is in progress",
        default=False,
    )

    bpy.types.WindowManager.mixie_chat_login_error = StringProperty(
        name="Login Error",
        description="Last login error message",
        default="",
        maxlen=512,
    )

    bpy.types.WindowManager.mixie_chat_session_expired = BoolProperty(
        name="Session Expired",
        description="Session expired — re-login required",
        default=False,
    )

    bpy.types.Scene.mixie_chat_credits = IntProperty(
        name="Credits",
        description="Number of available credits",
        default=1000,  # Placeholder value
        min=0,
    )

    # Quick prompt input (WindowManager-level for popup dialog)
    # C++ interface_handlers.cc inserts newline when Enter is pressed on this property
    bpy.types.WindowManager.mixie_chat_quick_prompt_input = StringProperty(
        name="Quick Prompt",
        description="Quick prompt message input",
        default="",
        maxlen=CHAT_INPUT_MAXLEN,
        options={'TEXTEDIT_UPDATE'},
        update=on_quick_prompt_input_changed,
    )

    # Quick prompt mode selection (ephemeral, dialog-only)
    bpy.types.WindowManager.mixie_chat_quick_prompt_mode = EnumProperty(
        name="Quick Prompt Mode",
        description="Mode for quick prompt dialog",
        items=[
            ('AGENT', "Agent", "AI agent for general tasks", 'AGENT', 0),
            ('GENERATE', "Generate", "Generate content", 'GENERATE', 1),
            ('ASK', "Ask", "Ask questions", 'ASK', 2),
        ],
        default='AGENT',
    )

    # Quick prompt generate type (ephemeral, dialog-only)
    bpy.types.WindowManager.mixie_chat_quick_prompt_generate_type = EnumProperty(
        name="Quick Prompt Generate Type",
        description="Generate type for quick prompt dialog",
        items=[
            ('LOOKDEV', "Blockout to Render", "Generate from depth map", 'SCENE_DATA', 0),
            ('LOOKDEV_360', "Generate PBR Maps", "Generate 360 textures", 'SPHERE', 1),
            ('IMAGE_TO_3D', "Image to 3D", "3D from image", 'MESH_CUBE', 2),
            ('IMAGE_GEN', "Generate Image", "Generate AI images", 'IMAGE_DATA', 3),
            ('SCENE_RECON', "Generate Scene", "Generate 3D scene from text", 'SCENE', 4),
        ],
        default='IMAGE_GEN',
    )

    # WindowManager - unique per running Blender instance (ephemeral)
    bpy.types.WindowManager.mixie_instance_id = StringProperty(
        name="Instance ID",
        description="Unique identifier for this Blender instance (generated on launch)",
        default="",
    )

    # Scene - chat session ID (persists with blend file)
    bpy.types.Scene.mixie_session_id = StringProperty(
        name="Session ID",
        description="Chat session identifier for this scene",
        default="",
    )


def unregister():
    # Remove file load handler
    from ...core.file_handlers import unregister as unregister_file_handlers
    unregister_file_handlers()

    # Remove undo/redo guard
    from ...core.undo_guard import unregister as unregister_undo_guard
    unregister_undo_guard()

    # Stop all timers and background threads first to prevent crashes
    try:
        from ...core.animation_manager import cleanup as cleanup_animations
        cleanup_animations()
    except Exception:
        pass
    try:
        from ...core.sse_handler import cleanup_all_sse_handlers
        cleanup_all_sse_handlers()
    except Exception:
        pass
    try:
        from ..operators.chat_ops import cleanup_image_encoder
        cleanup_image_encoder()
    except Exception:
        pass

    # Clean up preview collection for thumbnails
    from ...core import cleanup_preview_collection
    cleanup_preview_collection()

    # Remove Scene-level properties
    for attr in (
        'mixie_session_id', 'mixie_chat_credits', 'mixie_chat_user_id',
        'mixie_chat_model', 'mixie_chat_generate_type', 'mixie_chat_plan_enabled',
        'mixie_chat_is_busy', 'mixie_chat_state', 'mixie_chat_mode',
        'mixie_chat_pending_attachments', 'mixie_chat_messages', 'mixie_chat_input',
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    # Remove WindowManager-level properties
    for attr in (
        'mixie_instance_id', 'mixie_chat_quick_prompt_generate_type',
        'mixie_chat_quick_prompt_mode', 'mixie_chat_quick_prompt_input',
        'mixie_chat_session_expired', 'mixie_chat_login_error',
        'mixie_chat_is_logging_in', 'mixie_chat_is_logged_in',
        'mixie_chat_password',
    ):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    from .chat_slot_types import classes as slot_classes
    for cls in reversed(slot_classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
