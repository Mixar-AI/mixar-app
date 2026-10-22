# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent, catalog-driven records for moodboard inference blocks."""

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Image, Object, PropertyGroup

from mixar.modules.moodboard.constants import (
    GRAPH_ACCEPTED_TYPES_MAXLEN,
    GRAPH_DESCRIPTION_MAXLEN,
    GRAPH_ERROR_MAXLEN,
    GRAPH_JOB_ID_MAXLEN,
    GRAPH_LABEL_MAXLEN,
    GRAPH_MODEL_SLUG_MAXLEN,
    GRAPH_NODE_ID_MAXLEN,
    GRAPH_PROGRESS_MAXLEN,
    GRAPH_PROMPT_MAXLEN,
    GRAPH_OBJECT_NAMES_MAXLEN,
    GRAPH_SERVICE_KEY_MAXLEN,
    GRAPH_SOCKET_ID_MAXLEN,
    GRAPH_WIDGET_MAXLEN,
)
from mixar.modules.moodboard.ui.moodboard_graph_param_callbacks import (
    _clamp_parameter_value,  # noqa: F401  (re-exported for back-compat)
    _enum_label_from_choices,
    _parameter_changed,
    _parameter_enum_items,
)


from ..core.node_action_types import ACTION_TYPES  # noqa: F401 (public re-export)

# Mesh -> mesh continuations. Schema and execution must share this set.
MESH_FEATURE_ACTIONS = frozenset(
    {'PBR_GEN', 'RETOPOLOGY', 'MESH_SEGMENT', 'AUTO_RIG', 'ANIMATE'}
)

ACTION_STATES = (
    ('DRAFT', "Draft", "Configure this node before running it"),
    ('QUEUED', "Queued", "Waiting for generation"),
    ('RUNNING', "Running", "Generation is running"),
    ('SUCCESS', "Complete", "Generation completed"),
    ('FAILED', "Failed", "Generation failed"),
    ('CANCELLED', "Cancelled", "Generation was cancelled"),
)


_MESH_FEATURE_CAPABILITY = {
    'PBR_GEN': "pbr_generation",
    'RETOPOLOGY': "retopology",
    'MESH_SEGMENT': "mesh_segmentation",
    'AUTO_RIG': "animate",
    # Retarget is its own capability so a shipped Auto Rig card never lists
    # it as a second mode.
    'ANIMATE': "animation",
}


def capability_for_action(action_type: str) -> str:
    if action_type == 'ASSEMBLE':
        return None
    if action_type in {'IMAGE_GEN', 'MASK_DETAIL'}:
        return "image_gen"
    if action_type == 'VIDEO_GEN':
        return "video_gen"
    if action_type == 'VIDEO_UPSCALE':
        return "video_upscale"
    if action_type == 'WORLD_LABS':
        return "world_labs"
    if action_type == 'CHARACTER_PARTS':
        return "character_parts"
    if action_type in _MESH_FEATURE_CAPABILITY:
        return _MESH_FEATURE_CAPABILITY[action_type]
    return "model_gen"


# The Mode / Model dropdown callbacks live beside this file (500-line rule);
# node_schema and the tests reach them through this module's names.
from .moodboard_graph_dropdowns import (  # noqa: F401  (re-exported)
    _model_changed,
    _model_items,
    _service_changed,
    _service_items,
    refresh_node_dropdown_labels,
    suppress_enum_mirror,
)


class MixieMoodboardChoice(PropertyGroup):
    """One tickable row of a multi-select (``ARRAY``) parameter.

    Saved with the card, unlike the sidebar engine's transient rows
    (``generation_params.core.multi_select``), which share this shape.
    """

    value: StringProperty(name="Value", default="")
    label: StringProperty(name="Label", default="", maxlen=GRAPH_LABEL_MAXLEN)
    # Optional partition the owner's ``choice_filter`` narrows the list to.
    group: StringProperty(name="Group", default="", maxlen=GRAPH_LABEL_MAXLEN)
    selected: BoolProperty(name="Selected", default=False)


class MixieMoodboardNodeParameter(PropertyGroup):
    """One per-node value projected from a catalog parameter schema."""

    # Every string below that C++ reads into a fixed stack buffer carries a
    # ``maxlen`` strictly smaller than that buffer. See the buffer sizes in
    # ``mixie_draw_moodboard_node_ui.cc`` and ``mixie_moodboard_graph_geometry.cc``.
    # No maxlen: this is the backend payload key, not something C++ reads.
    name: StringProperty(name="Parameter ID", default="")
    label: StringProperty(name="Label", default="", maxlen=GRAPH_LABEL_MAXLEN)
    description: StringProperty(name="Description", default="", maxlen=GRAPH_DESCRIPTION_MAXLEN)
    parameter_type: EnumProperty(
        name="Type",
        items=(
            ('STRING', "Text", "String value"),
            ('INTEGER', "Integer", "Whole-number value"),
            ('FLOAT', "Number", "Floating-point value"),
            ('BOOLEAN', "Toggle", "Boolean value"),
            ('ENUM', "Choice", "Catalog choice"),
            ('ARRAY', "Choices", "Any number of catalog choices, sent as a list"),
        ),
        default='STRING',
    )
    widget: StringProperty(name="Widget", default="text", maxlen=GRAPH_WIDGET_MAXLEN)
    group: StringProperty(name="Group", default="", maxlen=GRAPH_LABEL_MAXLEN)
    choices_json: StringProperty(name="Choices", default="[]")
    visible_if_json: StringProperty(name="Visibility Condition", default="{}")
    visible: BoolProperty(name="Visible", default=True)
    required: BoolProperty(name="Required", default=False)
    order: IntProperty(name="Order", default=0)
    minimum: FloatProperty(name="Minimum", default=-1.0e18)
    maximum: FloatProperty(name="Maximum", default=1.0e18)
    value_string: StringProperty(name="Value", default="", update=_parameter_changed)
    value_integer: IntProperty(name="Value", default=0, update=_parameter_changed)
    value_float: FloatProperty(name="Value", default=0.0, update=_parameter_changed)
    value_boolean: BoolProperty(name="Value", default=False, update=_parameter_changed)
    value_enum: EnumProperty(
        name="Value", items=_parameter_enum_items, update=_parameter_changed
    )
    # Human label of the current enum value, cached for the C++ node overlay:
    # dynamic enums don't reliably self-display (see refresh_node_dropdown_labels).
    value_label: StringProperty(name="Value Label", default="", maxlen=GRAPH_LABEL_MAXLEN)
    # ARRAY only: the tickable rows (the value is the ticked ones, in order),
    # the list widget's active row, and the row group the list is narrowed to
    # ("" = every row) — written by the owning card's own code, never a draw.
    choices: CollectionProperty(type=MixieMoodboardChoice)
    active_choice: IntProperty(name="Active Choice", default=0, options={'SKIP_SAVE'})
    choice_filter: StringProperty(name="Choice Filter", default="", maxlen=GRAPH_LABEL_MAXLEN)


class MixieMoodboardInputSocket(PropertyGroup):
    """One bounded slot from a backend-defined media input group."""

    socket_id: StringProperty(name="Socket ID", default="", maxlen=GRAPH_SOCKET_ID_MAXLEN)
    label: StringProperty(name="Label", default="", maxlen=GRAPH_LABEL_MAXLEN)
    accepted_types: StringProperty(
        name="Accepted Types", default="", maxlen=GRAPH_ACCEPTED_TYPES_MAXLEN
    )
    required: BoolProperty(name="Required", default=False)
    group_id: StringProperty(name="Input Group", default="", maxlen=GRAPH_SOCKET_ID_MAXLEN)
    repeatable: BoolProperty(name="Repeatable", default=False)
    visible: BoolProperty(name="Visible", default=True)


class MixieMoodboardActionNode(PropertyGroup):
    """One configurable inference block on the moodboard canvas."""

    node_id: StringProperty(name="Node ID", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    # Canvas frame membership -- a frame holds cards as readily as pictures.
    frame_id: StringProperty(name="Frame ID", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    action_type: EnumProperty(
        name="Action",
        items=ACTION_TYPES,
        default='IMAGE_GEN',
    )
    position_x: FloatProperty(name="Position X", default=0.0)
    position_y: FloatProperty(name="Position Y", default=0.0)
    width: FloatProperty(name="Width", default=700.0, min=140.0, max=1400.0)
    height: FloatProperty(name="Height", default=560.0, min=140.0, max=1400.0)
    selected: BoolProperty(name="Selected", default=False)
    # Pure UI state, toggled by the floating Edit button on a finished card.
    # A completed node shows its RESULT: the settings panel and the in-tile
    # prompt are folded away until this is on. Deliberately not a state change
    # -- the older "Edit & Run Again" reset `state` to DRAFT to make the prompt
    # reappear, which threw away the node's real outcome (and its error) just to
    # open an editor.
    edit_mode: BoolProperty(
        name="Edit Mode",
        description="Show this node's settings and prompt over its result",
        default=False,
    )
    # Shown in the card header. Empty means "use the action type's own name",
    # which is what makes an unnamed card still identifiable at a glance.
    label: StringProperty(
        name="Name",
        description="Name shown in this node's header; blank uses the node type",
        default="",
        maxlen=GRAPH_LABEL_MAXLEN,
    )
    # Live queue state for the header's right side ("Queued (#3)", "0:42").
    # Written by the pulse timer in node_job_bridge, never from a draw callback.
    progress_text: StringProperty(
        name="Progress", default="", maxlen=GRAPH_PROGRESS_MAXLEN
    )
    prompt: StringProperty(name="Prompt", default="", maxlen=GRAPH_PROMPT_MAXLEN)
    # Refine / Revert state for the in-tile prompt. On the node, not in a
    # Python dict, because the card is painted in C++: the draw pass reads
    # these to choose between Refine, Revert and a disabled button, and it
    # cannot consult module state to do it.
    #
    # SKIP_SAVE on all three: what the user typed before a refinement is a
    # this-session affordance, and a .blend that reopened offering to
    # "revert" a prompt to something from a previous session would be
    # presenting a stale edit as an undo. An interrupted refinement likewise
    # must not reload as permanently in-flight.
    prompt_pre_refine: StringProperty(
        name="Prompt Before Refine",
        default="",
        maxlen=GRAPH_PROMPT_MAXLEN,
        options={'SKIP_SAVE'},
    )
    # Distinct from a non-empty prompt_pre_refine: a user may legitimately
    # revert TO an empty prompt, and "" must not read as "nothing to revert".
    prompt_refined: BoolProperty(
        name="Prompt Refined",
        description="This node's prompt was refined and can be reverted",
        default=False,
        options={'SKIP_SAVE'},
    )
    prompt_refining: BoolProperty(
        name="Refining Prompt",
        description="A prompt refinement is in flight for this node",
        default=False,
        options={'SKIP_SAVE'},
    )
    # MASK_DETAIL in-node controls, drawn vertically inside the node card by the
    # C++ layout. Real node props so each mask node is independent; catalog image
    # params come from the node's own `parameters` collection.
    views_per_component: IntProperty(
        name="Views per Component",
        description="Number of distinct detail views generated for this mask",
        default=3,
        min=1,
        max=4,
    )
    include_full_context: BoolProperty(
        name="Use Full Character Context",
        description=(
            "Also send the full source image for design context; off by default "
            "so strict cutout-only guidance adheres to the mask more closely"
        ),
        default=False,
    )
    # The dropdowns below are display state, never the source of truth.
    # Blender stores a dynamic ``EnumProperty`` as an index into whatever the
    # ``items`` callback returned, so its meaning drifts: a catalog reorder
    # repoints a saved node at a different service or model, and a file opened
    # before the 2s-delayed catalog fetch lands resolves against the LOADING
    # placeholder. (``SKIP_SAVE`` would NOT help — it only suppresses
    # operator-repeat and presets, not .blend persistence.) So the slugs are
    # saved separately and are what every consumer reads via
    # ``node_schema.node_service_key`` / ``node_model_slug``; the enums are
    # re-derived from them by ``restore_node_selection`` once the catalog loads.
    service_key: EnumProperty(
        name="Mode",
        description="Generation service supplied by the backend catalog",
        items=_service_items,
        update=_service_changed,
    )
    service_key_id: StringProperty(
        name="Service Key",
        description="Saved catalog service slug backing the Mode dropdown",
        default="",
        maxlen=GRAPH_SERVICE_KEY_MAXLEN,
    )
    # Human labels of the current Mode/Model, cached for the C++ node overlay
    # because the dynamic enums above don't reliably self-display.
    service_label: StringProperty(name="Mode Label", default="", maxlen=GRAPH_LABEL_MAXLEN)
    model_label: StringProperty(name="Model Label", default="", maxlen=GRAPH_LABEL_MAXLEN)
    show_mode: BoolProperty(
        name="Show Mode",
        description="The backend capability currently exposes multiple moodboard services",
        default=True,
    )
    show_prompt: BoolProperty(
        name="Show Prompt",
        description="This node type takes a text prompt",
        default=True,
    )
    requires_reference: BoolProperty(
        name="Requires Reference", default=False,
        description="Refuse to generate without a connected reference image",
    )
    model: EnumProperty(
        name="Model",
        description="Generation model supplied by the backend catalog",
        items=_model_items,
        update=_model_changed,
    )
    model_slug: StringProperty(
        name="Model Slug",
        description="Saved catalog model slug backing the Model dropdown",
        default="",
        maxlen=GRAPH_MODEL_SLUG_MAXLEN,
    )
    schema_json: StringProperty(
        name="Node Schema",
        description="Catalog schema used to build this node's controls",
        default="{}",
    )
    input_sockets: CollectionProperty(type=MixieMoodboardInputSocket)
    parameters: CollectionProperty(type=MixieMoodboardNodeParameter)
    params_json: StringProperty(
        name="Parameters",
        description="Parameters snapshotted when this node was last run",
        default="{}",
    )
    state: EnumProperty(name="State", items=ACTION_STATES, default='DRAFT')
    job_id: StringProperty(
        name="Queue Job ID", default="", maxlen=GRAPH_JOB_ID_MAXLEN, options={'SKIP_SAVE'}
    )
    error: StringProperty(
        name="Error", default="", maxlen=GRAPH_ERROR_MAXLEN, options={'SKIP_SAVE'}
    )
    result_names: StringProperty(
        name="Results", default="", maxlen=GRAPH_OBJECT_NAMES_MAXLEN
    )
    # MASK_DETAIL nodes only: the stable id of the source-image SAM3 segment
    # (component) this node details. The source image itself is resolved through
    # the node's incoming link; this id pins the exact mask on that source.
    component_id: StringProperty(
        name="Component ID", default="", maxlen=GRAPH_NODE_ID_MAXLEN
    )
    preview_image: PointerProperty(name="Media Preview", type=Image)
    # MASK_DETAIL only: the masked-cutout thumbnail shown at the bottom of the
    # node card before generation (preview_image holds the result afterwards).
    mask_preview: PointerProperty(name="Mask Preview", type=Image)
    preview_object: PointerProperty(name="3D Preview", type=Object)


class MixieMoodboardAssetNode(PropertyGroup):
    """Live mesh reference, or a legacy generated asset resolved by object name."""

    node_id: StringProperty(name="Node ID", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    # Canvas frame membership -- a frame holds cards as readily as pictures.
    frame_id: StringProperty(name="Frame ID", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    title: StringProperty(name="Title", default="3D Asset", maxlen=GRAPH_LABEL_MAXLEN)
    object_names: StringProperty(
        name="Object Names", default="", maxlen=GRAPH_OBJECT_NAMES_MAXLEN
    )
    scene_mesh_reference: BoolProperty(
        name="Scene Mesh Reference", default=False,
        description="Use the live object pointer; a removed source must not bind by name",
    )
    preview_object: PointerProperty(name="3D Preview", type=Object)
    position_x: FloatProperty(name="Position X", default=0.0)
    position_y: FloatProperty(name="Position Y", default=0.0)
    # Image-node-sized so 3D result nodes read consistently on the canvas.
    width: FloatProperty(name="Width", default=700.0, min=140.0, max=1400.0)
    height: FloatProperty(name="Height", default=700.0, min=140.0, max=1400.0)
    selected: BoolProperty(name="Selected", default=False)


class MixieMoodboardLink(PropertyGroup):
    """Stable-ID connection between two moodboard nodes."""

    link_id: StringProperty(name="Link ID", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    from_node_id: StringProperty(name="From Node", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    from_socket: StringProperty(
        name="From Socket", default="output", maxlen=GRAPH_SOCKET_ID_MAXLEN
    )
    to_node_id: StringProperty(name="To Node", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    to_socket: StringProperty(
        name="To Socket", default="input", maxlen=GRAPH_SOCKET_ID_MAXLEN
    )
    input_order: IntProperty(name="Input Order", default=0, min=0)
    selected: BoolProperty(name="Selected", default=False)


classes = (
    MixieMoodboardChoice,
    MixieMoodboardNodeParameter,
    MixieMoodboardInputSocket,
    MixieMoodboardActionNode,
    MixieMoodboardAssetNode,
    MixieMoodboardLink,
)
