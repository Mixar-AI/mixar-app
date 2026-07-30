# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Sidebar UI Helpers — Shared section-building functions.

Provides a consistent visual language for all moodboard sidebar tabs:
boxed sections with labeled headers, uniform separators, hint labels,
and standardized generate-button footers.
"""

from mixar.modules.moodboard.constants import (
    GENERATE_BUTTON_SCALE_Y,
    SEP_SECTION,
    SEP_INTRA,
    SEP_FOOTER,
    HINT_SCALE_Y,
)
from mixar.modules.common.utils.ui_utils import draw_multiline_text_input


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def draw_section_box(layout, label=None, icon='NONE', action_op=None,
                     action_icon='FILE_FOLDER'):
    """Create a styled section box, return an aligned column.

    Uses the custom Mixar section widget (C++ rendered, accent border + shadow)
    when available, falls back to standard box() otherwise.
    """
    if hasattr(layout, 'mixar_section'):
        box = layout.mixar_section()
    else:
        box = layout.box()
    col = box.column()
    if label:
        if action_op:
            row = col.row(align=True)
            row.label(text=label, icon=icon)
            row.operator(action_op, text="", icon=action_icon)
        else:
            col.label(text=label, icon=icon)
        col.separator(factor=SEP_INTRA)
    return col


def draw_section_separator(layout):
    """Standard separator between major sections."""
    layout.separator(factor=SEP_SECTION)


def draw_dropdown(layout, data, prop, text=""):
    """Draw an enum property using the Mixar styled dropdown when available."""
    if hasattr(layout, 'mixar_dropdown'):
        layout.mixar_dropdown(data, prop, text=text)
    else:
        layout.prop(data, prop, text=text)


def draw_toggle(layout, data, prop, text=""):
    """Draw a boolean property using the Mixar pill toggle when available."""
    if hasattr(layout, 'mixar_toggle'):
        layout.mixar_toggle(data, prop, text=text)
    else:
        layout.prop(data, prop, text=text)


def draw_input(layout, data, prop, text=""):
    """Draw a text property using the Mixar styled input when available."""
    if hasattr(layout, 'mixar_input'):
        layout.mixar_input(data, prop, text=text)
    else:
        layout.prop(data, prop, text=text)


def draw_hint(col, text, icon='NONE'):
    """Subtle, smaller-scale info label drawn inside a parent column."""
    row = col.row()
    row.scale_y = HINT_SCALE_Y
    row.label(text=text, icon=icon)


# ---------------------------------------------------------------------------
# Sidebar tab focus
# ---------------------------------------------------------------------------

def focus_scene_gen_segments(context):
    """Surface the Scene Gen tab's Segments to 3D mode.

    Used by the moodboard segmentation tools (magic select, box/lasso
    mask) so their results are visible where the Generate button lives.
    Switches the sidebar to the "Scene Gen" panel category and selects
    the ``scene_gen`` mode when the catalog is loaded (the mode enum item
    doesn't exist offline — silently skipped). Never raises.
    """
    scene = context.scene
    sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
    if sidebar is not None and hasattr(sidebar, 'tab_scene_recon'):
        try:
            sidebar.tab_scene_recon.mode = 'scene_gen'
        except Exception:
            pass  # catalog not loaded / capability disabled
    try:
        space = context.space_data
        if hasattr(space, 'show_region_ui'):
            space.show_region_ui = True
        area = context.area
        region = next(
            (r for r in area.regions if r.type == 'UI'), None,
        ) if area else None
        if region and hasattr(region, 'active_panel_category'):
            region.active_panel_category = "Scene Gen"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Prompt section
# ---------------------------------------------------------------------------

def draw_prompt_section(layout, prop_owner, label="Prompt",
                        icon='TEXT', action_op=None, action_icon='FILE_FOLDER',
                        min_lines=2, max_lines=5):
    """Boxed prompt input with label and optional action button. Returns col."""
    box = layout.mixar_section() if hasattr(layout, 'mixar_section') else layout.box()
    col = box.column()
    col.label(text=label, icon=icon)

    if action_op:
        row = col.row(align=True)
        sub = row.column(align=True)
        draw_multiline_text_input(sub, prop_owner, "prompt",
                                  min_lines=min_lines, max_lines=max_lines)
        row.operator(action_op, text="", icon=action_icon)
    else:
        draw_multiline_text_input(col, prop_owner, "prompt",
                                  min_lines=min_lines, max_lines=max_lines)
    return col


# ---------------------------------------------------------------------------
# Moodboard image selection
# ---------------------------------------------------------------------------

def get_selected_moodboard_image(context):
    """Return first selected moodboard image or None."""
    scene = context.scene
    if hasattr(scene, 'mixie_moodboard_images'):
        for item in scene.mixie_moodboard_images:
            if item.selected and item.image:
                return item.image
    return None


def get_image_to_3d_input_image(context):
    """Return the image the Model Gen tab currently treats as its input.

    The selected moodboard image when "Use Selected Moodboard Image" is on,
    the explicit reference image otherwise. Single source of truth so the
    sidebar button gating and the operator that runs never disagree about
    which image is about to be used.
    """
    scene = context.scene
    sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
    tab = getattr(sidebar, 'tab_image_to_3d', None) if sidebar else None

    if tab is not None and not getattr(tab, 'use_selected_image', False):
        return getattr(tab, 'reference_image', None)
    return get_selected_moodboard_image(context)


def draw_moodboard_image_toggle(col, prop_owner, context, *, multi=False):
    """Draw 'Use Selected Moodboard Image' toggle + status.

    Draws flat into the caller's column — no extra box wrapper.
    When *multi* is False (default) only the first selected image is shown
    and used — matching the operator behaviour that takes ``selected[0]``.
    Pass *multi=True* for panels (e.g. Image to 3D Pro) that accept
    multiple selected moodboard images.
    """
    from mixar.modules.common.utils.mixie_space_utils import (
        get_first_selected_moodboard_image,
        count_selected_moodboard_images,
    )
    if multi:
        count = count_selected_moodboard_images(context.scene)
        label = f"Use Selected Moodboard Image ({count})" if count > 0 else "Use Selected Moodboard Image"
    else:
        first_img = get_first_selected_moodboard_image(context.scene)
        label = "Use Selected Moodboard Image (1)" if first_img else "Use Selected Moodboard Image"
    draw_toggle(col, prop_owner, "use_selected_image", text=label)
    if prop_owner.use_selected_image:
        if multi:
            shown = 0
            scene = context.scene
            if hasattr(scene, 'mixie_moodboard_images'):
                for item in scene.mixie_moodboard_images:
                    if item.selected and item.image:
                        draw_image_info_card(col, item.image)
                        shown += 1
            if shown == 0:
                row = col.row()
                row.label(text="No image selected in moodboard", icon='ERROR')
        else:
            first_img = get_first_selected_moodboard_image(context.scene)
            if first_img:
                draw_image_info_card(col, first_img)
            else:
                row = col.row()
                row.label(text="No image selected in moodboard", icon='ERROR')


# ---------------------------------------------------------------------------
# Mesh info (Hunyuan mesh-based tabs)
# ---------------------------------------------------------------------------

def draw_mesh_info(col, context, max_faces=None, max_mb=None):
    """Mesh name, face count, and limit warnings inside caller's column."""
    selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
    if selected_meshes:
        total_faces = sum(len(o.data.polygons) for o in selected_meshes)
        if len(selected_meshes) == 1:
            col.label(text=f"Mesh: {selected_meshes[0].name} ({total_faces:,} faces)")
        else:
            col.label(text=f"{len(selected_meshes)} meshes ({total_faces:,} faces)")

        limits_parts = []
        if max_faces:
            limits_parts.append(f"{max_faces:,} faces")
        if max_mb:
            limits_parts.append(f"{max_mb}MB")
        if limits_parts:
            draw_hint(col, f"Limits: {' / '.join(limits_parts)}", icon='INFO')

        if max_faces and total_faces > max_faces:
            col.label(
                text=f"Warning: {total_faces:,} faces exceeds {max_faces:,} limit",
                icon='ERROR',
            )
    else:
        col.label(text="No mesh selected", icon='ERROR')


# ---------------------------------------------------------------------------
# Status badges
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    'GENERATING': 'TIME',
    'DONE': 'CHECKMARK',
    'ERROR': 'ERROR',
    'INFO': 'INFO',
}


def draw_status_badge(layout, text, status='INFO'):
    """Draw a compact status badge with icon.

    Status maps: GENERATING -> TIME, DONE -> CHECKMARK, ERROR -> ERROR, INFO -> INFO.
    Uses row.alert for error states (turns box red in Blender).
    """
    icon = _STATUS_ICONS.get(status, 'INFO')
    box = layout.box()
    row = box.row(align=True)
    row.scale_y = 0.85
    if status == 'ERROR':
        row.alert = True
    row.label(text=text, icon=icon)


def draw_styled_progress(layout, data, prop, text="Generating..."):
    """Wrap a progress slider in a styled box."""
    if hasattr(layout, 'mixar_section'):
        box = layout.mixar_section()
    else:
        box = layout.box()
    row = box.row()
    row.enabled = False
    row.prop(data, prop, text=text, slider=True)


# ---------------------------------------------------------------------------
# Image thumbnails
# ---------------------------------------------------------------------------

def _get_preview_icon_id(image):
    """Return the preview icon_id for a Blender image, ensuring it exists."""
    if not image:
        return 0
    # preview_ensure() must be called before .preview is usable —
    # without it, .preview may be None even for loaded images.
    image.preview_ensure()
    if image.preview:
        return image.preview.icon_id or 0
    return 0


def draw_image_thumbnail(layout, image, scale=3.0):
    """Draw an image preview thumbnail using Blender's template_icon.

    Returns True if a thumbnail was drawn, False if fallback label was used.
    """
    icon_id = _get_preview_icon_id(image)
    if icon_id:
        layout.template_icon(icon_value=icon_id, scale=scale)
        return True
    layout.label(text=image.name if image else "No image", icon='IMAGE_DATA')
    return False


def draw_image_info_card(layout, image, remove_op=None, remove_op_props=None,
                         display_name=None, display_resolution=None):
    """Draw a compact image card with preview icon, name, resolution, and remove button.

    Args:
        layout: Parent layout.
        image: Blender Image datablock (or None).
        remove_op: Optional operator idname for the X button.
        remove_op_props: Optional dict of properties to set on the remove operator.
        display_name: Override name (falls back to image.name).
        display_resolution: Override resolution string (falls back to WxH from image).
    """
    if not image:
        layout.label(text="No image", icon='IMAGE_DATA')
        return

    box = layout.box()
    row = box.row(align=True)

    # Preview icon on the left
    icon_id = _get_preview_icon_id(image)
    if icon_id:
        row.template_icon(icon_value=icon_id, scale=1.8)

    # Name + resolution details
    info_col = row.column(align=True)
    name = display_name or image.name
    info_col.label(text=name)

    res = display_resolution
    if not res and image.size[0] > 0:
        res = f"{image.size[0]} x {image.size[1]}"
    if res:
        sub = info_col.row()
        sub.scale_y = 0.75
        sub.label(text=res, icon='FULLSCREEN_ENTER')

    # Remove button on the right
    if remove_op:
        op = row.operator(remove_op, text="", icon='X')
        if remove_op_props:
            for k, v in remove_op_props.items():
                setattr(op, k, v)


# ---------------------------------------------------------------------------
# Generate footers
# ---------------------------------------------------------------------------

def _action_operator(layout, operator_id, text="", icon='NONE'):
    """Draw an operator using the Mixar accent action button when available."""
    if hasattr(layout, 'mixar_operator'):
        return layout.mixar_operator(operator_id, text=text, icon=icon)
    return layout.operator(operator_id, text=text, icon=icon)


def draw_generate_footer(layout, context, operator_id, tab_prefix,
                         gen_flag_attr=None, cancel_op=None,
                         feature_key=""):
    """Queue-style generate button + cancel + progress bar.

    When *feature_key* is provided the footer gains a 3-second cooldown
    flash ("Added to queue!"), a live job count, and a "View Queue"
    shortcut — matching the pattern used by Image-to-3D Pro.
    """
    scene = context.scene
    flag_attr = gen_flag_attr or f'mixie_{tab_prefix}_is_generating'
    is_gen = getattr(scene, flag_attr, False)

    # Cooldown / queue awareness (when feature_key is provided)
    cooldown = False
    has_queue_work = False
    if feature_key:
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import _in_cooldown
        from mixar.modules.common.job_queue.core.queue_manager import get_queue
        cooldown = _in_cooldown(feature_key)
        queue = get_queue(feature_key)
        has_queue_work = queue.has_active_work()

    layout.separator(factor=SEP_FOOTER)

    # Generate + Cancel side by side (matches queue footer layout)
    row = layout.row(align=True)
    row.scale_y = GENERATE_BUTTON_SCALE_Y
    sub = row.row()
    # When queue-aware, only the 3-second cooldown blocks the button —
    # users can queue multiple jobs while earlier ones are still running.
    # Without a feature_key we fall back to the legacy is_gen guard.
    if feature_key:
        sub.enabled = not cooldown
    else:
        sub.enabled = not is_gen
    if cooldown:
        _action_operator(sub, operator_id, text="Added to queue!", icon='CHECKMARK')
    else:
        _action_operator(sub, operator_id, text="Generate", icon='PLAY')

    if is_gen or has_queue_work:
        effective_cancel = cancel_op or "mixie.cancel_generation"
        cancel = row.row(align=True)
        cancel.scale_x = 0.6
        op = cancel.operator(effective_cancel, text="Cancel", icon='CANCEL')
        if hasattr(op, 'tab_prefix'):
            op.tab_prefix = tab_prefix
        if hasattr(op, 'gen_flag_attr') and gen_flag_attr:
            op.gen_flag_attr = gen_flag_attr

    # Queue status row
    if feature_key and (has_queue_work or cooldown):
        status_row = layout.row(align=True)
        active_count = queue.running_count() + queue.pending_count()
        if active_count:
            status_row.label(
                text=f"{active_count} job{'s' if active_count != 1 else ''} in queue",
                icon='TIME',
            )
        view = status_row.row(align=True)
        view.alignment = 'RIGHT'
        view.operator("mixie.queue_view", text="View Queue", icon='FORWARD')

    error_attr = f'mixie_{tab_prefix}_error'
    error_msg = getattr(scene, error_attr, '')
    if error_msg:
        from mixar.modules.common.job_queue.core.error_helpers import sanitize_message
        draw_status_badge(layout, f"Error: {sanitize_message(error_msg)}", 'ERROR')


def draw_hunyuan_generate_footer(layout, context, job, mode, can_generate_fn):
    """Queue-style Hunyuan generate footer (progress, cancel, result, error)."""
    layout.separator(factor=SEP_FOOTER)

    is_busy = job.status in ('SUBMITTING', 'POLLING')
    can_gen = can_generate_fn() if not is_busy else False

    # Generate + Cancel side by side (matches queue footer layout)
    row = layout.row(align=True)
    row.scale_y = GENERATE_BUTTON_SCALE_Y
    sub = row.row()
    sub.enabled = can_gen and not is_busy
    op = _action_operator(sub, "mixie.hunyuan_generate", text="Generate", icon='PLAY')
    op.mode_override = mode

    if is_busy:
        cancel = row.row(align=True)
        cancel.scale_x = 0.6
        c_op = cancel.operator("mixie.hunyuan_cancel", text="Cancel", icon='CANCEL')
        c_op.mode_override = mode

    if is_busy:
        draw_styled_progress(layout, job, "progress", text=job.progress_label or "Generating...")

    if job.status == 'DONE':
        draw_status_badge(layout, f"Imported: {job.imported_object_name}", 'DONE')

    if job.status == 'FAILED':
        from mixar.modules.common.job_queue.core.error_helpers import sanitize_message
        draw_status_badge(layout, f"Error: {sanitize_message(job.error_message)}", 'ERROR')
        row = layout.row()
        op = row.operator("mixie.hunyuan_dismiss_error", text="Dismiss", icon='X')
        op.mode_override = mode
