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
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from mixar.config.logging_config import get_logger
from ...core.ui_utils import bump_layout_epoch, redraw_chat_areas
from .chat_slot_types import (
    MixieChatTodoItem,
    MixieChatActionItem,
    MixieChatImageItem,
    MixieChatStepItem,
)
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


def on_feedback_comment_changed(self, context):
    """Detect Enter key via \\x1F marker and submit the feedback comment."""
    if not self.feedback_comment.endswith("\x1F"):
        # Live typing (fires per keystroke via TEXTEDIT_UPDATE): the input
        # grows/shrinks with its wrapped line count — Shift+Enter inserts
        # real newlines — so the C++ layout must remeasure.
        if self.feedback_comment_expanded:
            scene = getattr(context, 'scene', None)
            if scene is not None:
                bump_layout_epoch(scene)
        return
    self.feedback_comment = self.feedback_comment.rstrip("\x1F")
    bubble_id = self.bubble_id
    if not bubble_id:
        return
    if not self.feedback_comment.strip():
        return
    if self.feedback_comment_submitting:
        return
    if not 1 <= int(self.feedback_rating) <= 5:
        logger.info(
            "Feedback comment kept open until a rating is selected: "
            f"bubble_id={bubble_id}"
        )
        return
    bpy.app.timers.register(
        lambda bid=bubble_id: _deferred_submit_feedback(bid) or None,
        first_interval=0.01,
    )


def _deferred_submit_feedback(bubble_id):
    """Submit feedback comment via operator (called from timer)."""
    try:
        bpy.ops.mixie_chat.submit_feedback_comment(bubble_id=bubble_id)
    except Exception:
        logger.warning(f"Failed to submit feedback comment for {bubble_id}", exc_info=True)


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
        description="Type of input expected: text, choice, approval, or file_save",
        default="",
        maxlen=32,
        options={'SKIP_SAVE'}
    )
    batched_questions: StringProperty(
        name="Batched Questions",
        description="Runtime JSON for a local multi-choice input wizard",
        default="",
        maxlen=16384,
        options={'SKIP_SAVE'},
    )
    batched_answers: StringProperty(
        name="Batched Answers",
        description="Runtime JSON answers collected by a local input wizard",
        default="",
        maxlen=16384,
        options={'SKIP_SAVE'},
    )
    interrupt_id: StringProperty(
        name="Interrupt ID",
        description="Checkpointed backend interrupt represented by this bubble",
        default="",
        maxlen=200,
        options={'SKIP_SAVE'},
    )
    export_format: StringProperty(default="", maxlen=8, options={'SKIP_SAVE'})
    export_scope: StringProperty(default="", maxlen=16, options={'SKIP_SAVE'})
    export_extension: StringProperty(default="", maxlen=8, options={'SKIP_SAVE'})
    export_suggested_filename: StringProperty(default="", maxlen=96, options={'SKIP_SAVE'})

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

    # -------------------------------------------------------------------------
    # Steps block (agent tool-call activity)
    # -------------------------------------------------------------------------
    step_items: CollectionProperty(
        type=MixieChatStepItem,
        name="Step Items",
        description="Tool-call rows shown in the collapsible steps block"
    )
    steps_summary: StringProperty(
        name="Steps Summary",
        description="One-line summary shown on the collapsed steps header",
        default="",
        maxlen=256
    )
    steps_collapsed: BoolProperty(
        name="Steps Collapsed",
        description="Whether the steps block is collapsed to its summary",
        default=True
    )

    # -------------------------------------------------------------------------
    # Thinking dropdown (finalized reasoning; live reasoning uses `ephemeral`)
    # -------------------------------------------------------------------------
    thinking_text: StringProperty(
        name="Thinking Text",
        description="Full reasoning text revealed when the dropdown is expanded",
        default="",
        maxlen=65536
    )
    thinking_active: BoolProperty(
        name="Thinking Active",
        description="True while reasoning streams live (uses ephemeral bubble)",
        default=False,
        options={'SKIP_SAVE'},
    )
    thinking_start_time: FloatProperty(
        name="Thinking Start Time",
        description="Wall-clock start of reasoning (seconds); used to compute duration",
        default=0.0,
        options={'SKIP_SAVE'},
    )
    thinking_duration_ms: IntProperty(
        name="Thinking Duration Ms",
        description="Total reasoning duration in milliseconds (for 'Thought for Ns')",
        default=0
    )
    thinking_collapsed: BoolProperty(
        name="Thinking Collapsed",
        description="Whether the finalized thinking dropdown is collapsed",
        default=True
    )

    # -------------------------------------------------------------------------
    # Feedback fields (post-response rating)
    # -------------------------------------------------------------------------
    feedback_visible: BoolProperty(
        name="Feedback Visible",
        description="Whether to show the feedback rating row",
        default=False,
        options={'SKIP_SAVE'},
    )
    feedback_rating: IntProperty(
        name="Feedback Rating",
        description="User's star rating (0=unrated, 1-5=rated)",
        default=0,
        min=0,
        max=5,
        options={'SKIP_SAVE'},
    )
    feedback_comment: StringProperty(
        name="Feedback Comment",
        description="User's feedback comment",
        default="",
        maxlen=2000,
        options={'SKIP_SAVE', 'TEXTEDIT_UPDATE'},
        update=on_feedback_comment_changed,
    )
    feedback_comment_expanded: BoolProperty(
        name="Feedback Comment Expanded",
        description="Whether the inline comment field is shown",
        default=False,
        options={'SKIP_SAVE'},
    )
    feedback_comment_submitting: BoolProperty(
        name="Feedback Comment Submitting",
        description="Whether this feedback comment has an in-flight request",
        default=False,
        options={'SKIP_SAVE'},
    )
    feedback_status: IntProperty(
        name="Feedback Status",
        description="Submission state: 0=idle, 1=sending, 2=received, 3=failed",
        default=0,
        min=0,
        max=3,
        options={'SKIP_SAVE'},
    )
    feedback_submitted_comment: StringProperty(
        name="Submitted Feedback Comment",
        description="Comment accepted by the server, shown read-only in the chat",
        default="",
        maxlen=2000,
        options={'SKIP_SAVE'},
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
        return

    # An emptied composer can't have an active @-mention token. Interactive
    # edits are handled by the C++ detection hooks; this covers programmatic
    # clears (send/new-session) so the dropdown never lingers.
    try:
        if not self.mixie_chat_input and self.mixie_chat_mention_show:
            self.mixie_chat_mention_show = False
    except AttributeError:
        pass  # mention props not registered (isolated tests)


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


# Keep a module-level reference to the last items list returned to Blender.
# bpy does NOT copy the strings out of a dynamic enum-items callback; without
# this anchor they can be garbage-collected while the UI still points at
# them (the classic dynamic-EnumProperty crash).
_generate_type_items_ref = []


def generate_type_enum_items(self, context):
    """Dynamic items for the Generate Type dropdowns.

    Identifiers are generation-catalog service keys, sourced from the
    backend's /generation-catalog/chat-options view. See
    chat_generate_options_cache.
    """
    global _generate_type_items_ref
    try:
        from mixar.bootstrap.chat_generate_options_cache import (
            get_generate_type_enum_items,
        )
        _generate_type_items_ref = get_generate_type_enum_items()
    except Exception:
        # Bootstrap unavailable: fail closed instead of reviving services that
        # may have been disabled by the backend.
        _generate_type_items_ref = [
            ("NONE", "No generation services", "Generation is currently unavailable", 'ERROR', 0)
        ]
    return _generate_type_items_ref


# Instruction message shown when a generate type that needs extra input is
# selected, keyed by catalog service key. Each entry is
# (message, satisfied) — the hint is only posted when satisfied(scene,
# context) is False, so users who already attached an image / typed a
# prompt aren't told to do what they've already done.


def _has_input_image(scene, context):
    """True when a pending attachment or a selected moodboard image is
    available as the generation's input image."""
    try:
        if len(scene.mixie_chat_pending_attachments) > 0:
            return True
    except Exception:
        pass
    try:
        from mixar.modules.moodboard.ui.sidebar_ui_helpers import (
            get_selected_moodboard_image,
        )
        return get_selected_moodboard_image(context) is not None
    except Exception:
        return False


def _has_prompt(scene, context):
    return bool((scene.mixie_chat_input or "").strip())


def _has_prompt_or_image(scene, context):
    return _has_prompt(scene, context) or _has_input_image(scene, context)


def _has_mesh_selection(scene, context):
    try:
        return any(obj.type == 'MESH' for obj in context.selected_objects)
    except Exception:
        return False


_GENERATE_TYPE_HINTS = {
    'depth_to_image': (
        "Enter a render prompt. Mixie will use the current scene's depth "
        "as the guide.",
        _has_prompt,
    ),
    'pbr_gen': (
        "Please enter your prompt and select the mesh objects in the "
        "3D viewport before hitting send.",
        lambda scene, context: (
            _has_prompt(scene, context) and _has_mesh_selection(scene, context)
        ),
    ),
    'model_3d': (
        "Attach a reference image or select one in the moodboard, then "
        "hit send. A prompt is optional.",
        _has_input_image,
    ),
    'image_to_3d': (
        "Attach a reference image or select one in the moodboard, then "
        "hit send. A prompt is optional.",
        _has_input_image,
    ),
    'hunyuan_rapid': (
        "Attach a reference image or enter a prompt, then hit send.",
        _has_prompt_or_image,
    ),
    'scene_reconstruction': (
        "Attach an image to reconstruct it into a 3D scene, or enter a "
        "prompt to generate one from a description. You can also combine both.",
        _has_prompt_or_image,
    ),
}


# bubble_id prefix for the "which model?" ask bubbles — the slot-action
# handler recognises clicks by the chat_model: action value, and new asks
# strip the buttons off older ask bubbles via this prefix.
MODEL_ASK_BUBBLE_PREFIX = "chat-model-ask-"


def _clear_stale_model_asks(scene):
    """Remove action buttons from previous model-ask bubbles so only the
    ask for the currently selected type is clickable."""
    for msg in scene.mixie_chat_messages:
        if (getattr(msg, 'bubble_id', "").startswith(MODEL_ASK_BUBBLE_PREFIX)
                and len(msg.action_items)):
            msg.action_items.clear()


def _ask_model_choice(scene, service_key):
    """Post a chat bubble asking which model to use for *service_key*.

    Only asks when the chat options cache lists more than one model for
    the service. Buttons carry ``chat_model:<service>:<slug>`` values,
    intercepted locally by MIXIE_CHAT_OT_select_slot_action; ignoring the
    ask keeps the service's default model.
    """
    try:
        from mixar.bootstrap.chat_generate_options_cache import (
            get_display_label,
            get_option,
        )
        option = get_option(service_key) or {}
    except Exception:
        return False
    models = option.get("models") or []
    if len(models) < 2:
        return False

    default_slug = option.get("default_model") or models[0].get("slug")
    default_label = next(
        (m.get("label") or m.get("slug") for m in models
         if m.get("slug") == default_slug),
        default_slug,
    )

    import uuid
    msg = scene.mixie_chat_messages.add()
    msg.sender = 'AGENT'
    msg.bubble_id = MODEL_ASK_BUBBLE_PREFIX + str(uuid.uuid4())
    msg.text = (
        f"Which model should I use for {get_display_label(service_key)}? "
        f"Tap one below — or just hit send to use {default_label}."
    )
    for model in models:
        slug = model.get("slug")
        if not slug:
            continue
        label = model.get("label") or slug
        item = msg.action_items.add()
        item.label = label
        item.value = f"chat_model:{service_key}:{slug}"
        item.style = 'PRIMARY' if slug == default_slug else 'DEFAULT'
    return True


def on_generate_type_changed(self, context):
    """Show an instruction message for types that still need input, and
    ask which model to use when the type has more than one."""
    scene = context.scene
    gen_type = scene.mixie_chat_generate_type

    # The model choice is per-type; switching types resets to the default
    # and retires any previous type's ask buttons (their values name the
    # old service and would be rejected on click anyway).
    try:
        scene.mixie_chat_generate_model = ""
        _clear_stale_model_asks(scene)
    except Exception:
        pass

    posted = False
    entry = _GENERATE_TYPE_HINTS.get(gen_type)
    if entry:
        hint, satisfied = entry
        show = True
        try:
            show = not satisfied(scene, context)
        except Exception:
            pass  # on any doubt, show the hint
        if show:
            msg = scene.mixie_chat_messages.add()
            msg.sender = 'AGENT'
            msg.text = hint
            posted = True

    try:
        posted = _ask_model_choice(scene, gen_type) or posted
    except Exception as e:
        logger.debug("Model-choice ask skipped: %s", e)

    if posted:
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
            # Value 2 belonged to the removed legacy ASK mode and can still be
            # persisted in old .blend files. Never reuse it: doing so would
            # silently turn those files into Add-on Project Mode on load.
            ('ADDON_PROJECT', "Add-on Project", "Build and maintain a linked multi-file Blender add-on", 'FILE_SCRIPT', 3),
        ],
        default='AGENT',
    )

    bpy.types.Scene.mixie_addon_project_id = StringProperty(
        name="Add-on Project ID",
        description="Opaque project identity; the local folder path is stored only on this machine",
        default="",
    )

    bpy.types.Scene.mixie_addon_project_name = StringProperty(
        name="Add-on Project Name",
        description="Cached display name for the locally linked add-on project",
        default="",
        options={'SKIP_SAVE'},
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

    bpy.types.Scene.mixie_chat_layout_epoch = IntProperty(
        name="Chat Layout Epoch",
        description="Bumped by collapse toggles to force a C++ layout rebuild",
        default=0,
        options={'SKIP_SAVE'},
    )

    # Tracks whether the user has engaged with the chat composer this
    # session. The C++ message renderer gates the "Hi I'm Mixie"
    # empty-state greeting on this so the greeting only shows for a
    # truly fresh chat. Without this, anything that grew the bubble
    # (attachment, moodboard sync, screenshot) could push the bubble
    # past the height threshold and pop the greeting back into view.
    # SKIP_SAVE — every Blender launch starts with the greeting
    # available; new_session resets it back to False.
    bpy.types.Scene.mixie_chat_user_has_engaged = BoolProperty(
        name="User Has Engaged",
        description="True once the user has sent a message or otherwise interacted",
        default=False,
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.mixie_chat_state = EnumProperty(
        name="Session State",
        description="Current agent session state for this scene",
        items=SESSION_STATE_ITEMS,
        default='OFFLINE',
        options={'SKIP_SAVE'},  # Never persist — always OFFLINE on startup
    )

    # Chat mode captured when the currently running turn started —
    # stamped by SessionManager.set_state on the inactive→active edge,
    # cleared when the turn ends. The agent viewport lock (halo + input
    # block) keys off THIS rather than the live mixie_chat_mode
    # dropdown: the dropdown stays editable mid-turn, so flipping it
    # (AGENT → ASK → AGENT) must not lift the lock while an agent turn
    # is still editing the scene, nor raise it for a running Ask turn.
    bpy.types.Scene.mixie_chat_active_turn_mode = StringProperty(
        name="Active Turn Mode",
        description="Chat mode the currently running turn was started in",
        default="",
        options={'SKIP_SAVE'},  # Never persist — turns don't survive a file load
    )

    bpy.types.Scene.mixie_chat_generate_type = EnumProperty(
        name="Generate Type",
        description="Type of content to generate",
        # Catalog-driven: identifiers are generation-catalog service keys
        # served by /generation-catalog/chat-options (first option is the
        # default). SKIP_SAVE because the option list can change between
        # sessions — a persisted enum int could silently point at a
        # different service after a catalog update.
        items=generate_type_enum_items,
        update=on_generate_type_changed,
        options={'SKIP_SAVE'},
    )

    # Model slug chosen via the in-chat "which model?" ask (see
    # _ask_model_choice / the chat_model: slot-action intercept). Empty
    # means "use the service's catalog default". Reset on every type
    # change; SKIP_SAVE so a stale choice never outlives the session.
    bpy.types.Scene.mixie_chat_generate_model = StringProperty(
        name="Generate Model",
        description="Model to use for the selected generate type "
                    "(empty = service default)",
        default="",
        maxlen=128,
        options={'SKIP_SAVE'},
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
            ('ADDON_PROJECT', "Add-on Project", "Work on the linked Blender add-on", 'FILE_SCRIPT', 3),
        ],
        default='AGENT',
    )

    # Quick prompt generate type (ephemeral, dialog-only). Same
    # catalog-driven items as scene.mixie_chat_generate_type so the two
    # enums always share identifiers (quick_prompt copies by identifier).
    bpy.types.WindowManager.mixie_chat_quick_prompt_generate_type = EnumProperty(
        name="Quick Prompt Generate Type",
        description="Generate type for quick prompt dialog",
        items=generate_type_enum_items,
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
        'mixie_chat_layout_epoch',
        'mixie_session_id', 'mixie_chat_credits', 'mixie_chat_user_id',
        'mixie_chat_model', 'mixie_chat_generate_type',
        'mixie_chat_generate_model', 'mixie_chat_plan_enabled',
        'mixie_chat_is_busy', 'mixie_chat_state', 'mixie_chat_active_turn_mode',
        'mixie_chat_mode', 'mixie_addon_project_id', 'mixie_addon_project_name',
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
