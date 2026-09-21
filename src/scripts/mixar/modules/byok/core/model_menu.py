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
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

#: Shown when the catalog is empty — offline, pre-auth, or a backend that has
#: published nothing. Never replaced by a hardcoded model list: a
#: backend-authoritative list fails CLOSED.
EMPTY_SENTINEL_TEXT = "No models available — contact support"

#: Shown at the top of the menu while a user key is configured. The server
#: resolves BYOK ahead of any stored platform pick, so the pick is inert until
#: the key is removed — saying so beats a menu of silently dead rows.
BYOK_NOTE_TEXT = "Your own API key is in use — it overrides this pick"

RESET_TEXT = "Reset to default"

#: The chat's route to the dialog also offered in the profile menu. Keep it
#: enabled while BYOK is active so users can clear the key overriding their
#: hosted pick, including when the model catalog is empty.
BYOK_SETUP_TEXT = "Use my own API key…"
BYOK_MANAGE_TEXT = "Change or remove my API key…"

#: Middle dot, not a hyphen: the provider and the model are peers, and the
#: label is the only place the provider is named at all (no grouping, no
#: nesting — a deliberately flat list).
LABEL_SEPARATOR = " · "


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


def format_model_label(provider_label: str, model_label: str) -> str:
    """The flat row label: ``"Anthropic · Claude Sonnet 4.6"``."""
    provider = (provider_label or "").strip()
    model = (model_label or "").strip()
    if not provider:
        return model
    if not model:
        return provider
    return provider + LABEL_SEPARATOR + model


def format_thinking_label(level: str) -> str:
    """Sub-row wording for one thinking level."""
    text = (level or "").strip()
    if not text:
        return "Thinking"
    return "Thinking: " + text.replace("_", " ").title()


def build_rows(
    models: Sequence[Dict[str, Any]],
    *,
    active_provider: str = "",
    active_model: str = "",
    active_thinking: str = "",
    byok_active: bool = False,
) -> List[MenuRow]:
    """Rows for the picker, in the order the backend returned the models.

    ``models`` is `model_suggestions.get_platform_models()` — already filtered
    to `platform_available` and already in server order. It is NEVER re-sorted
    here: providers arrive sorted by label and models in the admin-configured
    display order, and a client-side sort would silently disagree with the
    admin dashboard.
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
        rows.append(MenuRow(kind="NOTE", label=BYOK_NOTE_TEXT, enabled=False))

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
                label=format_model_label(
                    record.get("provider_label") or provider,
                    record.get("model_label") or model,
                ),
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
        MenuRow(kind="RESET", label=RESET_TEXT, enabled=not byok_active)
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
