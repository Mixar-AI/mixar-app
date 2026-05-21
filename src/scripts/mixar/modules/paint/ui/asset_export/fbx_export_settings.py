# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FBX export settings PropertyGroup.

Property names match ExportFBX exactly so that the native FBX panel
draw functions can read directly from this PropertyGroup.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class MFbxExportSettings(PropertyGroup):
    """FBX export settings with names matching ExportFBX."""

    # ---- Path / Textures ----
    path_mode: EnumProperty(
        name='Path Mode',
        items=(
            ('AUTO', "Auto", "Use relative paths with subdirectories only"),
            ('ABSOLUTE', "Absolute", "Always write absolute paths"),
            ('RELATIVE', "Relative", "Always write relative paths"),
            ('MATCH', "Match", "Match the original path reference mode"),
            ('STRIP', "Strip Path", "Only write the filename"),
            ('COPY', "Copy", "Copy textures to the destination path"),
        ),
        default='AUTO',
    )
    embed_textures: BoolProperty(
        name='Embed Textures',
        description='Embed textures in FBX binary file (only for "Copy" path mode)',
        default=False,
    )
    batch_mode: EnumProperty(
        name='Batch Mode',
        items=(
            ('OFF', "Off", "Active scene to file"),
            ('SCENE', "Scene", "Each scene as a file"),
            ('COLLECTION', "Collection", "Each collection as a file"),
            ('SCENE_COLLECTION', "Scene Collections",
             "Each collection of each scene as a file"),
            ('ACTIVE_SCENE_COLLECTION', "Active Scene Collections",
             "Each collection of the active scene as a file"),
        ),
        default='OFF',
    )
    use_batch_own_dir: BoolProperty(
        name='Batch Own Dir',
        description='Create a dir for each exported file',
        default=True,
    )

    # ---- Include ----
    use_selection: BoolProperty(
        name='Selected Objects',
        description='Export selected and visible objects only',
        default=False,
    )
    use_visible: BoolProperty(
        name='Visible Objects',
        description='Export visible objects only',
        default=False,
    )
    use_active_collection: BoolProperty(
        name='Active Collection',
        description='Export only objects from the active collection',
        default=False,
    )
    object_types: EnumProperty(
        name='Object Types',
        options={'ENUM_FLAG'},
        items=(
            ('EMPTY', "Empty", ""),
            ('CAMERA', "Camera", ""),
            ('LIGHT', "Lamp", ""),
            ('ARMATURE', "Armature", ""),
            ('MESH', "Mesh", ""),
            ('OTHER', "Other", "Other geometry types"),
        ),
        description='Which kind of object to export',
        default={'EMPTY', 'CAMERA', 'LIGHT', 'ARMATURE', 'MESH', 'OTHER'},
    )
    use_custom_props: BoolProperty(
        name='Custom Properties', default=False,
    )

    # ---- Transform ----
    global_scale: FloatProperty(
        name='Scale', min=0.001, max=1000.0,
        soft_min=0.01, soft_max=1000.0, default=1.0,
    )
    apply_scale_options: EnumProperty(
        name='Apply Scalings',
        items=(
            ('FBX_SCALE_NONE', "All Local",
             "Apply custom scaling and units scaling to each object"),
            ('FBX_SCALE_UNITS', "FBX Units Scale",
             "Apply custom scaling to each object, units scaling to FBX"),
            ('FBX_SCALE_CUSTOM', "FBX Custom Scale",
             "Apply custom scaling to FBX, units scaling to each object"),
            ('FBX_SCALE_ALL', "FBX All",
             "Apply custom scaling and units scaling to FBX scale"),
        ),
        default='FBX_SCALE_NONE',
    )
    axis_forward: EnumProperty(
        name='Forward',
        items=(
            ('X', "X Forward", ""),
            ('Y', "Y Forward", ""),
            ('Z', "Z Forward", ""),
            ('-X', "-X Forward", ""),
            ('-Y', "-Y Forward", ""),
            ('-Z', "-Z Forward", ""),
        ),
        default='-Z',
    )
    axis_up: EnumProperty(
        name='Up',
        items=(
            ('X', "X Up", ""),
            ('Y', "Y Up", ""),
            ('Z', "Z Up", ""),
            ('-X', "-X Up", ""),
            ('-Y', "-Y Up", ""),
            ('-Z', "-Z Up", ""),
        ),
        default='Y',
    )
    apply_unit_scale: BoolProperty(
        name='Apply Unit',
        description='Take into account current Blender units settings',
        default=True,
    )
    use_space_transform: BoolProperty(
        name='Use Space Transform',
        description='Apply global space transform to the object rotations',
        default=True,
    )
    bake_space_transform: BoolProperty(
        name='Apply Transform',
        description='Bake space transform into object data (experimental)',
        default=False,
    )

    # ---- Geometry ----
    mesh_smooth_type: EnumProperty(
        name='Smoothing',
        items=(
            ('OFF', "Normals Only", "Export only normals"),
            ('FACE', "Face", "Write face smoothing"),
            ('EDGE', "Edge", "Write edge smoothing"),
            ('SMOOTH_GROUP', "Smoothing Groups", "Write face smoothing groups"),
        ),
        default='OFF',
    )
    use_subsurf: BoolProperty(
        name='Export Subdivision Surface', default=False,
    )
    use_mesh_modifiers: BoolProperty(
        name='Apply Modifiers', default=True,
    )
    use_mesh_edges: BoolProperty(
        name='Loose Edges', default=False,
    )
    use_triangles: BoolProperty(
        name='Triangulate Faces', default=False,
    )
    use_tspace: BoolProperty(
        name='Tangent Space', default=False,
    )
    colors_type: EnumProperty(
        name='Vertex Colors',
        items=(
            ('NONE', "None", "Do not export color attributes"),
            ('SRGB', "sRGB", "Export colors in sRGB color space"),
            ('LINEAR', "Linear", "Export colors in linear color space"),
        ),
        default='SRGB',
    )
    prioritize_active_color: BoolProperty(
        name='Prioritize Active Color', default=False,
    )

    # ---- Armature ----
    primary_bone_axis: EnumProperty(
        name='Primary Bone Axis',
        items=(
            ('X', "X Axis", ""), ('Y', "Y Axis", ""),
            ('Z', "Z Axis", ""), ('-X', "-X Axis", ""),
            ('-Y', "-Y Axis", ""), ('-Z', "-Z Axis", ""),
        ),
        default='Y',
    )
    secondary_bone_axis: EnumProperty(
        name='Secondary Bone Axis',
        items=(
            ('X', "X Axis", ""), ('Y', "Y Axis", ""),
            ('Z', "Z Axis", ""), ('-X', "-X Axis", ""),
            ('-Y', "-Y Axis", ""), ('-Z', "-Z Axis", ""),
        ),
        default='X',
    )
    armature_nodetype: EnumProperty(
        name='Armature FBXNode Type',
        items=(
            ('NULL', "Null", "'Null' FBX node, similar to Empty"),
            ('ROOT', "Root", "'Root' FBX node"),
            ('LIMBNODE', "LimbNode", "'LimbNode' FBX node"),
        ),
        default='NULL',
    )
    use_armature_deform_only: BoolProperty(
        name='Only Deform Bones', default=False,
    )
    add_leaf_bones: BoolProperty(
        name='Add Leaf Bones', default=True,
    )

    # ---- Animation ----
    bake_anim: BoolProperty(
        name='Baked Animation', default=True,
    )
    bake_anim_use_all_bones: BoolProperty(
        name='Key All Bones', default=True,
    )
    bake_anim_use_nla_strips: BoolProperty(
        name='NLA Strips', default=True,
    )
    bake_anim_use_all_actions: BoolProperty(
        name='All Actions', default=True,
    )
    bake_anim_force_startend_keying: BoolProperty(
        name='Force Start/End Keying', default=True,
    )
    bake_anim_step: FloatProperty(
        name='Sampling Rate', min=0.01, max=100.0,
        soft_min=0.1, soft_max=10.0, default=1.0,
    )
    bake_anim_simplify_factor: FloatProperty(
        name='Simplify', min=0.0, max=100.0,
        soft_min=0.0, soft_max=10.0, default=1.0,
    )


def register():
    bpy.utils.register_class(MFbxExportSettings)
    bpy.types.WindowManager.mixar_export_fbx = bpy.props.PointerProperty(
        type=MFbxExportSettings,
    )


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixar_export_fbx'):
        del bpy.types.WindowManager.mixar_export_fbx
    bpy.utils.unregister_class(MFbxExportSettings)
