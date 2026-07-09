# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unified job queue UIList + per-tab Generate/Cancel footer helpers."""

import re
import time

from bpy.types import UIList

from mixar.modules.common.job_queue.constants import (
    FEATURE_BRUSH_GEN,
    FEATURE_HUNYUAN_PART,
    FEATURE_HUNYUAN_RAPID,
    FEATURE_HUNYUAN_UV,
    FEATURE_IMAGE_TO_3D_PRO,
    FEATURE_IMAGEGEN,
    FEATURE_LOOKDEV,
    FEATURE_LOOKDEV360,
    FEATURE_MATGEN,
    FEATURE_MESH_SEGMENT,
    FEATURE_MODEL_3D,
    FEATURE_RETOPOLOGY,
    FEATURE_SCENE_GEN,
    FEATURE_SCENE_GEN_HP,
    FEATURE_SCENE_GEN_LP,
    FEATURE_SCENE_RECON,
)
from mixar.modules.common.job_queue.core.error_helpers import sanitize_message
from mixar.modules.common.job_queue.core.job import JobState
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

# Human-facing display name per feature key. Appears as the "Job Type"
# prefix on row 1 and as the coloured badge chip on row 2.
_FEATURE_LABEL = {
    FEATURE_IMAGE_TO_3D_PRO: "Image to 3D Pro",
    FEATURE_MODEL_3D: "Image to 3D",
    FEATURE_RETOPOLOGY: "Retopology",
    FEATURE_SCENE_GEN_HP: "Scene Gen HP",
    FEATURE_SCENE_GEN_LP: "Scene Gen LP",
    FEATURE_HUNYUAN_RAPID: "Rapid 3D",
    FEATURE_HUNYUAN_PART: "Part 3D",
    FEATURE_HUNYUAN_UV: "UV Unwrap",
    FEATURE_IMAGEGEN: "ImageGen",
    FEATURE_BRUSH_GEN: "Brush Gen",
    FEATURE_LOOKDEV: "Blockout Render",
    FEATURE_LOOKDEV360: "Lookdev360",
    FEATURE_MATGEN: "Material Gen",
    FEATURE_MESH_SEGMENT: "Mesh Segment",
    FEATURE_SCENE_GEN: "Scene Gen",
    FEATURE_SCENE_RECON: "Scene Recon",
}

_BUG_REPORT_URL = "https://www.mixar.app/bug-report"

# Prefixes that every enqueue site adds to ``job.label``. Row 2 already
# renders the feature type as a pill, so we strip the leading "<Prefix>: "
# from row 1 to avoid saying the same thing twice. Longer prefixes first so
# "Lookdev360:" wins over "Lookdev:".
_ENQUEUE_PREFIXES = (
    "ImageGen",
    "Lookdev360",
    "Lookdev",
    "SceneRecon",
    "MatGen",
    "Brush",
    "Segment",
)


def _strip_type_prefix(label: str) -> str:
    for pfx in _ENQUEUE_PREFIXES:
        if label.startswith(pfx + ": "):
            return label[len(pfx) + 2:]
        if label.startswith(pfx + ":"):
            return label[len(pfx) + 1:]
    return label


# Trailing " [xxxx]" where xxxx is a 4-char hex slug — appended by agent
# enqueue paths (e.g. imagegen_ops._execute_direct) to give each batch job
# a unique label so the queue's label-based dedup accepts it. Removing it
# from the row title only affects display; the underlying job.label is
# untouched, so dedup and downstream lookups keep working.
_DEDUP_TAG_RE = re.compile(r"\s+\[[0-9a-fA-F]{4,8}\]$")


def _strip_dedup_suffix(label: str) -> str:
    return _DEDUP_TAG_RE.sub("", label)


def _format_elapsed(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _feature_label(feature_key: str) -> str:
    return _FEATURE_LABEL.get(feature_key, feature_key.replace('_', ' ').title())


def _status_word(state: str, substate: str) -> str:
    """Row-2 status text — collapses SUCCESS to a plain 'Done'."""
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

    Each item draws two rows:
      1) status dot + "{JobType}: {label}" + elapsed + cancel/copy actions
      2) feature-type badge + substate text
    """

    bl_idname = "MIXIE_UL_unified_queue"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        from mixar.modules.common.job_queue.ui import queue_status_icons

        state = item.state
        is_terminal = state in _TERMINAL_STATE_VALUES
        is_failed = state == JobState.FAILED.value

        job_type = _feature_label(item.feature_key)
        # Row 2 shows the feature type as a pill, so strip the leading
        # "ImageGen: " / "Lookdev360: " / etc. that every enqueue site adds
        # to job.label. Then strip the trailing " [xxxx]" dedup slug that
        # the agent enqueue paths append. Falls through unchanged for
        # labels without either prefix or suffix.
        title = _strip_dedup_suffix(_strip_type_prefix(item.label)) \
            or "(unnamed)"
        # Sentence case: prompts arrive as typed ("a mouse") — capitalise
        # the first letter only, leaving the rest untouched so acronyms
        # and proper nouns inside the prompt survive.
        title = title[:1].upper() + title[1:]

        col = layout.column(align=True)

        # -- Row 1: coloured status dot + title + elapsed + cancel ---------
        top = col.row(align=True)
        top.scale_y = 1.05
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
        col.separator(factor=0.4)

        # -- Row 2: | pill 40% | gap 30% | status 30% | across the full row
        # width, so the right-aligned status lines up with row 1's elapsed
        # time at the row's right edge.
        # Row 2 is visually secondary to row 1 purely via ``scale_y`` — we
        # avoid ``active = False`` because Blender inverts text colour on
        # the highlighted (selected) UIList row, which turns dimmed text
        # into unreadable dark ink on the accent background.
        second = col.row(align=True)
        second.scale_y = 0.7
        # Indent by one icon width (blank icon label, same trick as the
        # error row below) so the pill's left edge lines up with the title
        # text after row 1's status dot.
        second.label(text="", icon='BLANK1')
        outer = second.split(factor=0.5, align=True)

        # Left ~third = bordered pill, kept narrow so it hugs the label
        # text. Sentence case (as authored in _FEATURE_LABEL) reads better
        # in a chip than a shout-cased tag.
        pill_box = outer.box()
        pill_box.label(text=job_type)

        # Remaining width: split in half — empty gap, then the status word.
        rest = outer.split(factor=0.3, align=True)
        rest.label(text="")  # gap between pill and status

        # Status word, right-aligned so it sits at row 2's right edge.
        # Must be a ``.column()``, not a ``.row()`` — the working
        # right-align pattern in the codebase (see
        # ``paint/ui/operators/layer_paint_ops_helpers.py:38``) uses
        # column because columns inside a split's slot fill the slot's
        # full width, so ``alignment='RIGHT'`` actually pushes children
        # to the right edge.  Rows inside a split slot size-to-content
        # and then align within their own narrow bounds — that's why
        # a plain ``outer.row(align=True)`` left "Done" drifting in
        # the middle of row 2.
        status_cell = rest.column(align=True)
        status_cell.alignment = 'RIGHT'
        status_cell.label(text=_status_word(state, item.substate_text))

        # -- Optional row 3: error detail + copy/report actions -------------
        if is_failed and (item.user_message or item.error):
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
        col.separator(factor=0.4)
        col.separator(type='LINE')
        spacer = col.row()
        spacer.scale_y = 0.35
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
    scene = context.scene
    if not hasattr(scene, "mixie_queue"):
        layout.label(text="Queue system not available", icon='INFO')
        return

    pg = scene.mixie_queue

    # Filter chips row (All / Active / Done / Failed), each with its
    # live job count so no separate summary block is needed.
    states = [it.state for it in pg.items]
    n_all = len(states)
    n_active = sum(1 for s in states if s in _ACTIVE_STATE_VALUES)
    n_done = sum(1 for s in states if s in _DONE_STATE_VALUES)
    n_failed = sum(1 for s in states if s in _FAILED_STATE_VALUES)

    chip_row = layout.row(align=True)
    chip_row.scale_y = 1.1
    chip_row.prop_enum(pg, "filter_mode", 'ALL', text=f"All ({n_all})")
    chip_row.prop_enum(pg, "filter_mode", 'ACTIVE', text=f"Active ({n_active})")
    chip_row.prop_enum(pg, "filter_mode", 'DONE', text=f"Done ({n_done})")
    chip_row.prop_enum(pg, "filter_mode", 'FAILED', text=f"Failed ({n_failed})")

    if len(pg.items) == 0:
        layout.label(text="No jobs queued", icon='INFO')
        return

    layout.template_list(
        MIXIE_UL_unified_queue.bl_idname, "",
        pg, "items",
        pg, "active_index",
        rows=8,
    )
