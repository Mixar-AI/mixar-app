# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rules of the island's model picker: one chip, one popup with source tabs.

The chip always names WHO answers (Mixie on credits, the user's own key, a
local model) and WHICH model. The popup opens on the current source's tab;
every row is a pick, and picking a row under another tab is the source
switch (a Mixie row pauses the key, a key row resumes or switches it). The
only rows that leave the popup are the footers that open AI Provider
Settings, because a secret is involved.

Everything here is `bpy`-free and pure: the three mirrors (credential,
preference, guest) are normalised by `picker_state`, `build_tabs` /
`build_rows` / `chip` derive what the C++ popup and chip draw, and `encode_*`
serialise them into the WindowManager strings the C++ reads (a record per
line of RS, fields split on FS — no JSON parser on the C++ side). The C++
decides nothing: it draws these strings and invokes `mixar.agent_pick`.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from mixar.modules.common.i18n import iface_, n_

from . import catalog_labels, model_menu, model_suggestions

TAB_MIXIE, TAB_KEY, TAB_LOCAL = "MIXIE", "KEY", "LOCAL"
ACTION_SETTINGS = "settings"
TABS = (TAB_MIXIE, TAB_KEY, TAB_LOCAL)
RS, FS = "\x1e", "\x1f"

# Row kinds the island's model card knows (agent_ui_model_card_data.cc).
ROW_MODEL, ROW_THINKING, ROW_LEVEL, ROW_FOOTER, ROW_NOTE = "model", "thinking", "level", "footer", "note"

MIXIE_LABEL = n_("Mixie")
LOCAL_LABEL = n_("Local")
ADD_KEY_TAB = n_("Add a key")
COST_CREDITS = n_("CREDITS")
COST_FREE = n_("NO CREDITS")
HEADING_MIXIE = n_("MIXAR MODELS")
HEADING_KEY = n_("YOUR KEY")
HEADING_ADD_KEY = n_("BRING YOUR OWN KEY")
HEADING_LOCAL = n_("ON THIS COMPUTER")
DEFAULT_ROW = n_("Mixar default")
#: The default row's trailing tag: the server picks the best model for the
#: agent. The island card draws it in the accent and rules it off from the
#: specific models below.
DEFAULT_META = n_("RECOMMENDED")
DEFAULT_CHIP = n_("Default")
SIGN_IN_NOTE = n_("Sign in to use Mixar models")
KEY_NEEDED_NOTE = n_("Key needed on this computer")
PAUSED_NOTE = n_("Paused — pick a model to switch back")
EMPTY_NOTE = n_("No models available — contact support")
NOT_ON_PLAN = n_("Not on your plan")
MANAGE_KEY = n_("Manage key…")
ENTER_KEY = n_("Enter key…")
SETUP_LOCAL = n_("Set up local model…")
CHANGE_SLUG = n_("Change model slug…")
LOADING_MESSAGE = n_("Loading your AI provider settings…")


@dataclass(frozen=True)
class Tab:
    id: str
    label: str
    enabled: bool = True
    cost: str = ""
    note: str = ""
    heading: str = ""
    #: "settings": the tab is an action, not a page — a click opens AI
    #: Provider Settings at once (no key saved: nothing to pick from).
    action: str = ""


@dataclass(frozen=True)
class Row:
    tab: str
    kind: str
    label: str
    meta: str = ""
    current: bool = False
    enabled: bool = True
    provider: str = ""
    model: str = ""
    thinking: str = ""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _pausable(credential):
    """credential_state.pausable on a snapshot (imported late: the state
    module mirrors through this one)."""
    from . import credential_state
    return credential_state.pausable(dict(credential_state._DEFAULTS, **credential))


def loading(credential: Dict[str, Any], preference: Dict[str, Any]) -> bool:
    """The hosted pick says a key answers but this launch's credential read
    has not landed: whether that key can be paused (a Mixie pick) is not
    known yet, so the card waits instead of guessing "open the settings".
    Only a server payload marks a key active, so an active one is loaded; a
    snapshot without the flag (an older caller) counts as loaded too."""
    return (bool(preference.get("mixar_agent_model_byok_active"))
            and not credential.get("byok_is_active")
            and not credential.get("byok_state_loaded", True))


def picker_state(credential: Dict[str, Any], preference: Dict[str, Any], *,
                 guest: bool = False, signed_in: bool = True, pending: str = "",
                 switching: str = "", busy: bool = False) -> Dict[str, Any]:
    """One dict the rules read, from the credential and preference mirrors.
    Mixar's own models need an account: signed out or on a guest, the Mixie
    tab still lists the catalog, disabled under a sign-in note, while a key
    of your own (Add a key, Local) works as usual.
    ``pending`` is the island mutation in flight (`credential_state.pending`);
    ``busy`` any other account change still unanswered (a hosted pick, a
    dialog save / removal). ``switching`` is the model an in-place switch is
    saving: the chip names it (dimmed, BUSY) until the save lands or fails."""
    active = bool(credential.get("byok_is_active"))
    provider = (credential.get("byok_current_provider") or "") if active else ""
    local_active = active and model_suggestions.is_local(provider)
    resumable = bool(credential.get("byok_key_resumable")) and not active
    resume_provider = (credential.get("byok_resume_provider") or "") if resumable else ""
    return {
        "source": TAB_LOCAL if local_active else (TAB_KEY if active else TAB_MIXIE),
        "key_provider": "" if local_active else provider,
        "key_model": ((switching or credential.get("byok_current_model") or "")
                      if active and not local_active else ""),
        "key_missing": active and bool(credential.get("byok_device_key_missing")),
        "local_model": (credential.get("byok_current_model") or "") if local_active else "",
        "resumable": resumable and not model_suggestions.is_local(resume_provider),
        "resume_provider": resume_provider,
        "resume_model": (credential.get("byok_resume_model") or "") if resumable else "",
        "pausable": _pausable(credential),
        "hosted_provider": preference.get("mixar_agent_model_provider") or "",
        "hosted_model": preference.get("mixar_agent_model_id") or "",
        "hosted_label": preference.get("mixar_agent_model_label") or "",
        "hosted_thinking": preference.get("mixar_agent_model_thinking") or "",
        "hosted_eligible": bool(preference.get("mixar_agent_model_eligible", True)),
        "guest": bool(guest),
        "hosted_ok": bool(signed_in) and not guest,
        "pending": pending or "",
        "busy": bool(busy),
        "loading": loading(credential, preference),
    }


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def _provider_name(provider: str) -> str:
    """The badge / tab name of a key's provider: a brand from the catalog,
    drawn as given; only the "Local" word is translated."""
    label = catalog_labels.chip_provider_label(provider)
    return iface_(label) if model_suggestions.is_local(provider) else label


def build_tabs(state: Dict[str, Any]) -> List[Tab]:
    # Always open: signed out, its rows say why they are off (_mixie_rows).
    tabs = [Tab(TAB_MIXIE, iface_(MIXIE_LABEL), cost=iface_(COST_CREDITS),
                heading=iface_(HEADING_MIXIE))]
    if state["key_provider"]:
        tabs.append(Tab(TAB_KEY, _provider_name(state["key_provider"]),
                        cost=iface_(COST_FREE), heading=iface_(HEADING_KEY),
                        note=iface_(KEY_NEEDED_NOTE) if state["key_missing"] else ""))
    elif state["resumable"]:
        tabs.append(Tab(TAB_KEY, _provider_name(state["resume_provider"]),
                        cost=iface_(COST_FREE), note=iface_(PAUSED_NOTE), heading=iface_(HEADING_KEY)))
    else:
        tabs.append(Tab(TAB_KEY, iface_(ADD_KEY_TAB), cost=iface_(COST_FREE),
                        heading=iface_(HEADING_ADD_KEY), action=ACTION_SETTINGS))
    if state["source"] == TAB_LOCAL:
        tabs.append(Tab(TAB_LOCAL, iface_(LOCAL_LABEL), cost=iface_(COST_FREE),
                        heading=iface_(HEADING_LOCAL)))
    return tabs


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _mixie_rows(state, models: Sequence[Dict[str, Any]]) -> List[Row]:
    rows: List[Row] = []
    live = state["hosted_ok"]
    if not live:
        # Shown only inside the card, above the catalog it greys out.
        rows.append(Row(TAB_MIXIE, ROW_NOTE, iface_(SIGN_IN_NOTE), enabled=False))
    if not models:
        return rows or [Row(TAB_MIXIE, ROW_NOTE, iface_(EMPTY_NOTE), enabled=False)]
    no_pick = not state["hosted_provider"] and not state["hosted_model"]
    rows.append(Row(TAB_MIXIE, ROW_MODEL, iface_(DEFAULT_ROW), meta=iface_(DEFAULT_META),
                    current=no_pick, enabled=live))
    for record in models:
        provider = record.get("provider_id") or ""
        model = record.get("model_id") or ""
        if not provider or not model:
            continue
        levels = [lv for lv in (record.get("thinking_levels") or []) if lv]
        eligible = bool(record.get("eligible", True))
        is_current = provider == state["hosted_provider"] and model == state["hosted_model"]
        # The current model's row keeps its saved level: picking it again (its
        # row body also folds the thinking disclosure) must not reset it.
        rows.append(Row(TAB_MIXIE, ROW_MODEL, record.get("model_label") or model,
                        meta="" if eligible else iface_(NOT_ON_PLAN),
                        current=is_current, enabled=live and eligible,
                        provider=provider, model=model,
                        thinking=state["hosted_thinking"] if is_current else ""))
        if is_current:
            if levels:
                # The disclosure and its levels always ride the wire; the
                # island card folds them (it owns that state, not Python).
                rows.append(Row(TAB_MIXIE, ROW_THINKING,
                                model_menu.format_thinking_label(state["hosted_thinking"]),
                                enabled=live, provider=provider, model=model))
                for level in levels:
                    rows.append(Row(TAB_MIXIE, ROW_LEVEL, iface_(model_menu.format_thinking_level(level)),
                                    current=level == state["hosted_thinking"], enabled=live,
                                    provider=provider, model=model, thinking=level))
    return rows


def _key_rows(state) -> List[Row]:
    rows: List[Row] = []
    provider = state["key_provider"] or (state["resume_provider"] if state["resumable"] else "")
    if not provider:
        return rows  # The tab itself opens the settings (Tab.action).
    paused = not state["key_provider"]
    current_model = state["resume_model"] if paused else state["key_model"]
    live = not state["key_missing"]
    if model_suggestions.is_openrouter(provider):
        rows.append(Row(TAB_KEY, ROW_MODEL, current_model or "—",
                        meta=catalog_labels.chip_provider_label(provider),
                        current=not paused, enabled=live and bool(current_model),
                        provider=provider, model=current_model))
        rows.append(Row(TAB_KEY, ROW_FOOTER, iface_(CHANGE_SLUG)))
        return rows
    listed = [(mid, label) for mid, label, _desc in model_suggestions.get_model_items(provider)
              if mid != 'NONE']
    if current_model and current_model not in {mid for mid, _label in listed}:
        # A provider with no catalog list (Kimi) or a model the catalog has
        # since dropped: the key's own model still gets its row.
        listed.insert(0, (current_model, catalog_labels.chip_model_label(provider, current_model)))
    for mid, label in listed:
        rows.append(Row(TAB_KEY, ROW_MODEL, label, current=(not paused and mid == current_model),
                        meta=iface_(n_("saved")) if (paused and mid == current_model) else "",
                        enabled=live, provider=provider, model=mid))
    rows.append(Row(TAB_KEY, ROW_FOOTER, iface_(ENTER_KEY) if state["key_missing"] else iface_(MANAGE_KEY)))
    return rows


def _local_rows(state) -> List[Row]:
    rows = [Row(TAB_LOCAL, ROW_MODEL, state["local_model"] or iface_(LOCAL_LABEL), current=True,
                provider="local", model=state["local_model"])]
    rows.append(Row(TAB_LOCAL, ROW_FOOTER, iface_(SETUP_LOCAL)))
    return rows


def build_rows(state: Dict[str, Any], models: Sequence[Dict[str, Any]]) -> List[Row]:
    """Rows of EVERY tab (the C++ filters by the open tab, so a tab click is
    a pure RNA write and the popup rebuilds without a Python round trip)."""
    rows = _mixie_rows(state, models)
    rows += _key_rows(state)
    if state["source"] == TAB_LOCAL:
        rows += _local_rows(state)
    return rows


# ---------------------------------------------------------------------------
# The chip
# ---------------------------------------------------------------------------

STATE_OK, STATE_KEY_NEEDED, STATE_BUSY = "OK", "KEY_NEEDED", "BUSY"


def chip(state: Dict[str, Any]) -> Dict[str, str]:
    """``{source, label, name, state}``: the badge word, the model name and
    the fill the chip takes."""
    source = state["source"]
    if source == TAB_LOCAL:
        label, name = iface_(LOCAL_LABEL), state["local_model"]
    elif source == TAB_KEY:
        label = _provider_name(state["key_provider"])
        name = catalog_labels.chip_model_label(state["key_provider"], state["key_model"])
    else:
        label = iface_(MIXIE_LABEL)
        name = model_menu.chip_label(state["hosted_label"], state["hosted_thinking"]) or iface_(DEFAULT_CHIP)
    # BUSY for every gate but a turn in flight: the island card words its
    # gate from this state ("Saving your change…" versus "Finish or stop
    # the current reply"), and the chip dims.
    waiting = state["pending"] or state.get("busy") or state.get("loading")
    kind = STATE_BUSY if waiting else (STATE_KEY_NEEDED if state["key_missing"] else STATE_OK)
    return {"source": source, "label": label, "name": name, "state": kind}


# ---------------------------------------------------------------------------
# Wire format for the C++ popup (one record per RS, fields on FS)
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return (text or "").replace(RS, " ").replace(FS, " ")


def encode_tabs(tabs: Sequence[Tab]) -> str:
    return RS.join(FS.join([_clean(t.id), _clean(t.label), "1" if t.enabled else "0", _clean(t.cost),
                            _clean(t.note), _clean(t.heading), _clean(t.action)])
                   for t in tabs)


def encode_rows(rows: Sequence[Row]) -> str:
    """Every field is scrubbed: an OpenRouter slug (provider/model ids ride
    back to `mixar.agent_pick`) is user-typed, and one stray separator would
    shift the C++ reader's nine fields."""
    return RS.join(FS.join([_clean(r.tab), _clean(r.kind), _clean(r.label), _clean(r.meta),
                            "1" if r.current else "0", "1" if r.enabled else "0",
                            _clean(r.provider), _clean(r.model), _clean(r.thinking)])
                   for r in rows)


def decode_tabs(text: str) -> List[Tab]:
    """The C++ reader's contract, in Python, so a test can round-trip it."""
    out = []
    for rec in (text or "").split(RS):
        if not rec:
            continue
        f = rec.split(FS)
        out.append(Tab(f[0], f[1], f[2] == "1", f[3], f[4], f[5], f[6] if len(f) > 6 else ""))
    return out


def decode_rows(text: str) -> List[Row]:
    out = []
    for rec in (text or "").split(RS):
        if not rec:
            continue
        f = rec.split(FS)
        out.append(Row(f[0], f[1], f[2], f[3], f[4] == "1", f[5] == "1", f[6], f[7], f[8]))
    return out
