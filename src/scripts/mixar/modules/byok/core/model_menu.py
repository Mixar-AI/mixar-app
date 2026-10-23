# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Wording rules for the hosted agent model, free of `bpy`.

The island's model card decides its rows in `core/picker.py`; what is left
here is the wording both it and the preference mirror share:
`chip_label()` (what the WM `mixar_agent_model_label` mirror holds),
`effective_thinking()` (the level a turn runs at: saved, else the catalog
default), `format_thinking_label()` / `format_thinking_level()` (the
"Thinking: High" disclosure and its levels) and `display_model_label()`
(model-only copy, including older provider-prefixed server echoes).
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


def effective_thinking(provider: str, model: str, saved: str) -> str:
    """The level a turn on this model actually runs at: the saved one, else
    the model's catalog default (`default_thinking_level`); "" when neither
    is known (an older backend: nothing is spelled out or ticked)."""
    if saved or not model:
        return saved or ""
    from . import model_suggestions

    return model_suggestions.default_thinking_level(provider, model)


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
    is not running on. ``thinking_level`` is the level the turn runs at
    (`effective_thinking`: the saved one, else the catalog default, so the
    default is spelled out too); empty only when neither is known.
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
