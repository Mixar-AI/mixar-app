# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""glTF export settings PropertyGroup.

Property names match ExportGLTF2_Base exactly so that the native glTF
panel draw functions can read directly from this PropertyGroup.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class MGltfExportSettings(PropertyGroup):
    """glTF export settings with names matching ExportGLTF2_Base."""

    # ---- Format ----
    export_format: EnumProperty(
        name='Format',
        items=(
            ('GLB', "glTF Binary (.glb)",
             "Exports a single file, with all data packed in binary form"),
            ('GLTF_SEPARATE', "glTF Separate (.gltf + .bin + textures)",
             "Exports multiple files, with separate JSON, binary and texture data"),
        ),
        default=0,
    )
    export_copyright: StringProperty(name='Copyright', default='')

    # ---- Include ----
    use_selection: BoolProperty(
        name='Selected Objects',
        description='Export selected objects only',
        default=False,
    )
    use_visible: BoolProperty(
        name='Visible Objects',
        description='Export visible objects only',
        default=False,
    )
    use_renderable: BoolProperty(
        name='Renderable Objects',
        description='Export renderable objects only',
        default=False,
    )
    use_active_collection_with_nested: BoolProperty(
        name='Include Nested Collections',
        default=True,
    )
    use_active_collection: BoolProperty(
        name='Active Collection',
        description='Export objects in the active collection only',
        default=False,
    )
    use_active_scene: BoolProperty(
        name='Active Scene',
        description='Export active scene only',
        default=False,
    )
    export_extras: BoolProperty(
        name='Custom Properties',
        description='Export custom properties as glTF extras',
        default=False,
    )
    export_cameras: BoolProperty(
        name='Cameras', description='Export cameras', default=False,
    )
    export_lights: BoolProperty(
        name='Punctual Lights', default=False,
    )

    # ---- Transform ----
    export_yup: BoolProperty(name='+Y Up', default=True)

    # ---- Data > Scene Graph ----
    export_gpu_instances: BoolProperty(
        name='GPU Instances', default=False,
    )
    export_hierarchy_flatten_objs: BoolProperty(
        name='Flatten Object Hierarchy', default=False,
    )
    export_hierarchy_full_collections: BoolProperty(
        name='Full Collection Hierarchy', default=False,
    )

    # ---- Data > Mesh ----
    export_apply: BoolProperty(
        name='Apply Modifiers',
        description='Apply modifiers (excluding Armatures) to mesh objects',
        default=False,
    )
    export_texcoords: BoolProperty(name='UVs', default=True)
    export_normals: BoolProperty(name='Normals', default=True)
    export_gn_mesh: BoolProperty(
        name='Geometry Nodes Instances (Experimental)', default=False,
    )
    export_tangents: BoolProperty(name='Tangents', default=False)
    export_attributes: BoolProperty(name='Attributes', default=False)
    use_mesh_edges: BoolProperty(name='Loose Edges', default=False)
    use_mesh_vertices: BoolProperty(name='Loose Points', default=False)
    export_shared_accessors: BoolProperty(
        name='Shared Accessors', default=False,
    )
    export_vertex_color: EnumProperty(
        name='Use Vertex Color',
        items=(
            ('MATERIAL', 'Material', 'Export vertex color when used by material'),
            ('ACTIVE', 'Active', 'Export active vertex color'),
            ('NAME', 'Name', 'Export vertex color with this name'),
            ('NONE', 'None', 'Do not export vertex color'),
        ),
        default='MATERIAL',
    )
    export_all_vertex_colors: BoolProperty(
        name='Export All Vertex Colors', default=True,
    )
    export_active_vertex_color_when_no_material: BoolProperty(
        name='Export Active Vertex Color When No Material', default=True,
    )

    # ---- Data > Material ----
    export_materials: EnumProperty(
        name='Materials',
        items=(
            ('EXPORT', 'Export', 'Export all materials used by included objects'),
            ('PLACEHOLDER', 'Placeholder',
             'Do not export materials, but write multiple primitive groups'),
            ('VIEWPORT', 'Viewport',
             'Export minimal materials as defined in Viewport display'),
            ('NONE', 'No export', 'Do not export materials'),
        ),
        default='EXPORT',
    )
    export_image_format: EnumProperty(
        name='Images',
        items=(
            ('AUTO', 'Automatic', 'Save PNGs as PNGs, JPEGs as JPEGs'),
            ('JPEG', 'JPEG Format (.jpg)', 'Save images as JPEGs'),
            ('WEBP', 'WebP Format', 'Save images as WebPs'),
            ('NONE', 'None', "Don't export images"),
        ),
        default='AUTO',
    )
    export_image_quality: IntProperty(
        name='Image Quality', default=75, min=0, max=100,
    )
    export_image_add_webp: BoolProperty(
        name='Create WebP', default=False,
    )
    export_image_webp_fallback: BoolProperty(
        name='WebP Fallback', default=False,
    )
    export_unused_images: BoolProperty(
        name='Unused Images', default=False,
    )
    export_unused_textures: BoolProperty(
        name='Prepare Unused Textures', default=False,
    )

    # ---- Data > Shape Keys ----
    export_morph: BoolProperty(name='Shape Keys', default=True)
    export_morph_normal: BoolProperty(
        name='Shape Key Normals', default=True,
    )
    export_morph_tangent: BoolProperty(
        name='Shape Key Tangents', default=False,
    )
    export_try_sparse_sk: BoolProperty(
        name='Use Sparse Accessor if Better', default=True,
    )
    export_try_omit_sparse_sk: BoolProperty(
        name='Omitting Sparse Accessor if Data is Empty', default=False,
    )

    # ---- Data > Armature ----
    export_rest_position_armature: BoolProperty(
        name='Use Rest Position Armature', default=True,
    )
    export_def_bones: BoolProperty(
        name='Export Deformation Bones Only', default=False,
    )
    export_armature_object_remove: BoolProperty(
        name='Remove Armature Object', default=False,
    )
    export_hierarchy_flatten_bones: BoolProperty(
        name='Flatten Bone Hierarchy', default=False,
    )
    export_leaf_bone: BoolProperty(
        name='Add Leaf Bones', default=False,
    )

    # ---- Data > Skinning ----
    export_skins: BoolProperty(name='Skinning', default=True)
    export_influence_nb: IntProperty(
        name='Bone Influences', default=4, min=1,
    )
    export_all_influences: BoolProperty(
        name='Include All Bone Influences', default=False,
    )

    # ---- Data > Lighting ----
    export_import_convert_lighting_mode: EnumProperty(
        name='Lighting Mode',
        items=(
            ('SPEC', "Standard", "Physically-based glTF lighting units"),
            ('COMPAT', "Unitless", "Non-physical, unitless lighting"),
            ('RAW', "Raw (Deprecated)",
             "Blender lighting strengths with no conversion"),
        ),
        default='SPEC',
    )

    # ---- Data > Compression (Draco) ----
    export_draco_mesh_compression_enable: BoolProperty(
        name='Draco Mesh Compression', default=False,
    )
    export_draco_mesh_compression_level: IntProperty(
        name='Compression Level', default=6, min=0, max=10,
    )
    export_draco_position_quantization: IntProperty(
        name='Position Quantization Bits', default=14, min=0, max=30,
    )
    export_draco_normal_quantization: IntProperty(
        name='Normal Quantization Bits', default=10, min=0, max=30,
    )
    export_draco_texcoord_quantization: IntProperty(
        name='Texcoord Quantization Bits', default=12, min=0, max=30,
    )
    export_draco_color_quantization: IntProperty(
        name='Color Quantization Bits', default=10, min=0, max=30,
    )
    export_draco_generic_quantization: IntProperty(
        name='Generic Quantization Bits', default=12, min=0, max=30,
    )

    # ---- Animation ----
    export_animations: BoolProperty(name='Animations', default=True)
    export_animation_mode: EnumProperty(
        name='Animation Mode',
        items=(
            ('ACTIONS', 'Actions',
             'Export actions as separate animations'),
            ('ACTIVE_ACTIONS', 'Active actions merged',
             'All currently assigned actions become one animation'),
            ('BROADCAST', 'Broadcast actions',
             'Broadcast all compatible actions to all objects'),
            ('NLA_TRACKS', 'NLA Tracks',
             'Export individual NLA Tracks as separate animation'),
            ('SCENE', 'Scene', 'Export baked scene as a single animation'),
        ),
        default='ACTIONS',
    )
    export_nla_strips_merged_animation_name: StringProperty(
        name='Merged Animation Name', default='Animation',
    )
    export_bake_animation: BoolProperty(
        name='Bake All Objects Animations', default=False,
    )
    export_anim_scene_split_object: BoolProperty(
        name='Split Animation by Object', default=True,
    )
    export_merge_animation: EnumProperty(
        name='Merge Animation',
        items=(
            ('NLA_TRACK', 'NLA Track Names', 'Merge by NLA Track Names'),
            ('ACTION', 'Actions', 'Merge by Actions'),
            ('NONE', 'No Merge', 'Do Not Merge Animations'),
        ),
        default='ACTION',
    )
    export_current_frame: BoolProperty(
        name='Use Current Frame as Object Rest Transformations',
        default=False,
    )
    export_frame_range: BoolProperty(
        name='Limit to Playback Range', default=False,
    )
    export_anim_slide_to_zero: BoolProperty(
        name='Set All glTF Animation Starting at 0', default=False,
    )
    export_negative_frame: EnumProperty(
        name='Negative Frames',
        items=(
            ('SLIDE', 'Slide', 'Slide animation to start at frame 0'),
            ('CROP', 'Crop', 'Keep only frames above frame 0'),
        ),
        default='SLIDE',
    )
    export_anim_single_armature: BoolProperty(
        name='Export all Armature Actions', default=True,
    )
    export_reset_pose_bones: BoolProperty(
        name='Reset Pose Bones Between Actions', default=True,
    )

    # ---- Animation > Shape Keys ----
    export_morph_animation: BoolProperty(
        name='Shape Key Animations', default=True,
    )
    export_morph_reset_sk_data: BoolProperty(
        name='Reset Shape Keys Between Actions', default=True,
    )

    # ---- Animation > Sampling ----
    export_force_sampling: BoolProperty(
        name='Always Sample Animations', default=True,
    )
    export_frame_step: IntProperty(
        name='Sampling Rate', default=1, min=1, max=120,
    )
    export_sampling_interpolation_fallback: EnumProperty(
        name='Sampling Interpolation Fallback',
        items=(
            ('LINEAR', 'Linear', 'Linear interpolation between keyframes'),
            ('STEP', 'Step', 'No interpolation between keyframes'),
        ),
        default='LINEAR',
    )

    # ---- Animation > Pointer ----
    export_pointer_animation: BoolProperty(
        name='Export Animation Pointer (Experimental)', default=False,
    )
    export_convert_animation_pointer: BoolProperty(
        name='Convert TRS/Weights to Animation Pointer', default=False,
    )

    # ---- Animation > Optimize ----
    export_optimize_animation_size: BoolProperty(
        name='Optimize Animation Size', default=True,
    )
    export_optimize_animation_keep_anim_armature: BoolProperty(
        name='Force Keeping Channels for Bones', default=True,
    )
    export_optimize_animation_keep_anim_object: BoolProperty(
        name='Force Keeping Channel for Objects', default=False,
    )
    export_optimize_disable_viewport: BoolProperty(
        name='Disable Viewport for Other Objects', default=False,
    )

    # ---- Animation > Extra ----
    export_extra_animations: BoolProperty(
        name='Prepare Extra Animations', default=False,
    )

    # ---- gltfpack ----
    export_use_gltfpack: BoolProperty(
        name='Use Gltfpack', default=False,
    )
    export_gltfpack_tc: BoolProperty(
        name='KTX2 Compression', default=True,
    )
    export_gltfpack_tq: IntProperty(
        name='Texture Encoding Quality', default=8, min=1, max=10,
    )
    export_gltfpack_si: FloatProperty(
        name='Mesh Simplification Ratio', default=1.0, min=0.0, max=1.0,
    )
    export_gltfpack_sa: BoolProperty(
        name='Aggressive Mesh Simplification', default=False,
    )
    export_gltfpack_slb: BoolProperty(
        name='Lock Mesh Border Vertices', default=False,
    )
    export_gltfpack_vp: IntProperty(
        name='Position Quantization', default=14, min=1, max=16,
    )
    export_gltfpack_vt: IntProperty(
        name='Texture Coordinate Quantization', default=12, min=1, max=16,
    )
    export_gltfpack_vn: IntProperty(
        name='Normal/Tangent Quantization', default=8, min=1, max=16,
    )
    export_gltfpack_vc: IntProperty(
        name='Vertex Color Quantization', default=8, min=1, max=16,
    )
    export_gltfpack_vpi: EnumProperty(
        name='Vertex Position Attributes',
        items=(
            ('Integer', 'Integer', 'Use integer attributes for positions'),
            ('Normalized', 'Normalized',
             'Use normalized attributes for positions'),
            ('Floating-point', 'Floating-point',
             'Use floating-point attributes for positions'),
        ),
        default='Integer',
    )
    export_gltfpack_noq: BoolProperty(
        name='Disable Quantization', default=True,
    )
    export_gltfpack_kn: BoolProperty(
        name='Keep Named Nodes', default=False,
    )

    # ---- Internal / kept for compatibility ----
    will_save_settings: BoolProperty(
        name='Remember Export Settings', default=False,
    )
    export_keep_originals: BoolProperty(
        name='Keep Original', default=False,
    )
    export_texture_dir: StringProperty(
        name='Textures', default='',
    )


def register():
    bpy.utils.register_class(MGltfExportSettings)
    bpy.types.WindowManager.mixar_export_gltf = bpy.props.PointerProperty(
        type=MGltfExportSettings,
    )


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixar_export_gltf'):
        del bpy.types.WindowManager.mixar_export_gltf
    bpy.utils.unregister_class(MGltfExportSettings)
