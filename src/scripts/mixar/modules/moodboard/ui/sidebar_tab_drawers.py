# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Sidebar Tab Drawers — Segment to 3D, Mesh Segment & Hunyuan

Inline drawer functions for tabs that were previously popup-only or
lived in a separate space. Called from sidebar panel drawers.
"""

from mixar.modules.hunyuan.constants import LIMITS
from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_hint, draw_moodboard_image_toggle, draw_mesh_info,
    draw_generate_footer, draw_hunyuan_generate_footer,
    get_selected_moodboard_image, draw_dropdown, draw_toggle,
    draw_status_badge, draw_image_info_card,
)
from mixar.modules.moodboard.constants import SEP_INTRA, GENERATE_BUTTON_SCALE_Y


# ---------------------------------------------------------------------------
# Segment to 3D
# ---------------------------------------------------------------------------

def _draw_segment_to_3d(layout, context):
    """Draw Segment to 3D tab — inline version of the popup dialog."""
    scene = context.scene
    state = scene.mixie_edit_tool_state

    # Find first selected moodboard image
    selected_idx = -1
    selected_item = None
    if hasattr(scene, 'mixie_moodboard_images'):
        for i, img_item in enumerate(scene.mixie_moodboard_images):
            if img_item.selected and img_item.image:
                selected_idx = i
                selected_item = img_item
                break

    if selected_idx < 0 or not selected_item:
        box = layout.box()
        box.label(text="No image selected", icon='INFO')
        return

    # Source image
    draw_image_info_card(layout, selected_item.image)

    # Box Select SAM section
    if state.box_select_has_selection or state.box_select_pending:
        sam_box = layout.box()
        sam_box.label(text="Box Selection:", icon='SELECT_SET')
        if state.box_select_pending:
            draw_status_badge(sam_box, "Processing...", 'GENERATING')
        else:
            row = sam_box.row()
            row.scale_y = GENERATE_BUTTON_SCALE_Y
            row.operator("mixie.box_select_sam", text="Identify and select", icon='MOD_MASK')

    # Lasso Select SAM section
    if state.lasso_select_has_selection or state.lasso_select_pending:
        sam_box = layout.box()
        sam_box.label(text="Lasso Selection:", icon='OUTLINER_DATA_GP_LAYER')
        if state.lasso_select_pending:
            draw_status_badge(sam_box, "Refining...", 'GENERATING')
        else:
            row = sam_box.row()
            row.scale_y = GENERATE_BUTTON_SCALE_Y
            row.operator("mixie.lasso_select_sam", text="Refine selection", icon='MOD_MASK')

    draw_section_separator(layout)

    # Segments list
    num_segments = len(selected_item.segments)
    if num_segments == 0:
        box = layout.box()
        box.label(text="No segments yet", icon='INFO')
        box.label(text="Use selection tools to create segments")
    else:
        col = draw_section_box(layout, f"Segments ({num_segments})", icon='MOD_MASK')
        for i, segment in enumerate(selected_item.segments):
            row = col.row(align=True)
            icon = 'CHECKBOX_HLT' if segment.active else 'CHECKBOX_DEHLT'
            op = row.operator("mixie.toggle_segment", text="", icon=icon, emboss=False)
            op.image_index = selected_idx
            op.segment_index = i
            row.label(text=segment.name)
            op = row.operator("mixie.delete_segment", text="", icon='X')
            op.image_index = selected_idx
            op.segment_index = i

        active_count = sum(1 for s in selected_item.segments if s.active)
        if active_count > 0:
            col.separator(factor=SEP_INTRA)
            draw_status_badge(col, f"{active_count} segment(s) active", 'DONE')

    from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN
    draw_generate_footer(layout, context, "mixie.generate_scene", "segment_to_3d",
                         cancel_op="mixie.cancel_segment_to_3d",
                         feature_key=FEATURE_SCENE_GEN)


# ---------------------------------------------------------------------------
# Mesh Segment
# ---------------------------------------------------------------------------

def _mesh_segment_catalog_ready():
    """True when the catalog has mesh_segmentation services."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        return is_loaded() and bool(get_services("mesh_segmentation"))
    except Exception:
        return False


def _draw_mesh_segment(layout, context):
    """Draw Mesh Segment tab.

    Catalog-driven mode selector (Mesh Segmentation = ``mesh_segment`` /
    Part Segmentation = ``hunyuan_part``) when the generation catalog is
    loaded; the legacy mesh_segment-only UI otherwise. The
    ``hunyuan_part`` mode reuses the PART_SEGMENT tab's existing
    submission flow (scene.hunyuan.part + ``mixie.hunyuan_generate``).
    """
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_mesh_segment

    service_key = "mesh_segment"
    catalog_ready = _mesh_segment_catalog_ready()
    if catalog_ready:
        from mixar.modules.common.generation_params import (
            draw_capability_selector, resolve_service_key,
        )
        service_key = resolve_service_key(
            "mesh_segmentation", getattr(tab, "mode", "")
        ) or "mesh_segment"

        col = draw_section_box(layout, "Settings", icon='SETTINGS')
        col.use_property_split = True
        col.use_property_decorate = False
        draw_capability_selector(col, tab, "mesh_segmentation")
        draw_section_separator(layout)

    if service_key == "hunyuan_part":
        # Part Segmentation — same inputs + submit flow as PART_SEGMENT.
        if not hasattr(scene, 'hunyuan'):
            layout.label(text="Hunyuan not initialized", icon='ERROR')
            return
        part = scene.hunyuan.part

        col = draw_section_box(layout, "Mesh Info", icon='MESH_DATA')
        draw_mesh_info(col, context, max_faces=30000, max_mb=100)
        draw_section_separator(layout)

        col = draw_section_box(layout, "Export", icon='EXPORT')
        draw_dropdown(col, part, "export_format", text="Format")

        draw_hunyuan_generate_footer(
            layout, context, part.job, 'PART',
            lambda: _mesh_can_generate(context, 'PART'),
        )
        return

    # Mesh Segmentation (default) — existing inputs + submit flow.
    draw_prompt_section(layout, tab, label="Description")
    draw_section_separator(layout)

    col = draw_section_box(
        layout, "Inputs" if catalog_ready else "Settings", icon='SETTINGS')
    col.prop(tab, "expected_parts", text="Expected Parts")

    draw_generate_footer(
        layout, context, "mixie.mesh_segment_submit", "mesh_segment",
        gen_flag_attr='mixie_mesh_segment_is_processing',
        cancel_op="mixie.mesh_segment_cancel",
        feature_key="mesh_segment",
    )


# ---------------------------------------------------------------------------
# Hunyuan shared input drawers
# ---------------------------------------------------------------------------

def _draw_hunyuan_pro(layout, pro, context=None):
    """Draw Pro mode inputs."""
    # --- Prompt ---
    draw_prompt_section(layout, pro)
    draw_section_separator(layout)

    # --- Input image ---
    col = draw_section_box(
        layout,
        "Input Image",
        icon='IMAGE_DATA',
        action_op="mixie.hunyuan_load_image",
    )

    if context and hasattr(pro, 'use_selected_image'):
        draw_moodboard_image_toggle(col, pro, context, multi=True)

    if not getattr(pro, 'use_selected_image', False):
        for i, entry in enumerate(pro.uploaded_images):
            if entry.image:
                draw_image_info_card(
                    col, entry.image,
                    remove_op="mixie.hunyuan_remove_uploaded_image",
                    remove_op_props={"index": i},
                )

    draw_section_separator(layout)

    col = draw_section_box(layout, "Multi-View Images", icon='RENDERLAYERS')
    for i, mv in enumerate(pro.multi_views):
        row = col.row(align=True)
        draw_dropdown(row, mv, "view_type", text="")
        # template_ID (not prop) so hovering an existing image in the
        # browse dropdown shows Blender's rich preview tooltip — see the
        # matching note in model_gen_drawer._draw_multi_view_section.
        row.template_ID(mv, "image")
        op_load = row.operator("mixie.hunyuan_load_image", text="", icon='FILE_FOLDER')
        op_load.target = "multi_view"
        op_load.multi_view_index = i
        op_rm = row.operator("mixie.hunyuan_remove_multi_view", text="", icon='X')
        op_rm.index = i
    col.operator("mixie.hunyuan_add_multi_view", text="Add View", icon='ADD')
    draw_hint(col, "Max 8MB each")

    draw_section_separator(layout)

    # --- Settings ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    draw_dropdown(col, pro, "model_version", text="Model")
    draw_dropdown(col, pro, "generate_type", text="Type")
    draw_toggle(col, pro, "enable_pbr", text="Enable PBR")
    col.prop(pro, "face_count", text="Face Count", slider=True)
    draw_hint(col, "Range: 40,000 - 1,500,000")
    if pro.generate_type == 'LowPoly':
        draw_dropdown(col, pro, "polygon_type", text="Polygon Type")


def _mesh_can_generate(context, mode):
    """Check if a mesh-based Hunyuan mode can generate."""
    selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
    if not selected_meshes:
        return False
    if mode in LIMITS:
        max_faces = LIMITS[mode].get('max_faces')
        if max_faces:
            total_faces = sum(len(o.data.polygons) for o in selected_meshes)
            if total_faces > max_faces:
                return False
    return True


# ---------------------------------------------------------------------------
# UV Unwrap (standalone tab)
# ---------------------------------------------------------------------------

def _draw_uv_unwrap(layout, context):
    """Draw standalone UV Unwrap tab — uses scene.hunyuan.uv properties.

    The catalog Model dropdown + schema params (capability
    ``uv_unwrapping``, single service — Mode dropdown hidden) are drawn
    when the generation catalog is loaded; the mesh-export inputs and the
    hunyuan submit flow are unchanged either way.
    """
    if not hasattr(context.scene, 'hunyuan'):
        layout.label(text="Hunyuan not initialized", icon='ERROR')
        return

    scene = context.scene
    props = scene.hunyuan
    uv = props.uv
    job = uv.job

    col = draw_section_box(layout, "Mesh Info", icon='MESH_DATA')
    draw_mesh_info(col, context, max_faces=30000, max_mb=100)
    draw_section_separator(layout)

    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    draw_dropdown(col, uv, "export_format", text="Format")

    # Catalog Model dropdown + schema params (no-op when not loaded).
    sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
    tab = getattr(sidebar, 'tab_uv_unwrap', None) if sidebar else None
    if tab is not None:
        try:
            from mixar.modules.common.generation_params import (
                draw_capability_selector,
            )
            draw_capability_selector(col, tab, "uv_unwrapping")
        except Exception:
            pass

    draw_hunyuan_generate_footer(
        layout, context, job, 'UV',
        lambda: _mesh_can_generate(context, 'UV'),
    )


# ---------------------------------------------------------------------------
# Retopology (standalone tab)
# ---------------------------------------------------------------------------

def _draw_retopology(layout, context):
    """Draw standalone Retopology tab.

    Catalog-driven UI (mode selector + schema params) when the generation
    catalog is loaded; the legacy ``scene.hunyuan.topology`` UI otherwise
    so the tab never goes blank offline / pre-auth. Retopology is
    queue-driven (one job per selected mesh) in both paths.
    """
    from .retopology_drawer import (
        _draw_retopology_catalog, _retopology_catalog_ready,
    )

    if _retopology_catalog_ready():
        _draw_retopology_catalog(layout, context)
        return

    # --- Legacy fallback (catalog not loaded) ---
    if not hasattr(context.scene, 'hunyuan'):
        layout.label(text="Hunyuan not initialized", icon='ERROR')
        return

    props = context.scene.hunyuan
    topo = props.topology
    is_tripo = topo.model == 'tripo'

    col = draw_section_box(layout, "Mesh Info", icon='MESH_DATA')
    draw_mesh_info(col, context, max_mb=150 if is_tripo else 200)
    draw_hint(layout, "Select the objects you want to retopologize", icon='INFO')
    draw_section_separator(layout)

    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    draw_dropdown(col, topo, "model", text="Model")
    if is_tripo:
        col.label(text="Algorithm: v2.0 (Smart)")
        col.prop(topo, "tripo_face_limit", text="Face Limit", slider=True)
        col.prop(topo, "tripo_quad", text="Quad Mesh")
        col.prop(topo, "tripo_bake", text="Bake Textures")
        face_range = "500-10,000 (quad)" if topo.tripo_quad else "500-20,000 (tri)"
        info = draw_section_box(layout, "About Tripo Retopology", icon='INFO')
        draw_hint(info, "v2.0 smart highpoly to lowpoly", icon='DOT')
        draw_hint(info, "Max mesh: 150 MB", icon='DOT')
        draw_hint(info, "Formats: GLB / GLTF / FBX / OBJ / STL", icon='DOT')
        draw_hint(info, f"Face Limit range: {face_range}", icon='DOT')
        draw_hint(info, "Bake transfers textures to the low-poly", icon='DOT')
    else:
        draw_dropdown(col, topo, "polygon_type", text="Polygon Type")
        draw_dropdown(col, topo, "face_level", text="Face Level")
        col.prop(topo, "post_process", text="Post-Processing")

    from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY
    from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
        draw_queue_generate_footer,
    )

    draw_queue_generate_footer(
        layout, context, FEATURE_RETOPOLOGY,
        lambda: _mesh_can_generate(context, 'TOPOLOGY'),
        mode_override='TOPOLOGY',
    )


# ---------------------------------------------------------------------------
# Image to 3D — Pro subtab
# ---------------------------------------------------------------------------

def _draw_image_to_3d_pro(layout, context):
    """Draw Pro subtab inside Image to 3D — uses scene.hunyuan.pro.

    Pro mode is queue-driven (not via the singleton ``pro.job``), so the
    standard hunyuan generate footer is replaced with the queue footer
    and a collapsible "Generation Queue" panel is appended.
    """
    if not hasattr(context.scene, 'hunyuan'):
        layout.label(text="Hunyuan not initialized", icon='ERROR')
        return

    pro = context.scene.hunyuan.pro
    _draw_hunyuan_pro(layout, pro, context)

    def _can_gen():
        if getattr(pro, 'use_selected_image', False):
            return get_selected_moodboard_image(context) is not None
        return (
            bool(pro.prompt.strip())
            or any(e.image for e in pro.uploaded_images)
            or any(mv.image for mv in pro.multi_views)
        )

    from mixar.modules.common.job_queue.constants import (
        FEATURE_IMAGE_TO_3D_PRO,
    )
    from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
        draw_queue_generate_footer,
    )

    draw_queue_generate_footer(
        layout, context, FEATURE_IMAGE_TO_3D_PRO, _can_gen,
    )
