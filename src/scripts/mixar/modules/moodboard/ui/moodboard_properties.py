# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Core Property Definitions

PropertyGroup classes for the fundamental moodboard data:
images, text boxes, groups, and segments.
"""

import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    PointerProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
    EnumProperty,
    FloatVectorProperty,
)

from mixar.modules.moodboard.constants import (
    IMAGE_SCALE_DEFAULT, IMAGE_SCALE_MIN, IMAGE_SCALE_MAX,
    IMAGE_ROTATION_DEFAULT, IMAGE_ROTATION_MIN, IMAGE_ROTATION_MAX,
    TEXTBOX_FONT_SIZE_DEFAULT, TEXTBOX_FONT_SIZE_MIN, TEXTBOX_FONT_SIZE_MAX,
    TEXTBOX_WIDTH_DEFAULT, TEXTBOX_WIDTH_MIN, TEXTBOX_WIDTH_MAX,
    TEXTBOX_HEIGHT_DEFAULT, TEXTBOX_HEIGHT_MIN, TEXTBOX_HEIGHT_MAX,
    TEXTBOX_COLOR_DEFAULT, TEXTBOX_BACKGROUND_COLOR_DEFAULT,
    TEXTBOX_ROTATION_DEFAULT, TEXTBOX_ROTATION_MIN, TEXTBOX_ROTATION_MAX,
    TEXT_ALIGNMENTS,
    TURNAROUND_VIEW_TYPES, TURNAROUND_VIEW_DEFAULT,
    CHARACTER_COMPONENT_IMAGE_ROLES,
)
from .moodboard_annotation_props import MixieMoodboardAnnotationStroke


class MixieMoodboardSegment(PropertyGroup):
    """Individual segment for an image (Magic Select results)"""

    component_id: StringProperty(
        name="Component ID",
        description="Persistent identity for this character component",
        default="",
    )

    mask_image: PointerProperty(
        type=bpy.types.Image,
        name="Mask Image",
        description="Binary mask for this segment (white=selected)"
    )
    active: BoolProperty(
        name="Active",
        description="Show this segment overlay and include it in Segments to 3D",
        default=True
    )
    show_overlay: BoolProperty(
        name="Show Overlay",
        description="Show the colored mask overlay on the source image",
        default=True,
    )
    outline_only: BoolProperty(
        name="Outline Only",
        description="Render only the selection boundary while keeping source pixels unchanged",
        default=False,
    )
    selection_outline: StringProperty(
        name="Selection Outline",
        description="Original lasso polygon stored as normalized JSON coordinates",
        default="",
    )
    include_for_detail: BoolProperty(
        name="Include Detail",
        description="Include this component in batch detail-image generation",
        default=True,
    )
    index: IntProperty(
        name="Index",
        description="Segment number",
        default=0
    )
    name: StringProperty(
        name="Name",
        description="Component name used to guide detail-image generation",
        default="Segment",
        maxlen=96,
    )


class MixieMoodboardImage(PropertyGroup):
    """Property group for moodboard reference images"""

    moodboard_item_id: StringProperty(
        name="Moodboard Item ID",
        description="Persistent identity used by component provenance links",
        default="",
    )

    image: PointerProperty(
        name="Image",
        description="Reference image",
        type=bpy.types.Image
    )

    # Computed properties for UI display (read-only)
    @property
    def display_width(self) -> int:
        """Get image width for display"""
        return self.image.size[0] if self.image else 0

    @property
    def display_height(self) -> int:
        """Get image height for display"""
        return self.image.size[1] if self.image else 0

    @property
    def display_name(self) -> str:
        """Get image name for display"""
        return self.image.name if self.image else ""

    @property
    def display_resolution(self) -> str:
        """Get formatted resolution string"""
        if self.image and self.image.size[0] > 0 and self.image.size[1] > 0:
            return f"{self.image.size[0]} x {self.image.size[1]}"
        return ""

    position_x: FloatProperty(
        name="Position X",
        description="X position on the moodboard canvas",
        default=0.0
    )
    position_y: FloatProperty(
        name="Position Y",
        description="Y position on the moodboard canvas",
        default=0.0
    )
    scale: FloatProperty(
        name="Scale",
        description="Scale factor for the image",
        default=IMAGE_SCALE_DEFAULT,
        min=IMAGE_SCALE_MIN,
        max=IMAGE_SCALE_MAX,
    )
    z_order: IntProperty(
        name="Z Order",
        description="Layer order (higher values are on top)",
        default=0
    )
    rotation: FloatProperty(
        name="Rotation",
        description="Rotation angle in degrees",
        default=IMAGE_ROTATION_DEFAULT,
        min=IMAGE_ROTATION_MIN,
        max=IMAGE_ROTATION_MAX,
    )
    flip_horizontal: BoolProperty(
        name="Flip Horizontal",
        description="Flip image horizontally (mirror on Y axis)",
        default=False
    )
    flip_vertical: BoolProperty(
        name="Flip Vertical",
        description="Flip image vertically (mirror on X axis)",
        default=False
    )
    selected: BoolProperty(
        name="Selected",
        description="Whether this image is currently selected",
        default=False,
        # Note: a property update= callback was tried for chat-sync but
        # doesn't fire from the C++ select/box-select operators (they
        # call RNA_property_boolean_set without RNA_property_update).
        # Sync is driven by a polling tick instead — see
        # moodboard.core.chat_sync.
    )
    generation_prompt: StringProperty(
        name="Generation Prompt",
        description="The prompt used to generate this image (if AI generated)",
        default="",
        maxlen=2048,
    )
    group_index: IntProperty(
        name="Group Index",
        description="Index of the group this image belongs to (-1 for no group)",
        default=-1
    )

    annotations: CollectionProperty(
        type=MixieMoodboardAnnotationStroke,
        name="Annotations",
        description="Non-destructive freehand strokes attached to this image",
    )
    show_annotations: BoolProperty(
        name="Show Annotations",
        description="Display freehand annotations on this image",
        default=True,
    )

    # Segment collection - stores all segments for this image (Magic Select)
    segments: CollectionProperty(
        type=MixieMoodboardSegment,
        name="Segments",
        description="Collection of segments created by Magic Select"
    )
    active_segment_index: IntProperty(
        name="Active Segment Index",
        description="Index of the currently selected segment",
        default=-1
    )
    # Display image with segment overlays applied (cached for performance)
    display_image: PointerProperty(
        type=bpy.types.Image,
        name="Display Image",
        description="Cached image with segment overlays applied"
    )
    # Compressed image for SAM upload (max 2048px, JPEG)
    compressed_image: PointerProperty(
        type=bpy.types.Image,
        name="Compressed Image",
        description="Compressed version of image used for SAM segmentation"
    )
    # Scene generation job tracking
    scene_gen_job_id: StringProperty(
        name="Scene Gen Job ID",
        description="Active scene generation job ID",
        default="",
        options={'SKIP_SAVE'},
    )
    chain_id: StringProperty(
        name="Chain ID",
        description="Pipeline chain ID linking label → image → HP mesh → LP mesh",
        default="",
    )

    # --- Character-component provenance --------------------------------
    component_role: EnumProperty(
        name="Character Component Role",
        description="How this image participates in a character component workflow",
        items=CHARACTER_COMPONENT_IMAGE_ROLES,
        default='NONE',
    )
    component_source_item_id: StringProperty(
        name="Component Source Image",
        description="Persistent moodboard item ID of the source character reference",
        default="",
    )
    component_source_segment_id: StringProperty(
        name="Component Source Segment",
        description="Persistent SAM3 segment ID that guided this detail image",
        default="",
    )
    component_name: StringProperty(
        name="Component Name",
        description="Named character component represented by this image",
        default="",
        maxlen=96,
    )

    # --- Turnaround / multi-view sets ------------------------------------
    # Populated by mixie.moodboard_detect_views when a single uploaded sheet
    # is split into per-view crops by POST /model-3d/detect-views, or by
    # mixie.moodboard_add_turnaround_view when the user builds a set by hand.
    view_type: EnumProperty(
        name="View",
        description=(
            "Camera angle this image shows. Only meaningful while the image "
            "belongs to a multi-view set — it is sent alongside the tab's "
            "input image as that angle"
        ),
        # Exactly the vendor's ViewType enum: seven companion angles, no
        # 'main' / 'front' / 'none'. The main image is the tab's Input Image
        # and never joins the set, so it needs no label. Kept STATIC rather
        # than filtered per model: this is saved .blend data and a dynamic
        # items= callback would remap or lose stored values when the model
        # switches. 3.0's narrower angle set is enforced when views are
        # assigned and again at payload build.
        items=TURNAROUND_VIEW_TYPES,
        default=TURNAROUND_VIEW_DEFAULT,
    )
    turnaround_group: StringProperty(
        name="Turnaround Group",
        description=(
            "Shared identifier linking every companion view of one "
            "multi-view set — crops detected from the same turnaround / "
            "model sheet, plus any views added by hand. Empty for ordinary "
            "images, including the set's own input image"
        ),
        default="",
    )
    turnaround_main_group: StringProperty(
        name="Turnaround Main",
        description=(
            "Identifier of the multi-view set this image is the FRONTAL "
            "(main) image of. This is the only thing that binds a set to an "
            "image: a set is submitted alongside an image if, and only if, "
            "that image carries the set's id here. Empty on companion views "
            "and on every ordinary moodboard image — exactly one item per "
            "set ever carries it"
        ),
        # Deliberately NOT turnaround_group: that property means "companion
        # of", and group_items / eligible_selected_images / the vendor's
        # 7-companion cap / the panel's view list all iterate on it. Putting
        # the main image in the group would make it a companion of itself.
        default="",
    )
    s3_key: StringProperty(
        name="S3 Key",
        description=(
            "Durable backend object key for this image, returned by the "
            "detect-views endpoint. Sent at submit time instead of "
            "re-uploading the pixels. Empty for a hand-added view, which "
            "carries its pixels inline instead"
        ),
        default="",
    )

    # Generation-loop-closure metadata (Phase 1)
    mixar_created_at_iso: StringProperty(
        name="Created At (ISO)",
        description=(
            "UTC ISO-8601 timestamp set when this entry was added to the moodboard. "
            "Used by the agent's list_moodboard_images tool for since-baseline diffs."
        ),
        default="",
        options={'SKIP_SAVE'},
    )

    # Generation-loop-closure metadata (Phase 2)
    mixar_job_handle: StringProperty(
        name="GPU Job Handle",
        description=(
            "Per-request identifier (mirrors the backend's request_id / session_id) "
            "of the generation pipeline that produced this image. Lets the agent "
            "correlate moodboard items back to the job that created them."
        ),
        default="",
        options={'SKIP_SAVE'},
    )


class MixieMoodboardGroup(PropertyGroup):
    """Property group for moodboard image groups"""

    name: StringProperty(
        name="Name",
        description="Group name",
        default="Group",
        maxlen=64
    )
    color: FloatVectorProperty(
        name="Color",
        description="Group color",
        subtype='COLOR',
        size=4,
        default=(0.2, 0.6, 1.0, 1.0),
        min=0.0,
        max=1.0
    )
    visible: BoolProperty(
        name="Visible",
        description="Whether group is visible",
        default=True
    )
    locked: BoolProperty(
        name="Locked",
        description="Whether group is locked (cannot select children)",
        default=False
    )
    selected: BoolProperty(
        name="Selected",
        description="Whether this group is currently selected",
        default=False
    )


class MixieMoodboardTextBox(PropertyGroup):
    """Property group for moodboard text boxes"""

    text: StringProperty(
        name="Text",
        description="Text content of the text box",
        default="Text",
        maxlen=1024
    )
    position_x: FloatProperty(
        name="Position X",
        description="X position on the moodboard canvas",
        default=0.0
    )
    position_y: FloatProperty(
        name="Position Y",
        description="Y position on the moodboard canvas",
        default=0.0
    )
    font_size: IntProperty(
        name="Font Size",
        description="Font size in points",
        default=TEXTBOX_FONT_SIZE_DEFAULT,
        min=TEXTBOX_FONT_SIZE_MIN,
        max=TEXTBOX_FONT_SIZE_MAX,
    )
    text_color: FloatVectorProperty(
        name="Text Color",
        description="Color of the text",
        subtype='COLOR',
        size=4,
        default=TEXTBOX_COLOR_DEFAULT,
        min=0.0,
        max=1.0
    )
    background_color: FloatVectorProperty(
        name="Background Color",
        description="Background color of the text box",
        subtype='COLOR',
        size=4,
        default=TEXTBOX_BACKGROUND_COLOR_DEFAULT,
        min=0.0,
        max=1.0
    )
    width: FloatProperty(
        name="Width",
        description="Width of the text box",
        default=TEXTBOX_WIDTH_DEFAULT,
        min=TEXTBOX_WIDTH_MIN,
        max=TEXTBOX_WIDTH_MAX,
    )
    height: FloatProperty(
        name="Height",
        description="Height of the text box",
        default=TEXTBOX_HEIGHT_DEFAULT,
        min=TEXTBOX_HEIGHT_MIN,
        max=TEXTBOX_HEIGHT_MAX,
    )
    rotation: FloatProperty(
        name="Rotation",
        description="Rotation angle in degrees",
        default=TEXTBOX_ROTATION_DEFAULT,
        min=TEXTBOX_ROTATION_MIN,
        max=TEXTBOX_ROTATION_MAX,
    )
    z_order: IntProperty(
        name="Z Order",
        description="Layer order (higher values are on top)",
        default=0
    )
    selected: BoolProperty(
        name="Selected",
        description="Whether this text box is currently selected",
        default=False
    )
    bold: BoolProperty(
        name="Bold",
        description="Use bold font",
        default=False
    )
    italic: BoolProperty(
        name="Italic",
        description="Use italic font",
        default=False
    )
    align: EnumProperty(
        name="Alignment",
        description="Text alignment within the box",
        items=TEXT_ALIGNMENTS,
        default='LEFT'
    )
