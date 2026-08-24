# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate-button footers for moodboard sidebar tabs."""

from mixar.modules.moodboard.constants import GENERATE_BUTTON_SCALE_Y, SEP_FOOTER

from .sidebar_ui_helpers import draw_status_badge, draw_styled_progress


def _action_operator(layout, operator_id, text="", icon='NONE'):
    """Draw an operator using the Mixar accent action button when available."""
    if hasattr(layout, 'mixar_operator'):
        return layout.mixar_operator(operator_id, text=text, icon=icon)
    return layout.operator(operator_id, text=text, icon=icon)


def draw_generate_footer(layout, context, operator_id, tab_prefix,
                         gen_flag_attr=None, cancel_op=None,
                         feature_key="", service_key="", model_slug="",
                         params=None, payload=None):
    """Queue-style generate button + cancel + progress bar.

    When *feature_key* is provided the footer gains a 3-second cooldown
    flash ("Added to queue!"), a live job count, and a "View Queue"
    shortcut — matching the pattern used by Image-to-3D Pro.

    *service_key* / *model_slug* drive the billed credit figure on the
    Generate button (catalog cost, plus a live estimate for image/video).
    """
    scene = context.scene
    flag_attr = gen_flag_attr or f'mixie_{tab_prefix}_is_generating'
    is_gen = getattr(scene, flag_attr, False)

    cooldown = False
    has_queue_work = False
    if feature_key:
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import _in_cooldown
        from mixar.modules.common.job_queue.core.queue_manager import get_queue
        cooldown = _in_cooldown(feature_key)
        queue = get_queue(feature_key)
        has_queue_work = queue.has_active_work()

    layout.separator(factor=SEP_FOOTER)

    row = layout.row(align=True)
    row.scale_y = GENERATE_BUTTON_SCALE_Y
    sub = row.row()
    if feature_key:
        sub.enabled = not cooldown
    else:
        sub.enabled = not is_gen
    if cooldown:
        _action_operator(sub, operator_id, text="Added to queue!", icon='CHECKMARK')
    else:
        generate_text = "Generate"
        try:
            from mixar.modules.common.job_queue.core.generate_cost import (
                generate_button_text,
                schedule_estimate_if_needed,
            )
            schedule_estimate_if_needed(
                service_key, model_slug, params, payload,
            )
            generate_text = generate_button_text(
                service_key, model_slug, feature_key, params,
            )
        except Exception:
            generate_text = "Generate"
        _action_operator(sub, operator_id, text=generate_text, icon='PLAY')

    if is_gen or has_queue_work:
        effective_cancel = cancel_op or "mixie.cancel_generation"
        cancel = row.row(align=True)
        cancel.scale_x = 0.6
        op = cancel.operator(effective_cancel, text="Cancel", icon='CANCEL')
        if hasattr(op, 'tab_prefix'):
            op.tab_prefix = tab_prefix
        if hasattr(op, 'gen_flag_attr') and gen_flag_attr:
            op.gen_flag_attr = gen_flag_attr

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
