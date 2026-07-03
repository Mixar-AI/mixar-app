# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Generative Sidebar Panels — Native N-Panel System

Independent Panel classes, each registered under its own bl_category
so they appear as separate vertical tabs in the sidebar — just like
Item / Tool / View in the 3D Viewport N-panel.
"""

from bpy.types import Panel

from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE
from mixar.config.logging_config import get_logger

from .sidebar_panel_drawers import (
    _draw_imagegen,
    _draw_blockout_to_render,
    _draw_lookdev360,
    _draw_image_to_3d,
    _draw_scene_recon,
    _draw_scene_gen_exp,
    _draw_segmentation,
    _draw_queue,
)
from .sidebar_tab_drawers import _draw_retopology

logger = get_logger(__name__)


def _moodboard_poll(context):
    """Shared poll: require MIXIE space in MOODBOARD mode."""
    if not MIXIE_SPACE_AVAILABLE:
        return False
    smixie = context.space_data
    return smixie and hasattr(smixie, 'mixie_mode') and smixie.mixie_mode == 'MOODBOARD'


def _safe_draw(drawer, layout, context):
    """Call a drawer function with error handling."""
    try:
        drawer(layout, context)
    except Exception as e:
        logger.exception("Panel drawer raised an exception")
        layout.label(text=f"Error: {e}", icon='ERROR')


# ---------------------------------------------------------------------------
# Panel classes — each bl_category = separate vertical tab
# ---------------------------------------------------------------------------

class MIXIE_PT_gen_imagegen(Panel):
    bl_label = "Generate Image"
    bl_idname = "MIXIE_PT_gen_imagegen"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Image Gen"
    bl_order = 10  # 1. Image generation
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='IMAGE_DATA')

    def draw(self, context):
        _safe_draw(_draw_imagegen, self.layout, context)


class MIXIE_PT_gen_blockout_to_render(Panel):
    bl_label = "Blockout to Render"
    bl_idname = "MIXIE_PT_gen_blockout_to_render"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Blockout"
    bl_order = 70  # 7. Blockout
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='SHADING_RENDERED')

    def draw(self, context):
        _safe_draw(_draw_blockout_to_render, self.layout, context)


class MIXIE_PT_gen_lookdev360(Panel):
    bl_label = "Generate PBR Maps"
    bl_idname = "MIXIE_PT_gen_lookdev360"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PBR Maps"
    bl_order = 50  # 5. PBR Maps
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='SPHERE')

    def draw(self, context):
        _safe_draw(_draw_lookdev360, self.layout, context)


class MIXIE_PT_gen_image_to_3d(Panel):
    bl_label = "Image to 3D"
    bl_idname = "MIXIE_PT_gen_image_to_3d"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Image to 3D"
    bl_order = 20  # 2. Image to 3D
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='VIEW3D')

    def draw(self, context):
        _safe_draw(_draw_image_to_3d, self.layout, context)


class MIXIE_PT_gen_scene_recon(Panel):
    bl_label = "Generate Scene"
    bl_idname = "MIXIE_PT_gen_scene_recon"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Scene"
    bl_order = 40  # 4. Scene
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='SCENE_DATA')

    def draw(self, context):
        _safe_draw(_draw_scene_recon, self.layout, context)


class MIXIE_PT_gen_retopology(Panel):
    bl_label = "Retopology"
    bl_idname = "MIXIE_PT_gen_retopology"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Retopology"
    bl_order = 30  # 3. Retopology
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_REMESH')

    def draw(self, context):
        _safe_draw(_draw_retopology, self.layout, context)


class MIXIE_PT_gen_scene_gen_exp(Panel):
    bl_label = "Scene Gen Experimental"
    bl_idname = "MIXIE_PT_gen_scene_gen_exp"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Scene Gen Exp"
    bl_order = 45
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='EXPERIMENTAL')

    def draw(self, context):
        _safe_draw(_draw_scene_gen_exp, self.layout, context)


class MIXIE_PT_gen_segmentation(Panel):
    bl_label = "Segmentation"
    bl_idname = "MIXIE_PT_gen_segmentation"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Segment"
    bl_order = 60  # 6. Segment
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_MASK')

    def draw(self, context):
        _safe_draw(_draw_segmentation, self.layout, context)


class MIXIE_PT_gen_queue(Panel):
    bl_label = "Queue"
    bl_idname = "MIXIE_PT_gen_queue"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Queue"
    bl_order = 80

    @classmethod
    def poll(cls, context):
        return _moodboard_poll(context)

    def draw_header(self, context):
        self.layout.label(text="", icon='LINENUMBERS_ON')

    def draw(self, context):
        _safe_draw(_draw_queue, self.layout, context)


# Only register if MIXIE space is available.
classes = (
    MIXIE_PT_gen_imagegen,
    MIXIE_PT_gen_blockout_to_render,
    MIXIE_PT_gen_lookdev360,
    MIXIE_PT_gen_image_to_3d,
    MIXIE_PT_gen_scene_recon,
    # MIXIE_PT_gen_scene_gen_exp,  # Scene Gen Experimental disabled
    MIXIE_PT_gen_retopology,
    MIXIE_PT_gen_segmentation,
    MIXIE_PT_gen_queue,
) if MIXIE_SPACE_AVAILABLE else ()
