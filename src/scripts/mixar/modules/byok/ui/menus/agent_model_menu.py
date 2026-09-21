# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The hosted agent-model picker menu.

**`bl_idname` is a cross-language contract.** Both surfaces draw one button in
C++ — the Mixie Chat footer's bottom control row and the Agent Bubble island's
chip row — and that button is a `wm.call_menu` whose ``name`` is this id. Python
owns the whole picker; C++ owns a label and a click. Renaming it leaves two
buttons that pop nothing.

**Two menus, one level deep.** The parent lists the models flat; the thinking
levels live in a submenu that reads the CURRENT pick. Drawing every model's
levels inline made a 26-row menu, and Blender column-wraps a menu taller than
its window — the levels spilled into a second column and were clipped by the
island. One submenu also sidesteps registering a Menu class per model, because
the levels it shows are always the picked model's.

Presentation only: `core/model_menu` decides what appears and what is
clickable, because those rules (ineligible is greyed not hidden, BYOK greys
every row but the key route, an empty catalog fails closed) are worth testing
outside a running Blender.
"""

import bpy
from bpy.types import Menu

from ...core import model_menu, model_suggestions, preference_state

THINKING_MENU_ID = "MIXIE_CHAT_MT_agent_model_thinking"


def _set_props(props, row) -> None:
    """Copy a row's identity onto the set-operator's properties."""
    # Under Blender these are real operator properties; guard anyway so a
    # draw-time RNA hiccup costs one row rather than the whole menu.
    try:
        props.provider = row.provider
        props.model = row.model
        props.label = row.label if row.kind == "MODEL" else ""
        props.thinking_level = row.thinking_level
    except (AttributeError, TypeError):
        pass


def _draw_row(layout, row) -> None:
    """Emit one `MenuRow`."""
    if row.kind in {"NOTE", "SENTINEL"}:
        line = layout.row()
        line.enabled = False
        line.label(text=row.label)
        return

    line = layout.row()
    line.enabled = row.enabled

    if row.kind == "RESET":
        line.operator("mixar.agent_model_reset", text=row.label, icon='LOOP_BACK')
        return

    if row.kind == "BYOK":
        # A Menu's layout runs operators in an EXEC context, and the dialog
        # operator does all its work in invoke() (execute() is a deliberate
        # no-op) — so without this the row ran execute(), returned FINISHED
        # and opened nothing. Pinned by tests/test_agent_model_picker.py and
        # driven for real in tests/qa/agent_model_picker_e2e.py.
        line.operator_context = 'INVOKE_DEFAULT'
        # `row.active` means a key is currently in use — same icon pair the
        # topbar entry used before PR #1562 removed it.
        line.operator(
            "mixar_byok.open_dialog",
            text=row.label,
            icon='KEY_HLT' if row.active else 'PREFERENCES',
        )
        return

    if row.kind == "THINKING_MENU":
        line.menu(THINKING_MENU_ID, text=row.label, icon='SEQ_HISTOGRAM')
        return

    icon = 'RADIOBUT_ON' if row.active else 'RADIOBUT_OFF'
    _set_props(line.operator("mixar.agent_model_set", text=row.label, icon=icon), row)


def _current():
    """(models, snapshot) — the two inputs both menus are built from."""
    return model_suggestions.get_platform_models(), preference_state.snapshot()


class MIXIE_CHAT_MT_agent_model(Menu):
    """Choose which model runs the agent."""

    bl_idname = "MIXIE_CHAT_MT_agent_model"
    bl_label = "Agent Model"

    def draw(self, context):
        layout = self.layout
        models, current = _current()
        rows = model_menu.build_rows(
            models,
            active_provider=current["mixar_agent_model_provider"],
            active_model=current["mixar_agent_model_id"],
            active_thinking=current["mixar_agent_model_thinking"],
            byok_active=bool(current["mixar_agent_model_byok_active"]),
        )
        # A build without the BYOK dialog would draw a row that pops nothing;
        # the removed topbar entry guarded the same way.
        dialog_available = hasattr(bpy.types, "MIXAR_BYOK_OT_open_dialog")
        separated = False
        for index, row in enumerate(rows):
            if row.kind == "BYOK" and not dialog_available:
                continue
            # One rule above the tail, however many of its rows draw.
            tail = row.kind in {"THINKING_MENU", "RESET", "BYOK"}
            if tail and index and not separated:
                layout.separator()
                separated = True
            _draw_row(layout, row)


class MIXIE_CHAT_MT_agent_model_thinking(Menu):
    """Reasoning effort for the model currently picked."""

    bl_idname = THINKING_MENU_ID
    bl_label = "Thinking"

    def draw(self, context):
        layout = self.layout
        models, current = _current()
        rows = model_menu.build_thinking_rows(
            models,
            active_provider=current["mixar_agent_model_provider"],
            active_model=current["mixar_agent_model_id"],
            active_thinking=current["mixar_agent_model_thinking"],
        )
        if not rows:
            # The pick changed out from under an open menu.
            line = layout.row()
            line.enabled = False
            line.label(text="No thinking levels for this model")
            return
        for row in rows:
            _draw_row(layout, row)


classes = (
    MIXIE_CHAT_MT_agent_model,
    MIXIE_CHAT_MT_agent_model_thinking,
)
