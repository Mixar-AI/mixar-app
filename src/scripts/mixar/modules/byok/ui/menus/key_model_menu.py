# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island key chip's model dropdown.

**`bl_idname` is a cross-language contract.** While the user's own key is in
use, the island draws a chip after the Mixie | Custom AI toggle naming the
provider and model ("Claude API · Opus 5.5 v"); its model pill is a native
pulldown that opens this menu. Each row runs `mixar_byok.switch_model`, which
re-sends the key this computer holds on another model without opening AI
Provider Settings.

The rows are the provider's catalog models, exactly the ones the settings
dialog offers for it. OpenRouter (any slug) and Local (whatever runs on this
machine) have no fixed list, so the island draws no dropdown for them and
this menu is never reached; it still fails closed with a note.
"""

from bpy.types import Menu

from ...core import credential_state, model_suggestions
from ..operators.byok_dialog_support import TURN_IN_FLIGHT_MESSAGE, turn_in_flight

KEY_MODEL_MENU_ID = "MIXAR_BYOK_MT_key_model"
OP_SWITCH = "mixar_byok.switch_model"


def menu_rows(snapshot, switching=""):
    """``[(model_id, label, active)]`` for the key's provider, or [] when the
    provider has no fixed list. Pure, so the rule is testable without Blender."""
    if not snapshot.get("byok_is_active"):
        return []
    provider = snapshot.get("byok_current_provider") or ""
    if (not provider or model_suggestions.is_openrouter(provider)
            or model_suggestions.is_local(provider)):
        return []
    current = switching or snapshot.get("byok_current_model") or ""
    return [(mid, label, mid == current)
            for mid, label, _desc in model_suggestions.get_model_items(provider)
            if mid != 'NONE']


class MIXAR_BYOK_MT_key_model(Menu):
    """Choose which model your API key runs the agent on"""

    bl_idname = KEY_MODEL_MENU_ID
    bl_label = "Model"

    def draw(self, context):
        layout = self.layout
        layout.ui_units_x = 12
        switching = credential_state.switching()
        busy = bool(credential_state.pending())
        rows = menu_rows(credential_state.snapshot(), switching)
        if not rows:
            line = layout.row()
            line.enabled = False
            line.label(text="No models to switch to")
            return
        if turn_in_flight(context):
            # The running turn keeps its model; say so instead of greying
            # rows with no explanation (the operator's poll greys them too).
            line = layout.row()
            line.enabled = False
            line.label(text=TURN_IN_FLIGHT_MESSAGE)
            busy = True
        for mid, label, active in rows:
            line = layout.row()
            line.scale_y = 1.15
            # One island mutation at a time: the chip names a switch's target
            # until it lands, and a toggle in flight holds the rows too.
            line.enabled = not busy
            props = line.operator(OP_SWITCH, text=label, translate=False)
            props.model = mid
            if hasattr(line, "mixar_cinema_row"):
                line.mixar_cinema_row(kind="ACTIVE" if active else "OPTION")


classes = (MIXAR_BYOK_MT_key_model,)
