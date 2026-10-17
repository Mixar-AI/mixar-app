# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager mirror of the hosted agent-model pick.

A separate file from `byok_props`: these properties belong to the platform
picker, not the BYOK dialog, and their only writer is
`core/preference_state.apply_to_wm()`. Nothing here ever writes them — RNA is
the channel, the dict in `preference_state` is the source of truth.

**These names are a cross-language contract.** The Mixie Chat footer button and
the Agent Bubble island chip are drawn in C++ and read them directly:
`..._label` is the text on the button (empty -> "Mixie") and `..._byok_active`
is what greys it out. Renaming one silently blanks a control in both surfaces.

**`mixar_agent_model_label` here is the COMPOSED chip text**, not the raw
model label: `preference_state.apply_to_wm()` writes
`model_menu.chip_label(...)` — "GPT 5.6 Sol · High" once a thinking level is
saved, the BYOK indicator (`model_menu.BYOK_CHIP_TEXT`) while a user key
overrides the pick. The dict field of the same name in `preference_state`
stays model-only; read that, never this property, when you need the model.

On WindowManager rather than Scene, like every other agent-settings mirror: the
pick is per-account, not per-.blend, and WindowManager properties are not
serialized into a file that could then carry another account's pick.
"""

import bpy
from bpy.props import BoolProperty, StringProperty

_WM_ATTRS = (
    'mixar_agent_model_provider',
    'mixar_agent_model_id',
    'mixar_agent_model_label',
    'mixar_agent_model_thinking',
    'mixar_agent_model_byok_active',
    'mixar_agent_model_eligible',
    'mixar_agent_source',
    'mixar_agent_source_label',
    'mixar_agent_chip_name',
    'mixar_agent_source_state',
    'mixar_agent_tabs',
    'mixar_agent_rows',
)


def register():
    WM = bpy.types.WindowManager

    WM.mixar_agent_model_provider = StringProperty(
        name="Agent Model Provider",
        description="Provider id of the saved hosted-agent model pick",
        default='',
    )
    WM.mixar_agent_model_id = StringProperty(
        name="Agent Model",
        description="Model id of the saved hosted-agent model pick",
        default='',
    )
    WM.mixar_agent_model_label = StringProperty(
        name="Agent Model Label",
        description=(
            "Composed picker chip text: model label plus saved thinking level, "
            "or the BYOK indicator while your own key overrides the pick"
        ),
        default='',
    )
    WM.mixar_agent_model_thinking = StringProperty(
        name="Agent Model Thinking Level",
        description="Saved thinking level; empty means the model's own default",
        default='',
    )
    WM.mixar_agent_model_byok_active = BoolProperty(
        name="Agent Model Overridden By BYOK",
        description=(
            "True while your own API key is configured — it takes precedence "
            "over the hosted model pick, so the picker is disabled"
        ),
        default=False,
    )
    WM.mixar_agent_model_eligible = BoolProperty(
        name="Agent Model Eligible",
        description="False when the saved model is not available on your plan",
        default=True,
    )
    # The island's model chip and its popup (core/picker.py decides, C++
    # draws: agent_ui_provider.cc, agent_ui_model_card*.cc). Written only by
    # `picker_mirror.apply_to_wm`. `_tabs` / `_rows` are RS/FS-separated
    # records (`picker.encode_*`); the card keeps its open tab and thinking
    # disclosure itself.
    WM.mixar_agent_source = StringProperty(default="MIXIE", options={'SKIP_SAVE'})
    WM.mixar_agent_source_label = StringProperty(
        name="Agent Source", description="Who answers the agent: Mixie, your key's provider, or Local",
        default="", options={'SKIP_SAVE'})
    WM.mixar_agent_chip_name = StringProperty(
        name="Agent Model Name", description="The model the agent runs on", default="",
        options={'SKIP_SAVE'})
    WM.mixar_agent_source_state = StringProperty(default="OK", options={'SKIP_SAVE'})
    WM.mixar_agent_tabs = StringProperty(default="", options={'SKIP_SAVE'})
    WM.mixar_agent_rows = StringProperty(default="", options={'SKIP_SAVE'})
    # Fill them once at start-up: signed out, no credential or catalog event
    # would ever write them, and the chip and card would stay blank.
    bpy.app.timers.register(_first_mirror, first_interval=0.1)


def _first_mirror():
    try:
        from ...core import picker_mirror
        picker_mirror.apply_to_wm()
    except Exception:
        pass
    return None


def unregister():
    WM = bpy.types.WindowManager
    for attr in _WM_ATTRS:
        try:
            delattr(WM, attr)
        except AttributeError:
            pass
