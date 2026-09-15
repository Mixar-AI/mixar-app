# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Topbar workspace-tab filter for the dual-mode UI system.

Monkey-patches TOPBAR_HT_upper_bar.draw_left so that in Zen mode the
workspace tab strip is hidden entirely — leaving only the menus + a clean
topbar.

The mode flip itself is the Zen/Engine SLIDER drawn here, centred in the
window: two operator buttons painted as one segmented track with an
animated thumb by the Mixar topbar widget (`interface_mixar_topbar.cc`,
reached through `layout.mixar_topbar_element`). It replaced the old
"Zen Mode"/"Engine Mode" menu entry (mode_menu.py, now dormant).

Note: install_topbar_filter() is intentionally called from
bootstrap/workflow_module.py during the synchronous bootstrap phase, before
the first UI paint. If installed during deferred UI loading instead, the
topbar would draw once with the unpatched method (showing all tabs) before
the patch lands — visible flicker on launch when the previous session ended
in Engine mode. There is no register()/classes contract here on purpose: the
bootstrap UI auto-loader checks for those and would otherwise call
register() a second time.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.workflow.constants import BASIC_WORKSPACE_NAME
from mixar.modules.workflow.ui.operators import mode_slider_anim

_logger = get_logger(__name__)

_original_draw_left = None
_original_draw_right = None


_SLIDER_HALF_UNITS = 5.5
"""Half the slider's width in UI units — the design's 225 px track, halved
(1 unit = UI_UNIT_X = 20 px @1x). Both halves MUST share this: the C++
painter derives the full track by mirroring the left half's rect."""


def _draw_mode_slider(layout, context) -> None:
    """Native layout centers the final slider rectangles in the full window."""
    workspace = getattr(context, "workspace", None)
    is_zen = workspace is not None and workspace.name == BASIC_WORKSPACE_NAME
    mode_slider_anim.note_mode(is_zen)

    layout.separator_spacer()

    # Tag each half IMMEDIATELY after creating it: the tag applies to the
    # BLOCK's most recent button, not to the sub-layout it is called on, so
    # deferring both tags to the end would stamp them both onto the second
    # button (and leave the first one drawn as a stock widget). Guarded so a
    # build without the C++ widget still gets two working, if plain, buttons.
    styled = hasattr(layout, "mixar_topbar_element")

    row = layout.row(align=True)
    left = row.row(align=True)
    left.ui_units_x = _SLIDER_HALF_UNITS
    left.operator("mixar.set_ui_mode_ai", text="Zen")
    if styled:
        left.mixar_topbar_element(kind='MODE_SLIDER_LEFT', active=is_zen)

    right = row.row(align=True)
    right.ui_units_x = _SLIDER_HALF_UNITS
    right.operator("mixar.set_ui_mode_pro", text="Engine")
    if styled:
        right.mixar_topbar_element(kind='MODE_SLIDER_RIGHT', active=not is_zen)

    layout.separator_spacer()


def _patched_draw_left(self, context):
    """Replacement for TOPBAR_HT_upper_bar.draw_left.

    In Zen mode the workspace tab strip is omitted entirely. In Engine mode
    we use the native template_ID_tabs — the dedicated Zen Mode workspace
    is filtered out at the C++ level (see Mixar's overlay of
    interface_template_id.cc::template_ID_tabs) so it doesn't surface as a
    tab while preserving the native tab styling.
    """
    layout = self.layout
    window = context.window
    screen = context.screen

    bpy.types.TOPBAR_MT_editor_menus.draw_collapsible(context, layout)
    # Space (not LINE) so Help keeps its trailing gap without a divider.
    layout.separator()

    if screen.show_fullscreen:
        layout.operator(
            "screen.back_to_previous", icon='SCREEN_BACK', text="Back to Previous"
        )
        return

    workspace = getattr(context, "workspace", None)
    if workspace is not None and workspace.name == BASIC_WORKSPACE_NAME:
        # Zen mode: no workspace tab strip — just the centred mode slider.
        _draw_mode_slider(layout, context)
        return
    if hasattr(bpy.types, "MIXAR_MT_engine_workspaces"):
        layout.menu("MIXAR_MT_engine_workspaces", text="", icon='WORKSPACE')
    layout.template_ID_tabs(
        window, "workspace",
        new="workspace.add",
        menu="TOPBAR_MT_workspace_menu",
    )
    _draw_mode_slider(layout, context)


def _patched_draw_right(self, context):
    """Replacement for TOPBAR_HT_upper_bar.draw_right.

    Zen mode drops the scene and view-layer selectors entirely — the calm
    canvas keeps only the Cinema Mode pill and the profile chip, both of
    which are APPENDED to this header by other modules and so are drawn
    after this method regardless of what it renders. Engine mode defers to
    the original draw.
    """
    workspace = getattr(context, "workspace", None)
    if workspace is not None and workspace.name == BASIC_WORKSPACE_NAME:
        return
    # Two full datablock selectors plus Cinema/profile can consume more than
    # half the header. On narrower or scaled displays keep both selectors in
    # one native popover, leaving the mode switch's center lane available.
    scale = max(float(context.preferences.system.ui_scale), 0.01)
    if context.area.width / scale < 1640 and hasattr(bpy.types, "MIXAR_PT_scene_controls"):
        self.layout.popover(panel="MIXAR_PT_scene_controls", text="", icon='SCENE_DATA')
    elif _original_draw_right is not None:
        _original_draw_right(self, context)


def install_topbar_filter():
    """Install the topbar tab-strip filter monkey patch. Idempotent."""
    global _original_draw_left
    cls = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if cls is None:
        _logger.warning("TOPBAR_HT_upper_bar not found; skipping mode filter")
        return

    global _original_draw_right
    if _original_draw_left is None:
        _original_draw_left = cls.draw_left
    if _original_draw_right is None:
        _original_draw_right = cls.draw_right

    cls.draw_left = _patched_draw_left
    cls.draw_right = _patched_draw_right


def uninstall_topbar_filter():
    """Restore the original topbar draw_left method. Idempotent."""
    global _original_draw_left
    global _original_draw_right
    cls = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if cls is None:
        return
    if _original_draw_left is not None:
        cls.draw_left = _original_draw_left
        _original_draw_left = None
    if _original_draw_right is not None:
        cls.draw_right = _original_draw_right
        _original_draw_right = None


classes = ()
