# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generation queue UIList + footer drawer helper."""

import time

from bpy.types import UIList

from mixar.modules.common.job_queue.core.job import JobState
from mixar.modules.common.job_queue.core.queue_manager import get_queue

# Tracks when the last enqueue happened per feature_key (epoch seconds).
# Used to show "Added to queue" flash and disable Generate for a few seconds.
_enqueue_timestamps: dict[str, float] = {}
_ENQUEUE_COOLDOWN_S = 3.0


_STATE_ICON = {
    JobState.PENDING.value: 'TIME',
    JobState.RUNNING_SUBMIT.value: 'PLAY',
    JobState.RUNNING_POLL.value: 'PLAY',
    JobState.RUNNING_DOWNLOAD.value: 'IMPORT',
    JobState.SUCCESS.value: 'CHECKMARK',
    JobState.FAILED.value: 'ERROR',
    JobState.CANCELLED.value: 'CANCEL',
    JobState.PAUSED_AUTH.value: 'LOCKED',
}

_TERMINAL_STATE_VALUES = {
    JobState.SUCCESS.value,
    JobState.FAILED.value,
    JobState.CANCELLED.value,
}


class MIXIE_UL_generation_queue(UIList):
    """Render queue items as one row per job.

    The ``feature_key`` is passed via ``list_id``.
    """

    bl_idname = "MIXIE_UL_generation_queue"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        icon_id = _STATE_ICON.get(item.state, 'QUESTION')
        is_terminal = item.state in _TERMINAL_STATE_VALUES
        is_failed = item.state == JobState.FAILED.value

        col = layout.column(align=True)
        # Main row: icon + label + status + cancel
        row = col.row(align=True)
        row.active = not is_terminal
        row.label(text="", icon=icon_id)
        row.label(text=item.label or "(unnamed)")
        info = row.row()
        info.alignment = 'RIGHT'
        info.label(text=item.substate_text or "")

        if not is_terminal:
            op = row.operator(
                "mixie.queue_cancel_job", text="", icon='X', emboss=False,
            )
            op.feature_key = self.list_id or ""
            op.job_id = item.job_id

        # Error row for failed jobs
        if is_failed and item.error:
            err_row = col.row(align=True)
            err_row.active = False
            err_row.label(text=item.error, icon='BLANK1')


classes = (MIXIE_UL_generation_queue,)


# ---------------------------------------------------------------------------
# Enqueue cooldown helpers
# ---------------------------------------------------------------------------

def mark_enqueued(feature_key: str) -> None:
    """Call after successfully enqueueing jobs to trigger the flash message."""
    import bpy
    _enqueue_timestamps[feature_key] = time.time()

    # Schedule a redraw after cooldown expires so the button text reverts
    def _redraw_after_cooldown():
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ('VIEW_3D', 'MIXIE'):
                    area.tag_redraw()
        return None  # Don't repeat

    bpy.app.timers.register(_redraw_after_cooldown, first_interval=_ENQUEUE_COOLDOWN_S + 0.1)


def _in_cooldown(feature_key: str) -> bool:
    ts = _enqueue_timestamps.get(feature_key, 0.0)
    return (time.time() - ts) < _ENQUEUE_COOLDOWN_S


# ---------------------------------------------------------------------------
# Footer + queue panel drawing helpers
# ---------------------------------------------------------------------------


def draw_queue_generate_footer(
    layout, context, feature_key: str, can_generate_fn,
    mode_override: str = 'PRO',
    progress_attr: str = '',
):
    """Draw the queue-aware Generate / Cancel-All footer.

    After clicking Generate, shows "Added to queue!" for 3 seconds with
    the button disabled, plus a "View Queue" shortcut.
    """
    from mixar.modules.moodboard.constants import (
        SEP_FOOTER, GENERATE_BUTTON_SCALE_Y,
    )

    layout.separator(factor=SEP_FOOTER)

    queue = get_queue(feature_key)
    has_work = queue.has_active_work()
    cooldown = _in_cooldown(feature_key)

    can_gen = bool(can_generate_fn()) if can_generate_fn else True

    # Generate + Cancel All row
    row = layout.row(align=True)
    row.scale_y = GENERATE_BUTTON_SCALE_Y
    sub = row.row()
    sub.enabled = can_gen and not cooldown
    if cooldown:
        sub.operator("mixie.hunyuan_generate", text="Added to queue!", icon='CHECKMARK')
    else:
        op = sub.operator("mixie.hunyuan_generate", text="Generate", icon='PLAY')
        op.mode_override = mode_override

    if has_work:
        cancel = row.row(align=True)
        cancel.scale_x = 0.6
        c_op = cancel.operator(
            "mixie.queue_cancel_all", text="Cancel All", icon='CANCEL',
        )
        c_op.feature_key = feature_key

    # Queue status + View Queue button
    if has_work or cooldown:
        status_row = layout.row(align=True)
        active_count = queue.running_count() + queue.pending_count()
        if active_count:
            status_row.label(text=f"{active_count} job{'s' if active_count != 1 else ''} in queue", icon='TIME')
        view = status_row.row(align=True)
        view.alignment = 'RIGHT'
        view.operator("mixie.queue_view", text="View Queue", icon='FORWARD')


def draw_queue_panel(layout, context, feature_key: str, mirror_attr: str,
                     label_override: str = "", show_footer: bool = True,
                     show_cancel_all: bool = False):
    """Draw the collapsible "Generation Queue" box.

    Parameters
    ----------
    label_override : str, optional
        Custom header label.  When empty the default
        "Queue (X running, Y pending, Z done)" is shown.
    show_footer : bool
        Show the per-section "Clear Completed" button inside the box.
    show_cancel_all : bool
        Show a "Cancel All" button inside the box when active work exists.
    """
    scene = context.scene
    if not hasattr(scene, "mixie_queues") or not hasattr(scene, "mixie_queue_ui"):
        return

    feature_pg = getattr(scene.mixie_queues, mirror_attr, None)
    if feature_pg is None:
        return

    queue = get_queue(feature_key)
    running = queue.running_count()
    pending = queue.pending_count()
    snapshot = queue.snapshot()
    done = sum(1 for j in snapshot if j.state.value in _TERMINAL_STATE_VALUES)

    box = layout.box()
    header = box.row(align=True)
    expanded_attr = f"{mirror_attr}_expanded"
    expanded = getattr(scene.mixie_queue_ui, expanded_attr, True)
    header.prop(
        scene.mixie_queue_ui, expanded_attr,
        icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT',
        emboss=False, text="",
    )
    if label_override:
        header.label(text=label_override)
    else:
        header.label(
            text=f"Queue ({running} running, {pending} pending, {done} done)",
        )

    # Compact counts next to the header label when using label_override
    if label_override:
        counts = header.row()
        counts.alignment = 'RIGHT'
        parts = []
        if running:
            parts.append(f"{running} running")
        if pending:
            parts.append(f"{pending} pending")
        if done:
            parts.append(f"{done} done")
        if parts:
            counts.label(text=", ".join(parts))

    if not expanded:
        return

    if len(feature_pg.items) == 0:
        box.label(text="No jobs queued", icon='INFO')
        return

    box.template_list(
        "MIXIE_UL_generation_queue", feature_key,
        feature_pg, "items",
        feature_pg, "active_index",
        rows=4,
    )

    # Footer actions inside the box
    has_active = show_cancel_all and queue.has_active_work()
    if show_footer or has_active:
        foot = box.row(align=True)
        if show_footer:
            op = foot.operator(
                "mixie.queue_clear_completed", text="Clear Completed", icon='TRASH',
            )
            op.feature_key = feature_key
        if has_active:
            op = foot.operator(
                "mixie.queue_cancel_all", text="Cancel All", icon='CANCEL',
            )
            op.feature_key = feature_key
