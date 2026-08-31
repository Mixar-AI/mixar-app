# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D -- N-Panel UI

3D Viewport N-Panel with 5 toggle modes (Pro, Rapid, Part, Topology, UV).
Each mode has its own input form, independent job state, generate/cancel
buttons, progress bar, and result/error display.
"""

import bpy
from bpy.types import Panel

from ..constants import LIMITS


class MIXIE_PT_hunyuan(Panel):
    """Hunyuan 3D generation panel in the 3D Viewport N-Panel."""

    bl_label = "Hunyuan 3D"
    bl_idname = "MIXIE_PT_hunyuan"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Hunyuan"

    def draw(self, context):
        layout = self.layout
        props = context.scene.hunyuan

        # -- Mode toggle buttons --
        row = layout.row(align=True)
        for mode_id in ('PRO', 'RAPID', 'PART', 'TOPOLOGY', 'UV'):
            row.prop_enum(props, "active_mode", mode_id)

        layout.separator()

        # -- Active mode inputs --
        mode = props.active_mode
        mode_props = getattr(props, mode.lower())
        job = mode_props.job

        if mode == 'PRO':
            self._draw_pro(layout, props.pro, context)
        elif mode == 'RAPID':
            self._draw_rapid(layout, props.rapid, context)
        elif mode == 'PART':
            self._draw_part(layout, props.part, context)
        elif mode == 'TOPOLOGY':
            self._draw_topology(layout, props.topology, context)
        elif mode == 'UV':
            self._draw_uv(layout, props.uv, context)

        layout.separator()

        # -- Generate / Progress / Cancel --
        is_busy = job.status in ('SUBMITTING', 'POLLING', 'DOWNLOADING')

        if is_busy:
            box = layout.box()
            box.prop(job, "progress", text=job.progress_label, slider=True)
            op = box.operator(
                "mixie.hunyuan_cancel", text="Cancel", icon='CANCEL',
            )
            op.mode_override = mode
        else:
            can_generate = self._can_generate(mode, mode_props, context)
            row = layout.row()
            row.enabled = can_generate
            row.scale_y = 1.5
            op = row.operator(
                "mixie.hunyuan_generate", text="Generate", icon='PLAY',
            )
            op.mode_override = mode

        # -- Result (DONE) --
        if job.status == 'DONE':
            box = layout.box()
            box.label(
                text=f"Imported: {job.imported_object_name}",
                icon='CHECKMARK',
            )

        # -- Error (FAILED) --
        if job.status == 'FAILED':
            from mixar.modules.common.job_queue.core.error_helpers import sanitize_message
            box = layout.box()
            box.label(text="Error:", icon='ERROR')
            # Word-wrap long error messages
            words = sanitize_message(job.error_message).split()
            line = ""
            for w in words:
                if len(line) + len(w) > 40:
                    box.label(text=line)
                    line = w
                else:
                    line = f"{line} {w}" if line else w
            if line:
                box.label(text=line)

    # ====================================================================
    # VALIDATION
    # ====================================================================

    def _can_generate(self, mode, mode_props, context):
        """Check if Generate should be enabled for the active mode."""
        if mode == 'PRO':
            p = mode_props
            return (
                bool(p.prompt.strip())
                or (p.image is not None)
                or any(mv.image for mv in p.multi_views)
            )
        elif mode == 'RAPID':
            p = mode_props
            return bool(p.prompt.strip()) or (p.image is not None)
        elif mode in ('PART', 'TOPOLOGY', 'UV'):
            obj = context.active_object
            if not obj or obj.type != 'MESH':
                return False
            if mode in LIMITS:
                max_faces = LIMITS[mode].get('max_faces')
                if max_faces and len(obj.data.polygons) > max_faces:
                    return False
            return True
        return False

    # ====================================================================
    # PER-MODE DRAW METHODS
    # ====================================================================

    def _draw_pro(self, layout, pro, context):
        """Draw Pro mode inputs."""
        layout.prop(pro, "prompt", text="Prompt")
        layout.label(text="Max 1024 characters", icon='INFO')

        row = layout.row(align=True)
        row.prop(pro, "image", text="Image")
        row.operator("mixie.hunyuan_load_image", text="", icon='FILE_FOLDER')
        layout.label(text="Max 6MB (jpg/png/jpeg/webp)")

        # Multi-view section
        box = layout.box()
        box.label(text="Multi-View Images:")
        for i, mv in enumerate(pro.multi_views):
            row = box.row(align=True)
            row.prop(mv, "view_type", text="")
            row.prop(mv, "image", text="")
            op_load = row.operator(
                "mixie.hunyuan_load_image", text="", icon='FILE_FOLDER',
            )
            op_load.target = "multi_view"
            op_load.multi_view_index = i
            op_rm = row.operator(
                "mixie.hunyuan_remove_multi_view", text="", icon='X',
            )
            op_rm.index = i
        box.operator(
            "mixie.hunyuan_add_multi_view", text="Add View", icon='ADD',
        )
        box.label(text="Max 8MB each")

        layout.prop(pro, "model_version", text="Model")
        layout.prop(pro, "generate_type", text="Type")
        layout.prop(pro, "enable_pbr", text="Enable PBR")
        layout.prop(pro, "face_count", text="Face Count", slider=True)
        layout.label(text="Range: 40,000 - 1,500,000")

        if pro.generate_type == 'LowPoly':
            layout.prop(pro, "polygon_type", text="Polygon Type")

    def _draw_rapid(self, layout, rapid, context):
        """Draw Rapid mode inputs."""
        layout.prop(rapid, "prompt", text="Prompt")
        layout.label(text="Max 200 characters", icon='INFO')

        row = layout.row(align=True)
        row.prop(rapid, "image", text="Image")
        row.operator("mixie.hunyuan_load_image", text="", icon='FILE_FOLDER')
        layout.label(text="Max 6MB (jpg/png/jpeg/webp)")

        layout.prop(rapid, "result_format", text="Format")
        layout.prop(rapid, "enable_pbr", text="Enable PBR")
        layout.prop(rapid, "enable_geometry", text="Geometry Only")

    def _draw_part(self, layout, part, context):
        """Draw Part mode inputs."""
        self._draw_mesh_info(layout, context, max_faces=30000, max_mb=100)
        layout.prop(part, "export_format", text="Format")

    def _draw_topology(self, layout, topo, context):
        """Draw Topology mode inputs."""
        self._draw_mesh_info(layout, context, max_mb=200)
        layout.prop(topo, "export_format", text="Format")
        layout.prop(topo, "polygon_type", text="Polygon Type")
        layout.prop(topo, "face_level", text="Face Level")
        layout.prop(topo, "post_process", text="Post-Processing")

    def _draw_uv(self, layout, uv, context):
        """Draw UV mode inputs."""
        self._draw_mesh_info(layout, context, max_faces=30000, max_mb=100)
        layout.prop(uv, "export_format", text="Format")

    def _draw_mesh_info(self, layout, context, max_faces=None, max_mb=None):
        """Show selected mesh info with limit warnings."""
        obj = context.active_object
        if obj and obj.type == 'MESH':
            face_count = len(obj.data.polygons)
            layout.label(text=f"Mesh: {obj.name} ({face_count:,} faces)")

            # Limits info
            limits_parts = []
            if max_faces:
                limits_parts.append(f"{max_faces:,} faces")
            if max_mb:
                limits_parts.append(f"{max_mb}MB")
            if limits_parts:
                layout.label(
                    text=f"Limits: {' / '.join(limits_parts)}", icon='INFO',
                )

            # Warning if over face limit
            if max_faces and face_count > max_faces:
                layout.label(
                    text=(
                        f"Warning: {face_count:,} faces exceeds "
                        f"{max_faces:,} limit"
                    ),
                    icon='ERROR',
                )
        else:
            layout.label(text="No mesh selected", icon='ERROR')


# ============================================================================
# CLASS LIST (registered by bootstrap)
# ============================================================================

# Panel retired — all Hunyuan functionality is accessible from the moodboard sidebar
# (Generate > 3D Model / UV / Retopo / Segmentation tabs).
# Kept here so imports don't break; panel is simply no longer registered.
classes = ()
