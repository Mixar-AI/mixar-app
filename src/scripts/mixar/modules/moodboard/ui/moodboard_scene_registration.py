# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Scene-Level Property Registration

Registers PropertyGroup classes and attaches collection/pointer properties
to bpy.types.Scene and bpy.types.WindowManager.

Architecture notes
------------------
This module has explicit register()/unregister() functions (rather than
relying solely on bootstrap auto-discovery) because it must wire up
bpy.types.Scene and bpy.types.WindowManager properties *after* the
PropertyGroup classes they reference have been registered. The bootstrap
auto-discovery system in ``startup/bootstrap/__init__.py`` excludes classes
that are already registered here, so there is no double-registration.

The ``try: register_class(cls) / except ValueError`` pattern inside
register() guards against hot-reloads (F8 or script re-run): Blender
raises ``ValueError`` when a class is already registered, which we catch
and silently skip so the rest of the property setup can proceed.
"""

import bpy
from bpy.props import (
    PointerProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
)

from mixar.config.logging_config import get_logger

from .moodboard_properties import (
    MixieMoodboardSegment,
    MixieMoodboardImage,
    MixieMoodboardGroup,
    MixieMoodboardTextBox,
)
from .moodboard_annotation_props import (
    MixieMoodboardAnnotationPoint,
    MixieMoodboardAnnotationStroke,
)
from .moodboard_graph_properties import (
    MixieMoodboardActionNode,
    MixieMoodboardAssetNode,
    MixieMoodboardInputSocket,
    MixieMoodboardLink,
    MixieMoodboardNodeParameter,
)
from .moodboard_tab_properties import (
    MixieCharacterComponentSettings,
    MixieMoodboardReferenceImage,
    MixieMoodboardTabAIRenderProps,
    MixieMoodboardTabImageGenProps,
    MixieMoodboardTabLookdevProps,
    MixieMoodboardTabLookdev360Props,
    MixieMoodboardTabPBRGenProps,
    MixieMoodboardTabImageTo3DProps,
    MixieMoodboardTabSegmentTo3DProps,
    MixieMoodboardTabMeshSegmentProps,
    MixieMoodboardTabSceneReconProps,
    MixieMoodboardTabAnimateProps,
    MixieMoodboardTabRetopologyProps,
    MixieMoodboardTabUVUnwrapProps,
    MixieMoodboardTabVideoGenProps,
    # Scene Gen Experimental disabled
    # MixieSceneGenExpBBox,
    # MixieSceneGenExpLabelObject,
    # MixieMoodboardTabSceneGenExpProps,
    MixieMoodboardSidebarProperties,
)

logger = get_logger(__name__)

classes = (
    MixieMoodboardAnnotationPoint,
    MixieMoodboardAnnotationStroke,
    MixieMoodboardSegment,
    MixieMoodboardImage,
    MixieMoodboardGroup,
    MixieMoodboardNodeParameter,
    MixieMoodboardInputSocket,
    MixieMoodboardActionNode,
    MixieMoodboardAssetNode,
    MixieMoodboardLink,
    MixieMoodboardReferenceImage,
    MixieMoodboardTabAIRenderProps,
    MixieMoodboardTabImageGenProps,
    MixieMoodboardTabLookdevProps,
    MixieMoodboardTabLookdev360Props,
    MixieMoodboardTabPBRGenProps,
    MixieMoodboardTabImageTo3DProps,
    MixieCharacterComponentSettings,
    MixieMoodboardTabSegmentTo3DProps,
    MixieMoodboardTabMeshSegmentProps,
    MixieMoodboardTabSceneReconProps,
    MixieMoodboardTabAnimateProps,
    MixieMoodboardTabRetopologyProps,
    MixieMoodboardTabUVUnwrapProps,
    MixieMoodboardTabVideoGenProps,
    # Scene Gen Experimental disabled
    # MixieSceneGenExpBBox,
    # MixieSceneGenExpLabelObject,
    # MixieMoodboardTabSceneGenExpProps,
    MixieMoodboardSidebarProperties,
    MixieMoodboardTextBox,
)


def register():
    """Register moodboard property classes and scene-level properties."""
    from bpy.utils import register_class

    for cls in classes:
        try:
            register_class(cls)
        except ValueError:
            logger.debug("Class %s already registered", cls.__name__)
        except Exception as e:
            logger.error("Failed to register class %s: %s", cls.__name__, e)

    # Scene collection properties
    _safe_scene_prop(
        'mixie_moodboard_images',
        CollectionProperty(
            type=MixieMoodboardImage,
            name="Mixie Moodboard Images",
            description="Collection of reference images in Moodboard mode",
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_textboxes',
        CollectionProperty(
            type=MixieMoodboardTextBox,
            name="Mixie Moodboard Text Boxes",
            description="Collection of text boxes in Moodboard mode",
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_groups',
        CollectionProperty(
            type=MixieMoodboardGroup,
            name="Mixie Moodboard Groups",
            description="Collection of image groups",
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_action_nodes',
        CollectionProperty(
            type=MixieMoodboardActionNode,
            name="Moodboard Action Nodes",
            description="Persistent generative inference blocks",
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_asset_nodes',
        CollectionProperty(
            type=MixieMoodboardAssetNode,
            name="Moodboard Asset Nodes",
            description="Persistent canvas cards for generated 3D assets",
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_links',
        CollectionProperty(
            type=MixieMoodboardLink,
            name="Moodboard Links",
            description="Connections between moodboard media, actions, and assets",
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_active_node_id',
        StringProperty(
            name="Active Moodboard Node",
            description="Stable identifier of the selected graph node",
            default="",
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_output_source_id',
        StringProperty(
            name="Moodboard Output Source",
            description="Source node used by the output-handle continuation menu",
            default="",
            options={'SKIP_SAVE'},
        ),
    )
    for axis in ('x', 'y'):
        _safe_scene_prop(
            f'mixie_moodboard_context_{axis}',
            FloatProperty(
                name=f"Moodboard Context {axis.upper()}",
                description="Canvas position of the latest context-menu invocation",
                default=0.0,
                options={'SKIP_SAVE'},
            ),
        )
    _safe_scene_prop(
        'mixie_moodboard_selected_index',
        IntProperty(
            name="Selected Moodboard Image Index",
            description="Index of the currently selected moodboard image",
            default=-1,
        ),
    )
    _safe_scene_prop(
        'mixie_moodboard_sidebar',
        PointerProperty(
            type=MixieMoodboardSidebarProperties,
            name="Moodboard Sidebar Properties",
            description="Properties for moodboard sidebar state",
        ),
    )

    # Edit tool state
    try:
        from .moodboard_edit_state import MoodboardEditToolState
        try:
            register_class(MoodboardEditToolState)
        except ValueError:
            pass  # already registered
        _safe_scene_prop(
            'mixie_edit_tool_state',
            PointerProperty(type=MoodboardEditToolState),
        )
    except Exception as e:
        logger.error("Failed to register mixie_edit_tool_state: %s", e)

    # Generation state flags (SKIP_SAVE so undo doesn't restore stale generating state)
    _safe_scene_prop(
        'mixie_scene_recon_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether scene reconstruction is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_scene_recon_error',
        StringProperty(
            name="Error Message",
            description="Last error message from scene reconstruction",
            default="",
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_segment_to_3d_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether segment to 3D generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_imagegen_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether image generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_video_gen_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether video generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_lookdev_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether lookdev generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_lookdev360_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether lookdev360 generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_image_to_3d_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether image to 3D generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    # Scene Gen Experimental disabled — flags intentionally not registered.
    _safe_scene_prop(
        'mixie_retopology_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether retopology generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_animate_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether rig/animate generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_pbr_gen_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether PBR (Tripo texture) generation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    # Tripo segmentation. Separate from mixie_mesh_segment_is_processing
    # (Jasper) so the two engines' in-flight state never masks each other.
    _safe_scene_prop(
        'mixie_tripo_segment_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether Tripo mesh segmentation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )
    _safe_scene_prop(
        'mixie_smart_segment_is_generating',
        BoolProperty(
            name="Is Generating",
            description="Whether Tripo smart segmentation is in progress",
            default=False,
            options={'SKIP_SAVE'},
        ),
    )

    # Generation progress floats (session-only)
    for prefix in ('imagegen', 'video_gen', 'lookdev', 'lookdev360', 'image_to_3d', 'scene_recon',
                    'segment_to_3d', 'mesh_segment', 'retopology', 'animate',
                    'pbr_gen', 'tripo_segment', 'smart_segment'):
        # Scene Gen Experimental ('scene_gen_hp', 'scene_gen_lp') intentionally omitted.
        _safe_wm_prop(
            f'mixie_{prefix}_generate_progress',
            FloatProperty(
                name="Generate Progress",
                description=f"Generation progress for {prefix}",
                default=0.0, min=0.0, max=1.0,
                subtype='FACTOR',
                options={'SKIP_SAVE'},
            ),
        )


def unregister():
    """Unregister moodboard property classes and scene-level properties."""
    from bpy.utils import unregister_class

    # Scene properties (reverse of registration order)
    for attr in (
        # Scene Gen Experimental flags were not registered; nothing to remove.
        'mixie_smart_segment_is_generating',
        'mixie_tripo_segment_is_generating',
        'mixie_pbr_gen_is_generating',
        'mixie_animate_is_generating',
        'mixie_retopology_is_generating',
        'mixie_image_to_3d_is_generating',
        'mixie_lookdev360_is_generating',
        'mixie_lookdev_is_generating',
        'mixie_imagegen_is_generating',
        'mixie_video_gen_is_generating',
        'mixie_scene_recon_error',
        'mixie_scene_recon_is_generating',
        'mixie_segment_to_3d_is_generating',
        'mixie_edit_tool_state',
        'mixie_moodboard_sidebar',
        'mixie_moodboard_output_source_id',
        'mixie_moodboard_active_node_id',
        'mixie_moodboard_context_y',
        'mixie_moodboard_context_x',
        'mixie_moodboard_links',
        'mixie_moodboard_asset_nodes',
        'mixie_moodboard_action_nodes',
        'mixie_moodboard_selected_index',
        'mixie_moodboard_groups',
        'mixie_moodboard_textboxes',
        'mixie_moodboard_images',
    ):
        try:
            delattr(bpy.types.Scene, attr)
        except AttributeError:
            pass

    # WindowManager properties
    wm_attrs = []
    for prefix in ('imagegen', 'video_gen', 'lookdev', 'lookdev360', 'image_to_3d', 'scene_recon',
                    'segment_to_3d', 'mesh_segment', 'retopology', 'animate', 'pbr_gen'):
        wm_attrs.append(f'mixie_{prefix}_generate_progress')
    for attr in wm_attrs:
        try:
            delattr(bpy.types.WindowManager, attr)
        except AttributeError:
            pass

    # Classes (reverse order)
    for cls in reversed(classes):
        try:
            unregister_class(cls)
        except RuntimeError:
            pass

    # Unregister lazily-registered edit state class
    try:
        from bpy.utils import unregister_class
        from .moodboard_edit_state import MoodboardEditToolState
        try:
            unregister_class(MoodboardEditToolState)
        except RuntimeError:
            pass
    except Exception:
        pass


# -- helpers ----------------------------------------------------------------

def _safe_scene_prop(name, prop):
    try:
        setattr(bpy.types.Scene, name, prop)
    except Exception as e:
        logger.error("Failed to register Scene.%s: %s", name, e)


def _safe_wm_prop(name, prop):
    try:
        setattr(bpy.types.WindowManager, name, prop)
    except Exception as e:
        logger.error("Failed to register WindowManager.%s: %s", name, e)
