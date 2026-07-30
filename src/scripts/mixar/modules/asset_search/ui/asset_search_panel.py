# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Library Search Panel

Panel in the asset browser's source list (TOOLS region): index status,
training with real-time progress (counter, phase, current asset, ETA,
failures, cancel), actionable search results, and the agent-reuse threshold.
"""

import bpy
from bpy.types import Panel


def _draw_status(layout, state):
    """Idle status block: indexed state, staleness delta, last-run summary."""
    box = layout.box()
    col = box.column(align=True)

    if state.is_training:
        return  # the training block owns the panel while running

    if state.last_summary:
        row = col.row()
        row.label(
            text=state.last_summary,
            icon='CHECKMARK' if state.last_summary_success else 'ERROR',
        )
        col.separator(factor=0.3)

    if not state.has_model and not state.last_trained_at:
        col.label(text="Library not indexed yet", icon='INFO')
        hint = col.row()
        hint.scale_y = 0.8
        hint.label(text="Train to enable search and agent reuse")
    elif state.needs_retraining:
        alert = col.row()
        alert.alert = True
        alert.label(
            text=state.retraining_message or "Library changed — retrain to update",
            icon='ERROR',
        )
    else:
        col.label(text="Index is up to date", icon='CHECKMARK')

    if state.last_trained_at:
        sub = col.row()
        sub.scale_y = 0.8
        sub.label(text=f"Last trained: {state.last_trained_at}")


def _draw_training_progress(layout, state):
    """Live progress: bar + counter + phase + current item + ETA + failures."""
    box = layout.box()
    col = box.column(align=True)

    col.prop(state, "progress", text=state.phase_text or "Training…", slider=True)

    if state.assets_total:
        col.label(
            text=f"Embedding {state.assets_done} / {state.assets_total} assets",
            icon='RENDER_RESULT',
        )
    if state.current_item:
        cur = col.row()
        cur.scale_y = 0.8
        cur.label(text=f"Now: {state.current_item}")
    if state.eta_text:
        eta = col.row()
        eta.scale_y = 0.8
        eta.label(text=state.eta_text, icon='TIME')
    if state.prepare_note:
        note = col.row()
        note.scale_y = 0.8
        note.label(text=state.prepare_note, icon='INFO')

    if state.failed_count:
        col.separator(factor=0.3)
        fail_row = col.row()
        fail_row.alert = True
        fail_row.prop(
            state, "show_failures",
            text=f"{state.failed_count} skipped",
            icon='TRIA_DOWN' if state.show_failures else 'TRIA_RIGHT',
            emboss=False,
        )
        if state.show_failures:
            for line in state.failed_list.split("\n"):
                if line.strip():
                    r = col.row()
                    r.scale_y = 0.75
                    r.label(text="  " + line)

    col.separator(factor=0.5)
    cancel = col.row()
    cancel.scale_y = 1.1
    if state.cancel_requested:
        cancel.enabled = False
        cancel.operator("mixie.cancel_asset_training",
                        text="Cancelling…", icon='SORTTIME')
    else:
        cancel.operator("mixie.cancel_asset_training",
                        text="Cancel", icon='X')


def _draw_train_controls(layout, state):
    box = layout.box()
    col = box.column(align=True)

    row = col.row(align=True)
    row.scale_y = 1.3
    row.operator("mixie.train_asset_model", text="Train Model",
                 icon='OUTLINER_OB_LIGHT')
    refresh_sub = row.row(align=True)
    refresh_sub.scale_x = 0.8
    if state and state.is_refreshing:
        refresh_sub.enabled = False
        refresh_sub.operator("mixie.refresh_asset_status", text="", icon='SORTTIME')
    else:
        refresh_sub.operator("mixie.refresh_asset_status", text="", icon='FILE_REFRESH')

    # Destructive action: labeled, on its own quiet row (not an icon trap
    # beside the primary button).
    danger = col.row()
    danger.scale_y = 0.85
    danger.operator("mixie.delete_asset_embeddings",
                    text="Delete All Embeddings…", icon='TRASH', emboss=False)


def _draw_search(layout, state, is_training):
    col = layout.column()

    if is_training:
        note = col.row()
        note.scale_y = 0.85
        note.label(text="Search is unavailable while training", icon='LOCKED')
        return

    if state:
        col.prop(state, "search_prompt", text="", icon='VIEWZOOM',
                 placeholder="Describe an asset…")
        col.separator(factor=0.3)
        col.label(text="Reference Image", icon='IMAGE_DATA')
        col.template_ID(state, "search_image", open="image.open")
        col.separator(factor=0.5)

    btn_row = col.row(align=True)
    btn_row.scale_y = 1.5
    if state and state.is_searching:
        btn_row.enabled = False
        btn_row.operator("mixie.search_assets", text="Searching…", icon='SORTTIME')
    else:
        btn_row.operator("mixie.search_assets", text="Search", icon='VIEWZOOM')

    if not state:
        return

    # -- Results: actionable rows, not text --
    if state.search_results:
        col.separator(factor=0.5)
        result_box = col.box()
        header = result_box.row()
        header.label(
            text=f"{len(state.search_results)} result(s)", icon='CHECKMARK',
        )
        header.operator("mixie.clear_search_results", text="", icon='X',
                        emboss=False)
        for hit in state.search_results:
            row = result_box.row(align=True)
            main = row.column(align=True)
            top = main.row(align=True)
            top.label(text=hit.name, icon='OBJECT_DATA')
            where = main.row()
            where.scale_y = 0.75
            src = hit.library or "unknown library"
            if hit.asset_type:
                src += f" · {hit.asset_type}"
            where.label(text="    " + src)
            score_row = main.row(align=True)
            score_row.scale_y = 0.6
            try:
                score_row.progress(factor=hit.score,
                                   text=f"{hit.score:.0%}", type='BAR')
            except Exception:
                score_row.label(text=f"score {hit.score:.2f}")
            btn = row.column()
            op = btn.operator("mixie.locate_search_result", text="",
                              icon='ZOOM_SELECTED')
            op.asset_name = hit.name
            op.library = hit.library
        result_box.separator(factor=0.2)
        tip = result_box.row()
        tip.scale_y = 0.75
        tip.label(text="Click the magnifier to show a result in the browser",
                  icon='INFO')
    elif state.search_message:
        col.separator(factor=0.5)
        msg_box = col.box()
        row = msg_box.row()
        row.label(text=state.search_message, icon='INFO')
        if "No matching" in state.search_message:
            hint = msg_box.row()
            hint.scale_y = 0.8
            hint.label(text="Try other words, or retrain if assets are new")
        row.operator("mixie.clear_search_results", text="", icon='X', emboss=False)


class MIXIE_PT_asset_library_search(Panel):
    """Asset Library Search panel in the asset browser source list"""

    bl_label = "Asset Library Search"
    bl_idname = "MIXIE_PT_asset_library_search"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOLS'
    bl_order = 100  # Appear after built-in panels

    @classmethod
    def poll(cls, context):
        from bpy_extras.asset_utils import SpaceAssetInfo
        return SpaceAssetInfo.is_asset_browser_poll(context)

    def draw(self, context):
        layout = self.layout
        state = getattr(context.scene, 'mixie_asset_training', None)
        is_training = state.is_training if state else False

        if state:
            _draw_status(layout, state)

        if is_training:
            _draw_training_progress(layout, state)
        elif state:
            _draw_train_controls(layout, state)

        layout.separator(factor=0.5)
        _draw_search(layout, state, is_training)

        # == Agent asset reuse ==
        if state:
            layout.separator(factor=0.5)
            reuse_box = layout.box()
            reuse_col = reuse_box.column(align=True)
            reuse_col.label(text="Agent Asset Reuse",
                            icon='OUTLINER_OB_GROUP_INSTANCE')
            reuse_col.prop(state, "match_threshold", text="Match Threshold",
                           slider=True)
            hint = reuse_col.row()
            hint.scale_y = 0.8
            hint.label(text="Ask the agent to \"use my library\"", icon='INFO')


classes = (
    MIXIE_PT_asset_library_search,
)
