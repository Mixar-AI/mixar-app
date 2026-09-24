# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Row model for the hosted agent-model picker.

The menu itself is three lines of `layout` calls in
`ui/menus/agent_model_menu.py`; everything that decides WHAT appears and
whether it is clickable lives here, free of `bpy`, so the rules that matter —
ineligible rows are greyed and never hidden, BYOK disables every row, an empty
catalog fails closed — are unit-testable rather than only observable in a
running app.

Row kinds:
    NOTE      non-interactive explanation (why everything is greyed)
    MODEL     one hosted model; clicking it saves the pick at the model's own
              default thinking level
    THINKING_MENU  the "Thinking: X" entry that opens the level submenu; drawn
              only when the CURRENT pick offers levels
    THINKING  one level inside that submenu (`build_thinking_rows`)
    RESET     drop the saved pick and fall back to the server default
    SENTINEL  the empty-catalog dead end
    BYOK      open the AI Provider Settings dialog shared with the profile menu

Also home to the two pure wording rules the island chip and the BYOK note
share: `chip_label()` (what the WM `mixar_agent_model_label` mirror holds) and
`byok_note_text()` (the NOTE row naming the key's provider and model).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

#: Shown when the catalog is empty — offline, pre-auth, or a backend that has
#: published nothing. Never replaced by a hardcoded model list: a
#: backend-authoritative list fails CLOSED.
EMPTY_SENTINEL_TEXT = "No models available — contact support"

#: Shown at the top of the menu while a user key is configured. The server
#: resolves BYOK ahead of any stored platform pick, so the pick is inert until
#: the key is removed — saying so beats a menu of silently dead rows. This is
#: the fallback wording; once the credential state names the provider and
#: model, `byok_note_text()` says which one ("Your key: <Provider> · <Model>").
BYOK_NOTE_TEXT = "Your API key controls the model"
BYOK_NOTE_PREFIX = "Your key: "

#: What the island chip reads while a user key overrides the hosted pick
#: (product decision: "Custom"; the no-pick chip stays "Mixie"). One constant
#: so the wording can be swapped in one place — e.g. "My Key", "Own Key".
BYOK_CHIP_TEXT = "Custom"

#: Separator between the model label and its thinking level on the chip.
CHIP_SEPARATOR = " · "

RESET_TEXT = "Mixie"

#: The chat's route to the dialog also offered in the profile menu. Keep it
#: enabled while BYOK is active so users can clear the key overriding their
#: hosted pick, including when the model catalog is empty.
BYOK_SETUP_TEXT = "Use my own API key…"
BYOK_MANAGE_TEXT = "Change or remove my API key…"

@dataclass(frozen=True)
class MenuRow:
    """One drawable row. `enabled` False means greyed, still visible."""

    kind: str
    label: str
    enabled: bool = True
    active: bool = False
    provider: str = ""
    model: str = ""
    thinking_level: str = ""
    #: MODEL: this model offers thinking levels. THINKING_MENU: always True.
    has_thinking: bool = False


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
    """Sub-row wording for one thinking level."""
    text = format_thinking_level(level)
    if not text:
        return "Thinking"
    return "Thinking: " + text


def chip_label(model_label: str, thinking_level: str = "", byok_active: bool = False) -> str:
    """The composed text the island chip draws.

    Empty means "no pick" and C++ falls back to "Mixie". A user key overrides
    every hosted pick, so the chip says so instead of naming a model the agent
    is not running on; the level rides along only when one is saved (empty is
    the model's own default, which the chip does not spell out).
    """
    if byok_active:
        return BYOK_CHIP_TEXT
    label = (model_label or "").strip()
    level = format_thinking_level(thinking_level)
    if label and level:
        return label + CHIP_SEPARATOR + level
    return label


def byok_note_text(provider_label: str = "", model_label: str = "") -> str:
    """The menu's BYOK note, naming the key's provider and model when known.

    Both unknown (the credential fetch has not landed) falls back to the
    generic wording rather than drawing "Your key: " over nothing.
    """
    parts = [part.strip() for part in (provider_label, model_label) if (part or "").strip()]
    if not parts:
        return BYOK_NOTE_TEXT
    return BYOK_NOTE_PREFIX + CHIP_SEPARATOR.join(parts)


def build_rows(
    models: Sequence[Dict[str, Any]],
    *,
    active_provider: str = "",
    active_model: str = "",
    active_thinking: str = "",
    byok_active: bool = False,
    byok_provider_label: str = "",
    byok_model_label: str = "",
) -> List[MenuRow]:
    """Rows for the picker, in the order the backend returned the models.

    ``models`` is `model_suggestions.get_platform_models()` — already filtered
    to `platform_available` and already in server order. It is NEVER re-sorted
    here: providers arrive sorted by label and models in the admin-configured
    display order, and a client-side sort would silently disagree with the
    admin dashboard.

    ``byok_provider_label`` / ``byok_model_label`` are the key's catalog
    labels (or raw ids) and only shape the NOTE row's wording.
    """
    rows: List[MenuRow] = []
    current_levels: List[str] = []

    if not models:
        # Still offer the key route: an empty catalog is exactly when a user
        # has nothing hosted to pick and their own key is the way forward.
        return [
            MenuRow(kind="SENTINEL", label=EMPTY_SENTINEL_TEXT, enabled=False),
            _byok_row(byok_active),
        ]

    if byok_active:
        rows.append(MenuRow(
            kind="NOTE",
            label=byok_note_text(byok_provider_label, byok_model_label),
            enabled=False,
        ))

    for record in models:
        provider = record.get("provider_id") or ""
        model = record.get("model_id") or ""
        if not provider or not model:
            # A malformed row costs one row, not the menu.
            continue
        levels = [
            level for level in (record.get("thinking_levels") or []) if level
        ]
        # BYOK wins over every row; ineligibility only over its own.
        enabled = not byok_active and bool(record.get("eligible", True))
        is_current = provider == active_provider and model == active_model
        rows.append(
            MenuRow(
                kind="MODEL",
                label=record.get("model_label") or model,
                enabled=enabled,
                active=is_current,
                provider=provider,
                model=model,
                has_thinking=bool(levels),
            )
        )
        if is_current:
            current_levels = levels

    # One submenu for the CURRENT pick, never a fan of inline levels. Five
    # models with four levels each is 20+ rows, and Blender column-wraps a
    # menu that tall — the levels spilled sideways into a second column and
    # were clipped by the island window. Levels are also per-model (Anthropic
    # offers `max`, Gemini does not), so a submenu that reads the current pick
    # shows exactly the right set without one registered class per model.
    if current_levels:
        rows.append(
            MenuRow(
                kind="THINKING_MENU",
                label=format_thinking_label(active_thinking),
                enabled=not byok_active,
                provider=active_provider,
                model=active_model,
                thinking_level=active_thinking,
                has_thinking=True,
            )
        )

    rows.append(
        MenuRow(kind="RESET", label=RESET_TEXT, enabled=not byok_active,
                active=not active_provider and not active_model)
    )
    rows.append(_byok_row(byok_active))
    return rows


def build_thinking_rows(
    models: Sequence[Dict[str, Any]],
    *,
    active_provider: str = "",
    active_model: str = "",
    active_thinking: str = "",
) -> List[MenuRow]:
    """Rows for the Thinking submenu — the CURRENT pick's levels, in order.

    Empty when nothing is picked or the picked model offers no levels; the
    parent then draws no submenu entry at all ("if available").
    """
    for record in models:
        if (record.get("provider_id") or "") != active_provider:
            continue
        if (record.get("model_id") or "") != active_model:
            continue
        levels = [lv for lv in (record.get("thinking_levels") or []) if lv]
        return [
            MenuRow(
                kind="THINKING",
                label=format_thinking_label(level),
                enabled=True,
                active=level == active_thinking,
                provider=active_provider,
                model=active_model,
                thinking_level=level,
            )
            for level in levels
        ]
    return []


def _byok_row(byok_active: bool) -> MenuRow:
    """The AI Provider Settings row.

    ``enabled`` is unconditionally True — it is the one row a configured key
    must NOT disable, because clearing that key is what it is for. ``active``
    carries "a key is in use" so the menu can pick the icon, the way the
    removed topbar entry did.
    """
    return MenuRow(
        kind="BYOK",
        label=BYOK_MANAGE_TEXT if byok_active else BYOK_SETUP_TEXT,
        enabled=True,
        active=byok_active,
    )
