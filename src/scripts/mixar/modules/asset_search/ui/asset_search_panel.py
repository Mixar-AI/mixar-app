# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Library Search Panel

Asset-browser TOOLS panel styled in the Mixar sidebar language (same visual
system as the moodboard N-panel): mixar_section boxes with labeled headers,
hint-scale sublabels, 1.4-scale primary action buttons, and status badges.
"""

import bpy
from bpy.types import Panel

# Visual constants — kept in lockstep with moodboard/constants.py
# (GENERATE_BUTTON_SCALE_Y / SEP_* / HINT_SCALE_Y).
_BTN_SCALE = 1.4
_SEP_SECTION = 0.8
_SEP_INTRA = 0.15
_HINT_SCALE = 0.85


def _section(layout, label=None, icon='NONE', action_op=None,
             action_icon='FILE_REFRESH', action_enabled=True):
    """Styled Mixar section (accent border + shadow); returns its column."""
    box = layout.mixar_section() if hasattr(layout, 'mixar_section') else layout.box()
    col = box.column()
    if label:
        if action_op:
            row = col.row(align=True)
            row.label(text=label, icon=icon)
            sub = row.row(align=True)
            sub.alignment = 'RIGHT'
            sub.enabled = action_enabled
            sub.operator(action_op, text="", icon=action_icon)
        else:
            col.label(text=label, icon=icon)
        col.separator(factor=_SEP_INTRA)
    return col


def _hint(col, text, icon='NONE'):
    row = col.row()
    row.scale_y = _HINT_SCALE
    row.label(text=text, icon=icon)


def _input(layout, data, prop, **kw):
    if hasattr(layout, 'mixar_input'):
        layout.mixar_input(data, prop, **{k: v for k, v in kw.items() if k == 'text'})
    else:
        layout.prop(data, prop, **kw)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _draw_status(layout, state):
    """Library Index section: state badge, last-run summary, train actions."""
    col = _section(
        layout, "Library Index", icon='ASSET_MANAGER',
        action_op="mixie.refresh_asset_status",
        action_icon='SORTTIME' if state.is_refreshing else 'FILE_REFRESH',
        action_enabled=not state.is_refreshing,
    )

    if not state.has_model and not state.last_trained_at:
        col.label(text="Not indexed yet", icon='INFO')
        _hint(col, "Train to enable search and agent reuse")
    elif state.needs_retraining:
        alert = col.row()
        alert.alert = True
        alert.label(
            text=state.retraining_message or "Library changed — retrain",
            icon='ERROR',
        )
    else:
        col.label(text="Up to date", icon='CHECKMARK')
    if state.last_trained_at:
        _hint(col, f"Last trained: {state.last_trained_at}")

    if state.last_summary:
        col.separator(factor=_SEP_INTRA)
        row = col.row()
        row.scale_y = _HINT_SCALE
        if not state.last_summary_success:
            row.alert = True
        row.label(
            text=state.last_summary,
            icon='CHECKMARK' if state.last_summary_success else 'ERROR',
        )

    col.separator(factor=_SEP_INTRA)
    btn = col.row()
    btn.scale_y = _BTN_SCALE
    btn.operator("mixie.train_asset_model", text="Train Model", icon='PLAY')
    danger = col.row()
    danger.scale_y = _HINT_SCALE
    danger.operator("mixie.delete_asset_embeddings",
                    text="Delete All Embeddings…", icon='TRASH', emboss=False)


def _draw_training_progress(layout, state):
    """Live training section: bar, counter, phase, current item, ETA, cancel."""
    col = _section(layout, "Training", icon='ASSET_MANAGER')

    col.prop(state, "progress", text=state.phase_text or "Training…", slider=True)

    if state.assets_total:
        col.label(
            text=f"Embedding {state.assets_done} / {state.assets_total} assets",
            icon='RENDER_RESULT',
        )
    if state.current_item:
        _hint(col, f"Now: {state.current_item}")
    if state.eta_text:
        _hint(col, state.eta_text, icon='TIME')
    if state.prepare_note:
        _hint(col, state.prepare_note, icon='INFO')

    if state.failed_count:
        col.separator(factor=_SEP_INTRA)
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
                    _hint(col, "  " + line)

    col.separator(factor=_SEP_INTRA)
    cancel = col.row()
    cancel.scale_y = 1.1
    if state.cancel_requested:
        cancel.enabled = False
        cancel.operator("mixie.cancel_asset_training",
                        text="Cancelling…", icon='SORTTIME')
    else:
        cancel.operator("mixie.cancel_asset_training",
                        text="Cancel", icon='CANCEL')


def _draw_search(layout, state, is_training):
    """Search section: prompt + reference image + button + actionable results."""
    col = _section(layout, "Search Library", icon='VIEWZOOM')

    if is_training:
        _hint(col, "Unavailable while training", icon='LOCKED')
        return

    _input(col, state, "search_prompt", text="",
           icon='VIEWZOOM', placeholder="Describe an asset…")
    col.separator(factor=_SEP_INTRA)
    _hint(col, "Reference Image (optional)", icon='IMAGE_DATA')
    col.template_ID(state, "search_image", open="image.open")

    col.separator(factor=_SEP_INTRA)
    btn = col.row()
    btn.scale_y = _BTN_SCALE
    if state.is_searching:
        btn.enabled = False
        btn.operator("mixie.search_assets", text="Searching…", icon='SORTTIME')
    else:
        btn.operator("mixie.search_assets", text="Search", icon='VIEWZOOM')

    if state.search_results:
        col.separator(factor=_SEP_SECTION)
        header = col.row(align=True)
        header.label(text=f"{len(state.search_results)} result(s)",
                     icon='CHECKMARK')
        header.operator("mixie.clear_search_results", text="", icon='X',
                        emboss=False)
        for hit in state.search_results:
            card = col.box()
            row = card.row(align=True)
            main = row.column(align=True)
            main.label(text=hit.name, icon='OBJECT_DATA')
            src = hit.library or "unknown library"
            if hit.asset_type:
                src += f" · {hit.asset_type}"
            _hint(main, "    " + src)
            score_row = main.row(align=True)
            score_row.scale_y = 0.6
            try:
                score_row.progress(factor=hit.score,
                                   text=f"{hit.score:.0%}", type='BAR')
            except Exception:
                _hint(score_row, f"score {hit.score:.2f}")
            btn_col = row.column()
            op = btn_col.operator("mixie.locate_search_result", text="",
                                  icon='ZOOM_SELECTED')
            op.asset_name = hit.name
            op.library = hit.library
        _hint(col, "Click the magnifier to show a result in the browser",
              icon='INFO')
    elif state.search_message:
        col.separator(factor=_SEP_INTRA)
        row = col.row(align=True)
        row.scale_y = _HINT_SCALE
        row.label(text=state.search_message, icon='INFO')
        row.operator("mixie.clear_search_results", text="", icon='X',
                     emboss=False)
        if "No matching" in state.search_message:
            _hint(col, "Try other words, or retrain if assets are new")


def _draw_agent_reuse(layout, state):
    col = _section(layout, "Agent Asset Reuse",
                   icon='OUTLINER_OB_GROUP_INSTANCE')
    col.prop(state, "match_threshold", text="Match Threshold", slider=True)
    _hint(col, "Ask the agent to \"use my library\"", icon='INFO')


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

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
        if state is None:
            layout.label(text="Asset search unavailable", icon='ERROR')
            return
        is_training = state.is_training

        if is_training:
            _draw_training_progress(layout, state)
        else:
            _draw_status(layout, state)
        layout.separator(factor=_SEP_SECTION)
        _draw_search(layout, state, is_training)
        layout.separator(factor=_SEP_SECTION)
        _draw_agent_reuse(layout, state)


classes = (
    MIXIE_PT_asset_library_search,
)
