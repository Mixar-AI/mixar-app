# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Properties UI State

PropertyGroup for managing collapsible section expansion states
in the Mixar UV Properties space.

Handler functions (timers, depsgraph, tool detection) live in properties_handlers.py.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty

from .properties_handlers import (
    _active_panel_update,
    _check_uv_sculpt_tool_change,
    _check_tool_and_refresh,
    register_handlers,
    unregister_handlers,
)


class MixarUVUIState(bpy.types.PropertyGroup):
    """UI state for Mixar UV Properties collapsible sections."""

    # Active panel selector (shown in UV editor header)
    # Note: Selection, Tools, Functions, and Transform are tool-based (no header buttons)
    # NONE is used when tool-based panels are active to hide enum-based panels
    active_panel: EnumProperty(
        name='Active Panel',
        description='Currently visible panel in UV Properties',
        items=[
            ('NONE', 'None', 'No panel selected (tool-based panel active)', 'BLANK1', -1),
            ('UV_SET', 'UV Set', 'UV Set panel', 'UV', 0),
            # 1 was PROJECTION — its content now lives in the Unwrap panel.
            ('UNWRAP', 'Unwrap', 'Unwrap and Project panel', 'UV_SYNC_SELECT', 2),
            ('TEXEL_DENSITY', 'Texel Density', 'Texel Density panel', 'TEXTURE', 3),
            ('PACK_ISLANDS', 'Layout', 'Layout panel', 'PACKAGE', 4),
            ('IMAGE', 'Image', 'Image panel', 'IMAGE_DATA', 5),
            ('MATERIAL_SLOT', 'Material Slot', 'Material Slot panel', 'MATERIAL', 6),
            ('EXPORT', 'Export', 'UV Export panel', 'EXPORT', 7),
        ],
        default='NONE',
        update=_active_panel_update
    )

    # UV Set sub-sections
    expand_uv_maps: BoolProperty(
        name='Expand UV Maps',
        description='Show UV Maps section expanded',
        default=True
    )

    expand_active_image: BoolProperty(
        name='Expand Active Image',
        description='Show Active Image section expanded',
        default=True
    )

    expand_udim_tiles: BoolProperty(
        name='Expand UDIM Tiles',
        description='Show UDIM Tiles section expanded',
        default=True
    )

    expand_image_settings: BoolProperty(
        name='Expand Image Settings',
        description='Show Image Settings section expanded',
        default=True
    )

    expand_grid: BoolProperty(
        name='Expand Grid',
        description='Show Grid section expanded',
        default=True
    )

    expand_uv_stretch: BoolProperty(
        name='Expand UV Stretch',
        description='Show UV Stretch section expanded',
        default=True
    )

    expand_uv_display: BoolProperty(
        name='Expand UV Display',
        description='Show UV Display section expanded',
        default=True
    )

    expand_image_info: BoolProperty(
        name='Expand Image Info',
        description='Show Image Info section expanded',
        default=True
    )

    # Unwrap method dropdown — includes Smart UV Project as a 4th method
    # alongside the three modes of `uv.unwrap`. Stored here (not on the
    # operator) because `uv.unwrap`'s enum does not expose SMART_PROJECT.
    unwrap_method: EnumProperty(
        name='Method',
        description='Unwrap method',
        items=[
            ('ANGLE_BASED', 'Angle Based',
             'Angle Based unwrap (uv.unwrap, method=ANGLE_BASED)'),
            ('CONFORMAL', 'Conformal',
             'Conformal unwrap (uv.unwrap, method=CONFORMAL)'),
            ('MINIMUM_STRETCH', 'Minimum Stretch',
             'Minimum Stretch unwrap (uv.unwrap, method=MINIMUM_STRETCH)'),
            ('SMART_PROJECT', 'Smart UV Project',
             'Smart UV Project (uv.smart_project)'),
        ],
        default='ANGLE_BASED',
    )

    # Projection type dropdown — one Type selector that switches the
    # property block shown in the Projection panel.
    projection_type: EnumProperty(
        name='Type',
        description='Projection type',
        items=[
            ('CUBE', 'Cube', 'Cube projection (uv.cube_project)'),
            ('CYLINDER', 'Cylinder', 'Cylinder projection (uv.cylinder_project)'),
            ('SPHERE', 'Sphere', 'Sphere projection (uv.sphere_project)'),
            ('CAMERA', 'Camera Based', 'Camera-based projection (mixar.camera_project)'),
            ('NORMAL', 'Normal Based', 'Normal-based projection (mixar.normal_project)'),
            ('PLANAR', 'Planar', 'Planar projection (mixar.planar_project)'),
        ],
        default='CUBE',
    )

    # Snapping sub-sections
    expand_snapping_options: BoolProperty(
        name='Expand Snapping Options',
        description='Show Snapping options section expanded',
        default=True
    )

    expand_snap_operations: BoolProperty(
        name='Expand Snap Operations',
        description='Show Snap operations section expanded',
        default=True
    )

    # Tools sub-sections
    expand_tool_falloff: BoolProperty(
        name='Expand Tool Falloff',
        description='Show Falloff section expanded',
        default=False
    )

    expand_tool_options: BoolProperty(
        name='Expand Tool Options',
        description='Show Options section expanded',
        default=True
    )

    # Functions sub-sections
    expand_stitch_options: BoolProperty(
        name='Expand Stitch Options',
        description='Show Stitch options section expanded',
        default=True
    )

    # UV Cursor position properties (for Transform panel)
    def _update_cursor_x(self, context):
        """Update UV cursor X position in IMAGE_EDITOR"""
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    sima.cursor_location[0] = self.cursor_x
                    area.tag_redraw()
                    break
    
    def _update_cursor_y(self, context):
        """Update UV cursor Y position in IMAGE_EDITOR"""
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    sima.cursor_location[1] = self.cursor_y
                    area.tag_redraw()
                    break
    
    cursor_x: bpy.props.FloatProperty(
        name='Cursor X',
        description='2D Cursor X position in UV editor',
        default=0.0,
        update=_update_cursor_x
    )
    
    cursor_y: bpy.props.FloatProperty(
        name='Cursor Y',
        description='2D Cursor Y position in UV editor',
        default=0.0,
        update=_update_cursor_y
    )
    
    # Transform Move properties (for Transform panel)
    def _update_move_x(self, context):
        """Update UV move X in real-time"""
        # Prevent recursive updates
        if getattr(self, '_updating_move', False):
            return
        
        area = None
        for a in context.screen.areas:
            if a.type == 'IMAGE_EDITOR':
                sima = a.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    area = a
                    break
        
        if area:
            # Get the WINDOW region
            region = None
            for r in area.regions:
                if r.type == 'WINDOW':
                    region = r
                    break
            
            if region:
                # Apply the move transform
                with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                    bpy.ops.transform.translate(value=(self.move_x, 0.0, 0.0), orient_type='GLOBAL', constraint_axis=(False, False, False))
                
                # Reset to 0 after applying (prevent recursive call)
                self._updating_move = True
                self.property_unset("move_x")
                self._updating_move = False
                
                # Redraw
                area.tag_redraw()
    
    def _update_move_y(self, context):
        """Update UV move Y in real-time"""
        # Prevent recursive updates
        if getattr(self, '_updating_move', False):
            return
        
        area = None
        for a in context.screen.areas:
            if a.type == 'IMAGE_EDITOR':
                sima = a.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    area = a
                    break
        
        if area:
            # Get the WINDOW region
            region = None
            for r in area.regions:
                if r.type == 'WINDOW':
                    region = r
                    break
            
            if region:
                # Apply the move transform
                with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                    bpy.ops.transform.translate(value=(0.0, self.move_y, 0.0), orient_type='GLOBAL', constraint_axis=(False, False, False))
                
                # Reset to 0 after applying (prevent recursive call)
                self._updating_move = True
                self.property_unset("move_y")
                self._updating_move = False
                
                # Redraw
                area.tag_redraw()
    
    move_x: bpy.props.FloatProperty(
        name='Move X',
        description='Move selected UVs in X direction (incremental)',
        default=0.0,
        update=_update_move_x
    )
    
    move_y: bpy.props.FloatProperty(
        name='Move Y',
        description='Move selected UVs in Y direction (incremental)',
        default=0.0,
        update=_update_move_y
    )
    
    # Transform Scale properties (for Transform panel)
    def _update_scale_x(self, context):
        """Update UV scale X in real-time"""
        # Prevent recursive updates
        if getattr(self, '_updating_scale', False):
            return
        
        area = None
        for a in context.screen.areas:
            if a.type == 'IMAGE_EDITOR':
                sima = a.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    area = a
                    break
        
        if area:
            # Get the WINDOW region
            region = None
            for r in area.regions:
                if r.type == 'WINDOW':
                    region = r
                    break
            
            if region:
                # Apply the scale transform
                with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                    bpy.ops.transform.resize(value=(self.scale_x, 1.0, 1.0), orient_type='GLOBAL', constraint_axis=(False, False, False))
                
                # Reset to 1.0 after applying (prevent recursive call)
                self._updating_scale = True
                self.property_unset("scale_x")
                self._updating_scale = False
                
                # Redraw
                area.tag_redraw()
    
    def _update_scale_y(self, context):
        """Update UV scale Y in real-time"""
        # Prevent recursive updates
        if getattr(self, '_updating_scale', False):
            return
        
        area = None
        for a in context.screen.areas:
            if a.type == 'IMAGE_EDITOR':
                sima = a.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    area = a
                    break
        
        if area:
            # Get the WINDOW region
            region = None
            for r in area.regions:
                if r.type == 'WINDOW':
                    region = r
                    break
            
            if region:
                # Apply the scale transform
                with context.temp_override(area=area, region=region, space_data=area.spaces.active):
                    bpy.ops.transform.resize(value=(1.0, self.scale_y, 1.0), orient_type='GLOBAL', constraint_axis=(False, False, False))
                
                # Reset to 1.0 after applying (prevent recursive call)
                self._updating_scale = True
                self.property_unset("scale_y")
                self._updating_scale = False
                
                # Redraw
                area.tag_redraw()
    
    scale_x: bpy.props.FloatProperty(
        name='Scale X',
        description='Scale selected UVs in X direction (incremental)',
        default=1.0,
        update=_update_scale_x
    )
    
    scale_y: bpy.props.FloatProperty(
        name='Scale Y',
        description='Scale selected UVs in Y direction (incremental)',
        default=1.0,
        update=_update_scale_y
    )


classes = (MixarUVUIState,)


def register():
    """Register UV UI properties."""
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register on WindowManager for panel access
    bpy.types.WindowManager.mixar_uv_ui = PointerProperty(type=MixarUVUIState)

    # Register handlers (depsgraph + timer) from properties_handlers module
    register_handlers()


def unregister():
    """Unregister UV UI properties."""
    # Unregister handlers (depsgraph + timer) from properties_handlers module
    unregister_handlers()

    if hasattr(bpy.types.WindowManager, 'mixar_uv_ui'):
        del bpy.types.WindowManager.mixar_uv_ui

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
