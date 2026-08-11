# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent, catalog-driven records for moodboard inference blocks."""

import json

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
    GRAPH_OBJECT_NAMES_MAXLEN,
    GRAPH_SERVICE_KEY_MAXLEN,
    GRAPH_SOCKET_ID_MAXLEN,
    GRAPH_WIDGET_MAXLEN,
)


ACTION_TYPES = (
    ('IMAGE_GEN', "Generate Image", "Generate or edit an image"),
    ('VIDEO_GEN', "Generate Video", "Generate a video from image/video references"),
    ('MODEL_3D', "Generate to 3D", "Generate a 3D asset from one image"),
    ('MASK_DETAIL', "Multi Lasso Mask",
     "Generate a detailed image of a lasso-masked region of the source image"),
    # Mesh -> mesh continuations, chained off a 3D mesh node.
    ('PBR_GEN', "PBR Generation", "Texture the connected 3D mesh"),
    ('RETOPOLOGY', "Retopology", "Retopologize the connected 3D mesh"),
    ('MESH_SEGMENT', "Mesh Segmentation", "Segment the connected 3D mesh into parts"),
    ('AUTO_RIG', "Auto Rig", "Auto-rig the connected 3D mesh"),
)

# Action node types whose input is a 3D mesh (from a connected mesh node) and
# whose output is a new 3D mesh. Kept here so both the schema and execution
# layers agree on the set.
MESH_FEATURE_ACTIONS = frozenset(
    {'PBR_GEN', 'RETOPOLOGY', 'MESH_SEGMENT', 'AUTO_RIG'}
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
}


def capability_for_action(action_type: str) -> str:
    if action_type in {'IMAGE_GEN', 'MASK_DETAIL'}:
        return "image_gen"
    if action_type == 'VIDEO_GEN':
        return "video_gen"
    if action_type in _MESH_FEATURE_CAPABILITY:
        return _MESH_FEATURE_CAPABILITY[action_type]
    return "model_gen"


def _service_items(self, _context):
    try:
        from mixar.modules.common.generation_params import get_service_enum_items
        from mixar.modules.moodboard.core.node_schema import services_for_action

        items = get_service_enum_items(capability_for_action(self.action_type))
        if self.action_type == 'MODEL_3D':
            keyed = [{"key": item[0], "item": item} for item in items]
            filtered = services_for_action(self.action_type, keyed)
            return [service["item"] for service in filtered] or [
                ('NONE', "Unavailable", "No supported 3D service is available")
            ]
        if self.action_type == 'MASK_DETAIL':
            # Detail generation runs on the plain image_gen service only.
            filtered = [item for item in items if item[0] == 'image_gen']
            return filtered or items
        if self.action_type == 'MESH_SEGMENT':
            # The mesh node imports segmented part meshes (Part decomposition),
            # not the vertex-group segmenter.
            filtered = [item for item in items if item[0] == 'hunyuan_part']
            return filtered or items
        return items
    except Exception:
        return [('LOADING', "Loading...", "Fetching generation catalog")]


def _model_items(self, _context):
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model_enum_items

        items = get_model_enum_items(self.service_key)
        if self.action_type == 'MASK_DETAIL':
            # Only models advertising mask guidance + two references can detail
            # a cutout/mask pair; fail closed rather than offer an invalid model.
            from mixar.bootstrap.generation_catalog_cache import get_models
            from mixar.modules.moodboard.core.character_components import (
                eligible_component_model_slugs,
            )

            eligible = eligible_component_model_slugs(get_models(self.service_key))
            filtered = [item for item in items if item[0] in eligible]
            return filtered or [(
                'NONE',
                "No compatible models",
                "Image models must advertise mask guidance and two references",
            )]
        return items
    except Exception:
        return [('LOADING', "Loading...", "Fetching generation catalog")]


# The Mode/Model/enum dropdowns are dynamic enums that persist a fragile INDEX,
# so Blender cannot reliably resolve them back to a name at draw time and blanks
# the menu. The C++ node overlay therefore shows a Python-cached human label
# instead, derived from the saved slug (service/model) or choices (params).
def _service_label_for_slug(action_type, service_key) -> str:
    if not service_key:
        return ""
    try:
        from mixar.modules.common.generation_params import get_service_enum_items

        for item in get_service_enum_items(capability_for_action(action_type)):
            if item and item[0] == service_key:
                return str(item[1])
    except Exception:
        pass
    return str(service_key)


def _model_label_for_slug(service_key, model_slug) -> str:
    if not model_slug:
        return ""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model_enum_items

        for item in get_model_enum_items(service_key):
            if item and item[0] == model_slug:
                return str(item[1])
    except Exception:
        pass
    return str(model_slug)


def _enum_label_from_choices(choices_json, value) -> str:
    if not value:
        return ""
    try:
        for choice in json.loads(choices_json or "[]"):
            if isinstance(choice, dict) and str(choice.get("value")) == str(value):
                return str(choice.get("label") or choice.get("value") or "")
    except (TypeError, ValueError):
        pass
    return str(value)


def refresh_node_dropdown_labels(node) -> None:
    """Cache the Mode/Model dropdown labels (read by the C++ node overlay)."""
    node.service_label = _service_label_for_slug(node.action_type, node.service_key_id)
    node.model_label = _model_label_for_slug(node.service_key_id, node.model_slug)


_SUPPRESS_ENUM_MIRROR = False


def suppress_enum_mirror(enabled: bool) -> None:
    """Let restore paths write the dropdowns without clobbering saved slugs.

    Assigning ``service_key`` normally means "the user picked a new mode", which
    resets the model to that service's default. Replaying a *saved* selection
    back into the transient enums must not trigger that reset.
    """
    global _SUPPRESS_ENUM_MIRROR
    _SUPPRESS_ENUM_MIRROR = enabled


def _service_changed(self, _context):
    """A model identifier only has meaning within its selected service."""
    if _SUPPRESS_ENUM_MIRROR:
        return
    self.service_key_id = str(self.service_key or "")
    self.service_label = _service_label_for_slug(self.action_type, self.service_key)
    try:
        from mixar.bootstrap.generation_catalog_cache import get_default_model_slug

        self.model = get_default_model_slug(self.service_key) or ""
    except Exception:
        self.model = ""


def _parameter_changed(self, context):
    """Re-evaluate backend ``visible_if`` rules for this node's controls."""
    if self.parameter_type == 'ENUM':
        self.value_label = _enum_label_from_choices(self.choices_json, self.value_enum)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return
    try:
        from mixar.modules.moodboard.core.node_schema import (
            refresh_node_parameter_visibility,
        )

        pointer = self.as_pointer()
        for node in scene.mixie_moodboard_action_nodes:
            if any(parameter.as_pointer() == pointer for parameter in node.parameters):
                refresh_node_parameter_visibility(node)
                break
    except Exception:
        pass


def _model_changed(self, context):
    if _SUPPRESS_ENUM_MIRROR:
        return
    self.model_slug = str(self.model or "")
    self.model_label = _model_label_for_slug(self.service_key_id, self.model)
    if context is None or getattr(context, "scene", None) is None:
        return
    try:
        from mixar.modules.moodboard.core.node_schema import sync_node_schema

        sync_node_schema(context.scene, self)
    except Exception:
        pass


# Blender does not copy the strings a dynamic ``items`` callback returns, so
# Python must keep them alive for as long as any button can reference them.
# This cache is therefore deliberately never evicted: dropping an entry that a
# live enum still points at is a use-after-free. Growth is bounded in practice
# by the number of distinct parameter schemas the catalog publishes.
_ENUM_ITEM_CACHE = {}


def _parameter_enum_items(self, _context):
    raw = str(getattr(self, "choices_json", "") or "[]")
    cached = _ENUM_ITEM_CACHE.get(raw)
    if cached is not None:
        return cached
    try:
        choices = json.loads(raw)
    except (TypeError, ValueError):
        choices = []
    items = []
    for choice in choices if isinstance(choices, list) else []:
        if not isinstance(choice, dict) or choice.get("value") is None:
            continue
        identifier = str(choice["value"])
        label = str(choice.get("label") or identifier)
        items.append((identifier, label, label))
    cached = items or [('NONE', "None", "No choices published")]
    _ENUM_ITEM_CACHE[raw] = cached
    return cached


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
    prompt: StringProperty(name="Prompt", default="", maxlen=4096)
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
    """Canvas representation of generated Blender object(s) — a 3D mesh node.

    Holds the mesh identity (``object_names``) so the mesh-continuation features
    (PBR / Retopology / Mesh Segmentation / Auto Rig) know which objects to
    select and submit. ``preview_object`` renders the 3D thumbnail on the card.
    """

    node_id: StringProperty(name="Node ID", default="", maxlen=GRAPH_NODE_ID_MAXLEN)
    title: StringProperty(name="Title", default="3D Asset", maxlen=GRAPH_LABEL_MAXLEN)
    object_names: StringProperty(
        name="Object Names", default="", maxlen=GRAPH_OBJECT_NAMES_MAXLEN
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
    MixieMoodboardNodeParameter,
    MixieMoodboardInputSocket,
    MixieMoodboardActionNode,
    MixieMoodboardAssetNode,
    MixieMoodboardLink,
)
