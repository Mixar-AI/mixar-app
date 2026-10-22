# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Wording rules for the hosted agent model, free of `bpy`.

The island's model card decides its rows in `core/picker.py`; what is left
here is the wording both it and the preference mirror share:
`chip_label()` (what the WM `mixar_agent_model_label` mirror holds),
`format_thinking_label()` / `format_thinking_level()` (the "Thinking: High"
disclosure and its levels) and `display_model_label()` (model-only copy,
including older provider-prefixed server echoes).
"""

from mixar.modules.common.i18n import iface_, n_

#: What the legacy `mixar_agent_model_label` mirror reads while a user key
#: overrides the hosted pick (the island chip itself names the key's model).
BYOK_CHIP_TEXT = n_("Custom")

#: Separator between the model label and its thinking level on the chip.
CHIP_SEPARATOR = " · "


def display_model_label(provider: str, model: str, label: str = "") -> str:
    """Resolve model-only copy, including older provider-prefixed server echoes."""
    from . import model_suggestions

    for record in model_suggestions.get_platform_models():
        if record.get("provider_id") == provider and record.get("model_id") == model:
            return record.get("model_label") or model
    return (label or model).rsplit(" · ", 1)[-1].strip()


def format_thinking_level(level: str) -> str:
    """Title-cased wording for one thinking level (`medium_high` -> `Medium High`)."""
    return (level or "").strip().replace("_", " ").title()


def format_thinking_label(level: str) -> str:
    """Sub-row wording for one thinking level, translated (the card draws
    it as given)."""
    text = format_thinking_level(level)
    if not text:
        return iface_("Thinking")
    return iface_("Thinking: {level}").format(level=iface_(text))


def chip_label(model_label: str, thinking_level: str = "", byok_active: bool = False) -> str:
    """The composed text the island chip draws.

    Empty means "no pick" and C++ falls back to "Mixie". A user key overrides
    every hosted pick, so the chip says so instead of naming a model the agent
    is not running on; the level rides along only when one is saved (empty is
    the model's own default, which the chip does not spell out).
    """
    if byok_active:
        return iface_(BYOK_CHIP_TEXT)
    label = (model_label or "").strip()
    # The level words ("Low", "High", ...) are fixed vocabulary; the model
    # label is catalog data and stays as written.
    level = iface_(format_thinking_level(thinking_level))
    if label and level:
        return label + CHIP_SEPARATOR + level
    return label
