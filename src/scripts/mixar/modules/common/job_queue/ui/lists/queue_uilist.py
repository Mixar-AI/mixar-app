# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unified job queue UIList + per-tab Generate/Cancel footer helpers."""

import time

from bpy.types import UIList

from mixar.modules.common.job_queue.core.error_helpers import sanitize_message
from mixar.modules.common.job_queue.core.job import JobState
from mixar.modules.common.job_queue.core.labels import feature_label, format_elapsed
from mixar.modules.common.job_queue.core.queue_manager import get_queue

# Tracks when the last enqueue happened per feature_key (epoch seconds).
# Used to show "Added to queue" flash and disable Generate for a few seconds.
_enqueue_timestamps: dict[str, float] = {}
_ENQUEUE_COOLDOWN_S = 3.0


_RUNNING_STATE_VALUES = {
    JobState.RUNNING_SUBMIT.value,
    JobState.RUNNING_POLL.value,
    JobState.RUNNING_DOWNLOAD.value,
}

_ACTIVE_STATE_VALUES = _RUNNING_STATE_VALUES | {
    JobState.PENDING.value,
    JobState.PAUSED_AUTH.value,
}

_DONE_STATE_VALUES = {JobState.SUCCESS.value}

_FAILED_STATE_VALUES = {
    JobState.FAILED.value,
    JobState.CANCELLED.value,
}

_TERMINAL_STATE_VALUES = _DONE_STATE_VALUES | _FAILED_STATE_VALUES

_BUG_REPORT_URL = "https://www.mixar.app/bug-report"

# Centralized queue layout tokens. Generation names remain backend-owned;
# these values only control the native Blender presentation.
_QUEUE_PRIMARY_SCALE_Y = 1.05
_QUEUE_SECONDARY_SCALE_Y = 0.85
_QUEUE_STATUS_SCALE_Y = 0.8
_QUEUE_FILTER_SCALE_Y = 1.1
_QUEUE_ROW_GAP = 0.45
_QUEUE_STATUS_GAP = 0.2
_QUEUE_ITEM_GAP = 0.5
_QUEUE_FILTER_GAP = 0.55
_QUEUE_LIST_ROWS = 8


# Shared with the Agent Bubble status pill — the same job must not be named
# two different things on two surfaces. See job_queue/core/labels.py.
_format_elapsed = format_elapsed
_feature_label = feature_label


def _model_label(service: str, model: str) -> str:
    """Backend catalog model label, with exact submitted-slug fallback."""
    model_slug = (model or "").strip()
    if not model_slug:
        return ""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model

        catalog_model = get_model((service or "").strip(), model_slug)
        if catalog_model and catalog_model.get("label"):
            return catalog_model["label"]
    except Exception:
        pass
    return model_slug


def _generation_model_label(service: str, model: str) -> str:
    """Queue metadata text: backend-owned model label only."""
    return _model_label(service, model)


def _display_title(display_label: str, label: str) -> str:
    """Return the structured queue title without parsing human-authored text."""
    title = (display_label or label or "(unnamed)").strip() or "(unnamed)"
    return title[:1].upper() + title[1:]


def _status_word(state: str, substate: str) -> str:
    """Human-readable state text; the icon alone is not an accessible label."""
    if state == JobState.SUCCESS.value:
        return "Done"
    if state == JobState.FAILED.value:
        return "Failed"
    if state == JobState.CANCELLED.value:
        return "Cancelled"
    if state == JobState.PAUSED_AUTH.value:
        return "Waiting for sign-in"
    if state in _RUNNING_STATE_VALUES:
        return substate or "Processing"
    if state == JobState.PENDING.value:
        return substate or "Queued"
    return substate or ""


class MIXIE_UL_unified_queue(UIList):
    """Render every queued job across every feature as a single flat list.

    Each item draws three compact rows:
      1) status dot + label + elapsed + cancel/copy actions
      2) feature badge + optional model badge
      3) right-aligned queue status
    """

    bl_idname = "MIXIE_UL_unified_queue"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        from mixar.modules.common.job_queue.ui import queue_status_icons

        state = item.state
        is_terminal = state in _TERMINAL_STATE_VALUES
        is_failed = state == JobState.FAILED.value

        job_type = _feature_label(
            item.origin_capability_key,
            item.service,
            item.feature_key,
        )
        # Some jobs keep dedup or downstream naming data in ``label``.
        # Enqueue paths provide a structured display_label for those jobs,
        # so arbitrary prompts/object names never need string parsing.
        title = _display_title(item.display_label, item.label)

        col = layout.column(align=True)

        # -- Row 1: coloured status dot + title + elapsed + cancel ---------
        top = col.row(align=True)
        top.scale_y = _QUEUE_PRIMARY_SCALE_Y
        dot_id = queue_status_icons.get_icon_id(state)
        if dot_id:
            top.label(text="", icon_value=dot_id)
        else:
            top.label(text="", icon='RADIOBUT_ON')
        top.label(text=title)

        info = top.row(align=True)
        info.alignment = 'RIGHT'
        if item.created_at:
            # Same monotonic clock as Job.created_at / finished_at — mixing
            # in time.time() here would break both start and finish values.
            end = item.finished_at if item.finished_at else time.monotonic()
            info.label(text=_format_elapsed(end - item.created_at))
        if not is_terminal:
            op = top.operator(
                "mixie.queue_cancel_job", text="", icon='X', emboss=False,
            )
            op.feature_key = item.feature_key
            op.job_id = item.job_id

        # Breathing room between row 1 and row 2 — an explicit separator
        # since ``col`` is aligned (align=True collapses button borders
        # together but still respects separator gaps).
        col.separator(factor=_QUEUE_ROW_GAP)

        # -- Row 2: type + optional generation metadata -------------------
        # The metadata owns the full row. Keeping queue status in its own row
        # below prevents backend model labels from being squeezed by long
        # states such as "Waiting for sign-in".
        # Row 2 is visually secondary to row 1 purely via ``scale_y`` — we
        # avoid ``active = False`` because Blender inverts text colour on
        # the highlighted (selected) UIList row, which turns dimmed text
        # into unreadable dark ink on the accent background.
        second = col.row(align=True)
        second.scale_y = _QUEUE_SECONDARY_SCALE_Y
        # Keep at most two boxes: capability and model. Provider routing is
        # intentionally not shown in the queue.
        # Start at the row edge rather than reserving a full blank icon slot;
        # the UIList already supplies its own outer padding.
        chips = second.row(align=False)
        type_box = chips.box()
        type_box.label(text=job_type)
        metadata_label = _generation_model_label(
            item.service,
            item.model,
        )
        if metadata_label:
            metadata_box = chips.box()
            metadata_box.label(text=metadata_label)

        # -- Row 3: status -------------------------------------------------
        status_text = _status_word(state, item.substate_text)
        if status_text:
            col.separator(factor=_QUEUE_STATUS_GAP)
            status_row = col.row(align=True)
            status_row.scale_y = _QUEUE_STATUS_SCALE_Y
            status_cell = status_row.column(align=True)
            status_cell.alignment = 'RIGHT'
            status_cell.label(text=status_text)

        # -- Optional error detail + copy/report actions -------------------
        if is_failed and (item.user_message or item.error):
            col.separator(factor=_QUEUE_ROW_GAP)
            err_row = col.row(align=True)
            msg_col = err_row.row(align=True)
            msg_col.active = False
            msg = item.user_message or sanitize_message(item.error)
            msg_col.label(text=msg, icon='BLANK1')
            actions = err_row.row(align=True)
            actions.alignment = 'RIGHT'
            op = actions.operator(
                "mixie.queue_copy_error", text="", icon='COPYDOWN',
                emboss=False,
            )
            op.feature_key = item.feature_key
            op.job_id = item.job_id
            op = actions.operator(
                "wm.url_open", text="", icon='URL', emboss=False,
            )
            op.url = _BUG_REPORT_URL

        # Trailing gap + hairline become the inter-item demarcation.
        # Blender's ``template_list`` collapses trailing
        # ``col.separator(...)`` inside ``draw_item`` — the item's rendered
        # height doesn't grow — so the LINE separator is followed by an
        # empty ``col.row()`` with ``scale_y > 0``: a real widget whose
        # height is respected, keeping the line from being trimmed and
        # adding the gap before the next item.
        col.separator(factor=_QUEUE_ITEM_GAP)
        col.separator(type='LINE')
        spacer = col.row()
        spacer.scale_y = _QUEUE_ITEM_GAP
        spacer.label(text="")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        mode = getattr(data, "filter_mode", 'ALL')

        if mode == 'ALL':
            allowed = None
        elif mode == 'ACTIVE':
            allowed = _ACTIVE_STATE_VALUES
        elif mode == 'DONE':
            allowed = _DONE_STATE_VALUES
        elif mode == 'FAILED':
            allowed = _FAILED_STATE_VALUES
        else:
            allowed = None

        bitflag = self.bitflag_filter_item
        flt_flags = [
            bitflag if (allowed is None or it.state in allowed) else 0
            for it in items
        ]
        return flt_flags, []


classes = (MIXIE_UL_unified_queue,)


# ---------------------------------------------------------------------------
# Enqueue cooldown helpers
# ---------------------------------------------------------------------------

def mark_enqueued(feature_key: str) -> None:
    """Call after successfully enqueueing jobs to trigger the flash message."""
    import bpy
    _enqueue_timestamps[feature_key] = time.time()

    def _redraw_after_cooldown():
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ('VIEW_3D', 'MIXIE'):
                    area.tag_redraw()
        return None

    bpy.app.timers.register(_redraw_after_cooldown, first_interval=_ENQUEUE_COOLDOWN_S + 0.1)


def _in_cooldown(feature_key: str) -> bool:
    ts = _enqueue_timestamps.get(feature_key, 0.0)
    return (time.time() - ts) < _ENQUEUE_COOLDOWN_S


# ---------------------------------------------------------------------------
# Per-tab Generate / Cancel footer (used by hunyuan tabs)
# ---------------------------------------------------------------------------


def draw_queue_generate_footer(
    layout, context, feature_key: str, can_generate_fn,
    mode_override: str = 'PRO',
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

    if has_work or cooldown:
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


# ---------------------------------------------------------------------------
# Unified queue panel drawer
# ---------------------------------------------------------------------------


def draw_unified_queue_panel(layout, context):
    """Draw the single unified queue: filter chips + flat template_list."""
    wm = context.window_manager
    if not hasattr(wm, "mixie_queue"):
        layout.label(text="Queue system not available", icon='INFO')
        return

    pg = wm.mixie_queue

    # Filter chips row (All / Active / Done / Failed), each with its
    # live job count so no separate summary block is needed.
    states = [it.state for it in pg.items]
    n_all = len(states)
    n_active = sum(1 for s in states if s in _ACTIVE_STATE_VALUES)
    n_done = sum(1 for s in states if s in _DONE_STATE_VALUES)
    n_failed = sum(1 for s in states if s in _FAILED_STATE_VALUES)

    chip_row = layout.row(align=True)
    chip_row.scale_y = _QUEUE_FILTER_SCALE_Y
    chip_row.prop_enum(pg, "filter_mode", 'ALL', text=f"All ({n_all})")
    chip_row.prop_enum(pg, "filter_mode", 'ACTIVE', text=f"Active ({n_active})")
    chip_row.prop_enum(pg, "filter_mode", 'DONE', text=f"Done ({n_done})")
    chip_row.prop_enum(pg, "filter_mode", 'FAILED', text=f"Failed ({n_failed})")
    layout.separator(factor=_QUEUE_FILTER_GAP)

    if len(pg.items) == 0:
        layout.label(text="No jobs queued", icon='INFO')
        return

    layout.template_list(
        MIXIE_UL_unified_queue.bl_idname, "",
        pg, "items",
        pg, "active_index",
        rows=_QUEUE_LIST_ROWS,
    )
