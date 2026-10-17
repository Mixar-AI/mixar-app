# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island's model picker: one chip, one popup with source tabs.

Pins `byok/core/picker.py` (what the chip says, which tabs and rows the
popup has, per state), the wire format the C++ reads, the mirror writer, and
`mixar.agent_pick` (which request each row makes).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import credential_state, key_store, model_suggestions, picker, picker_mirror, preference_state
from mixar.modules.byok.core.picker import TAB_KEY, TAB_LOCAL, TAB_MIXIE

CATALOG = {'providers': [
    {'id': 'anthropic', 'label': 'Anthropic', 'short_label': 'Claude API', 'models': [
        {'id': 'claude-opus-5-5', 'label': 'Claude Opus 5.5', 'short_label': 'Opus 5.5',
         'platform_available': True, 'thinking_levels': ['low', 'high']},
        {'id': 'claude-sonnet-5-5', 'label': 'Claude Sonnet 5.5', 'short_label': 'Sonnet 5.5',
         'platform_available': True},
    ]},
    {'id': 'openai', 'label': 'OpenAI', 'short_label': 'OpenAI API', 'models': [
        {'id': 'gpt-6-astra', 'label': 'GPT 6 Astra', 'short_label': 'GPT 6 Astra',
         'platform_available': True, 'eligible': False},
    ]},
]}


def _cred(**kw):
    base = dict(credential_state._DEFAULTS)
    base.update(kw)
    return base


def _pref(**kw):
    base = dict(preference_state._DEFAULTS)
    base.update(kw)
    return base


@pytest.fixture
def catalog():
    import copy
    saved = (list(model_suggestions._provider_cache), copy.deepcopy(model_suggestions._model_cache),
             copy.deepcopy(model_suggestions._platform_records), model_suggestions._populated_once)
    model_suggestions.populate_from_payload(CATALOG)
    yield model_suggestions.get_platform_models()
    model_suggestions.populate(*saved[:3])
    model_suggestions._populated_once = saved[3]


def _kinds(rows, tab):
    return [(r.kind, r.label, r.current, r.enabled) for r in rows if r.tab == tab]


# ---------------------------------------------------------------------------
# What the chip says and which tabs exist
# ---------------------------------------------------------------------------

def test_no_key_mixie_default(catalog):
    s = picker.picker_state(_cred(), _pref())
    assert s["source"] == TAB_MIXIE
    assert picker.chip(s) == {"source": TAB_MIXIE, "label": "Mixie", "name": "Default", "state": "OK"}
    tabs = picker.build_tabs(s)
    assert [(t.id, t.label, t.enabled) for t in tabs] == [(TAB_MIXIE, "Mixie", True), (TAB_KEY, "Add a key", True)]
    rows = picker.build_rows(s, catalog)
    assert _kinds(rows, TAB_MIXIE)[0] == ("model", "Mixar default", True, True)
    assert ("model", "GPT 6 Astra", False, False) in _kinds(rows, TAB_MIXIE)  # not on the plan: greyed, not hidden
    # No key saved: the tab is the action itself (one click to the settings), no page behind it.
    assert tabs[1].action == picker.ACTION_SETTINGS
    assert _kinds(rows, TAB_KEY) == []


def test_hosted_pick_with_thinking_names_the_model_and_offers_levels(catalog):
    s = picker.picker_state(_cred(), _pref(mixar_agent_model_provider="anthropic", mixar_agent_model_id="claude-opus-5-5",
                                           mixar_agent_model_label="Claude Opus 5.5", mixar_agent_model_thinking="high"))
    assert picker.chip(s)["name"] == "Claude Opus 5.5 · High"
    rows = _kinds(picker.build_rows(s, catalog), TAB_MIXIE)
    assert ("model", "Claude Opus 5.5", True, True) in rows
    assert ("thinking", "Thinking: High", False, True) in rows
    # The levels always ride the wire right after the disclosure; the card folds them.
    kinds = [r[0] for r in rows]
    at = kinds.index("thinking")
    assert kinds[at + 1:at + 3] == ["level", "level"]
    assert ("level", "Low", False, True) in rows and ("level", "High", True, True) in rows
    assert [r.thinking for r in picker.build_rows(s, catalog) if r.kind == "level"] == ["low", "high"]


def test_hosted_rows_follow_the_catalog_and_keep_provider_identity(catalog):
    s = picker.picker_state(_cred(), _pref(mixar_agent_model_provider="anthropic",
                                          mixar_agent_model_id="claude-sonnet-5-5"))
    rows = [r for r in picker.build_rows(s, catalog) if r.tab == TAB_MIXIE and r.kind == "model"]
    # "Mixar default" first, then the catalog's order verbatim; labels are
    # model names only, the provider rides in the payload.
    assert [r.label for r in rows] == ["Mixar default", "Claude Opus 5.5", "Claude Sonnet 5.5", "GPT 6 Astra"]
    assert [(r.provider, r.model) for r in rows[1:]] == [
        ("anthropic", "claude-opus-5-5"), ("anthropic", "claude-sonnet-5-5"), ("openai", "gpt-6-astra")]
    assert [r.label for r in rows if r.current] == ["Claude Sonnet 5.5"]  # exactly one current


def test_own_key_in_use(catalog):
    s = picker.picker_state(_cred(byok_is_active=True, byok_current_provider="anthropic", byok_current_model="claude-opus-5-5",
                                  byok_record_resumable=True), _pref(mixar_agent_model_byok_active=True))
    assert s["source"] == TAB_KEY and s["pausable"]
    assert picker.chip(s) == {"source": TAB_KEY, "label": "Claude API", "name": "Opus 5.5", "state": "OK"}
    tabs = picker.build_tabs(s)
    assert [(t.id, t.label, t.cost) for t in tabs] == [(TAB_MIXIE, "Mixie", "CREDITS"), (TAB_KEY, "Claude API", "NO CREDITS")]
    rows = _kinds(picker.build_rows(s, catalog), TAB_KEY)
    assert rows == [("model", "Claude Opus 5.5", True, True), ("model", "Claude Sonnet 5.5", False, True),
                    ("footer", "Manage key…", False, True)]


def test_key_needed_on_this_device(catalog):
    s = picker.picker_state(_cred(byok_is_active=True, byok_current_provider="anthropic", byok_current_model="claude-opus-5-5",
                                  byok_device_key_missing=True), _pref(mixar_agent_model_byok_active=True))
    assert picker.chip(s)["state"] == "KEY_NEEDED"
    tab = [t for t in picker.build_tabs(s) if t.id == TAB_KEY][0]
    assert tab.note == "Key needed on this computer"
    rows = _kinds(picker.build_rows(s, catalog), TAB_KEY)
    assert all(not enabled for kind, _l, _c, enabled in rows if kind == "model")
    assert rows[-1] == ("footer", "Enter key…", False, True)


def test_paused_key_is_a_tab_whose_rows_resume(catalog):
    s = picker.picker_state(_cred(byok_key_resumable=True, byok_resume_provider="anthropic",
                                  byok_resume_model="claude-sonnet-5-5"), _pref())
    assert s["source"] == TAB_MIXIE and s["resumable"]
    tab = [t for t in picker.build_tabs(s) if t.id == TAB_KEY][0]
    assert (tab.label, tab.note) == ("Claude API", "Paused — pick a model to switch back")
    rows = picker.build_rows(s, catalog)
    saved = [r for r in rows if r.tab == TAB_KEY and r.meta == "saved"]
    assert [r.model for r in saved] == ["claude-sonnet-5-5"]
    assert all(not r.current for r in rows if r.tab == TAB_KEY)  # nothing on the key tab answers now


def test_local_source(catalog):
    s = picker.picker_state(_cred(byok_is_active=True, byok_current_provider="local", byok_current_model="llama3"), _pref())
    assert s["source"] == TAB_LOCAL and not s["pausable"]
    assert picker.chip(s)["label"] == "Local" and picker.chip(s)["name"] == "llama3"
    assert [t.id for t in picker.build_tabs(s)] == [TAB_MIXIE, TAB_KEY, TAB_LOCAL]
    assert _kinds(picker.build_rows(s, catalog), TAB_LOCAL) == [("model", "llama3", True, True), ("footer", "Set up local model…", False, True)]


def test_openrouter_has_a_slug_not_a_list(catalog):
    s = picker.picker_state(_cred(byok_is_active=True, byok_current_provider="openrouter",
                                  byok_current_model="anthropic/claude-opus-4.8"), _pref(mixar_agent_model_byok_active=True))
    rows = _kinds(picker.build_rows(s, catalog), TAB_KEY)
    assert rows == [("model", "anthropic/claude-opus-4.8", True, True), ("footer", "Change model slug…", False, True)]


def test_guest_and_empty_catalog(catalog):
    s = picker.picker_state(_cred(), _pref(), guest=True)
    tab = picker.build_tabs(s)[0]
    assert not tab.enabled and tab.note == "Sign in to use Mixar models"
    assert all(not r.enabled for r in picker.build_rows(s, catalog) if r.tab == TAB_MIXIE)
    s = picker.picker_state(_cred(), _pref())
    assert _kinds(picker.build_rows(s, []), TAB_MIXIE) == [("note", "No models available — contact support", False, False)]


def test_busy_is_a_chip_state(catalog):
    s = picker.picker_state(_cred(), _pref(), pending="switch")
    assert picker.chip(s)["state"] == "BUSY"


def test_wire_format_round_trips(catalog):
    s = picker.picker_state(_cred(byok_is_active=True, byok_current_provider="anthropic", byok_current_model="claude-opus-5-5"), _pref())
    tabs, rows = picker.build_tabs(s), picker.build_rows(s, catalog)
    assert [t.heading for t in tabs] == ["MIXAR MODELS", "YOUR KEY"]
    assert [t.cost for t in tabs] == ["CREDITS", "NO CREDITS"]
    assert picker.decode_tabs(picker.encode_tabs(tabs)) == tabs
    assert picker.decode_rows(picker.encode_rows(rows)) == rows
    # A label can never break a record: separators are scrubbed.
    assert picker.encode_rows([picker.Row(TAB_KEY, "model", "a\x1eb\x1fc")]).count("\x1e") == 0


# ---------------------------------------------------------------------------
# The mirror writer
# ---------------------------------------------------------------------------

def test_mirror_writes_the_chip_and_the_lists(catalog, monkeypatch):
    monkeypatch.setattr(key_store, "check_resumable_async", lambda on_done: None)
    monkeypatch.setattr(key_store, "check_presence_async", lambda provider, on_done: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    monkeypatch.setattr(preference_state, "_redraw", lambda: None)
    wm = SimpleNamespace(mixar_agent_rows="")
    credential_state.clear(wm)
    preference_state.clear(wm)
    assert wm.mixar_agent_source == TAB_MIXIE and wm.mixar_agent_chip_name == "Default"
    assert picker.decode_tabs(wm.mixar_agent_tabs)[1].label == "Add a key"
    credential_state.apply_from_payload({"byok_active": True, "items": [{"provider": "anthropic", "model": "claude-opus-5-5"}]}, wm)
    assert wm.mixar_agent_source == TAB_KEY and wm.mixar_agent_source_label == "Claude API"
    assert [t.id for t in picker.decode_tabs(wm.mixar_agent_tabs)] == [TAB_MIXIE, TAB_KEY]
    # The card's own state never rides the mirror.
    assert not hasattr(wm, "mixar_agent_popup_tab") and not hasattr(wm, "mixar_agent_thinking_open")
    credential_state.clear(wm)


# ---------------------------------------------------------------------------
# mixar.agent_pick: which request each row makes
# ---------------------------------------------------------------------------

@pytest.fixture
def pick(monkeypatch, catalog):
    from mixar.modules.byok.ui.operators import agent_pick_ops as ops
    calls = SimpleNamespace(set=[], reset=[], pause=[], resume=[], switch=[], dialog=[])
    monkeypatch.setattr(ops.agent_model_ops, "set_hosted", lambda wm, p, m, t="", label="": calls.set.append((p, m, t)) or True)
    monkeypatch.setattr(ops.agent_model_ops, "reset_hosted", lambda wm: calls.reset.append(True) or True)
    monkeypatch.setattr(ops.byok_toggle_ops, "pause", lambda wm, then=None: calls.pause.append(then) or True)
    monkeypatch.setattr(ops.byok_toggle_ops, "resume", lambda wm, model=None: calls.resume.append(model) or True)
    monkeypatch.setattr(ops.byok_switch_ops, "switch", lambda wm, model: calls.switch.append(model) or True)
    monkeypatch.setattr(ops, "_open_settings", lambda: calls.dialog.append(True) or {'FINISHED'})
    monkeypatch.setattr(ops, "turn_in_flight", lambda context: False)
    monkeypatch.setattr(ops, "account_busy", lambda: False)
    monkeypatch.setattr(key_store, "check_resumable_async", lambda on_done: None)
    monkeypatch.setattr(key_store, "check_presence_async", lambda provider, on_done: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    monkeypatch.setattr(preference_state, "_redraw", lambda: None)
    wm = SimpleNamespace()
    credential_state.clear(wm)
    preference_state.clear(wm)

    def run(source, provider="", model="", thinking=""):
        op = ops.MIXAR_OT_agent_pick()
        op.source, op.provider, op.model, op.thinking = source, provider, model, thinking
        return op.execute(SimpleNamespace(window_manager=wm, scene=SimpleNamespace()))

    yield run, calls, wm
    credential_state.clear(wm)
    preference_state.clear(wm)


def test_mixie_row_sets_or_resets_the_hosted_pick(pick):
    run, calls, wm = pick
    assert run(TAB_MIXIE, "anthropic", "claude-opus-5-5", "high") == {'FINISHED'}
    assert calls.set == [("anthropic", "claude-opus-5-5", "high")]
    preference_state.apply_local({"mixar_agent_model_provider": "anthropic",
                                  "mixar_agent_model_id": "claude-opus-5-5",
                                  "mixar_agent_model_thinking": "high"}, wm)
    assert run(TAB_MIXIE) == {'FINISHED'} and calls.reset == [True]
    assert calls.pause == [] and calls.dialog == []


def test_the_current_mixie_row_sends_nothing(pick):
    run, calls, wm = pick
    # No pick yet: "Mixar default" is current.
    assert run(TAB_MIXIE) == {'FINISHED'}
    preference_state.apply_local({"mixar_agent_model_provider": "anthropic",
                                  "mixar_agent_model_id": "claude-opus-5-5",
                                  "mixar_agent_model_thinking": "high"}, wm)
    assert run(TAB_MIXIE, "anthropic", "claude-opus-5-5", "high") == {'FINISHED'}
    assert calls.set == [] and calls.reset == []
    # Another level of the same model is a change.
    assert run(TAB_MIXIE, "anthropic", "claude-opus-5-5", "low") == {'FINISHED'}
    assert calls.set == [("anthropic", "claude-opus-5-5", "low")]


def test_the_current_mixie_row_while_a_key_answers_only_pauses(pick):
    run, calls, wm = pick
    credential_state.apply_from_payload({"byok_active": True, "items": [{"provider": "anthropic", "model": "claude-opus-5-5"}]}, wm)
    credential_state.set_resumable({"provider": "anthropic", "model": "claude-opus-5-5"})
    assert run(TAB_MIXIE) == {'FINISHED'} and len(calls.pause) == 1
    assert calls.pause[0]() is True
    assert calls.set == [] and calls.reset == []


def test_mixie_row_while_a_key_answers_pauses_then_picks(pick):
    run, calls, wm = pick
    credential_state.apply_from_payload({"byok_active": True, "items": [{"provider": "anthropic", "model": "claude-opus-5-5"}]}, wm)
    credential_state.set_resumable({"provider": "anthropic", "model": "claude-opus-5-5"})
    assert run(TAB_MIXIE, "anthropic", "claude-sonnet-5-5") == {'FINISHED'}
    assert len(calls.pause) == 1 and calls.set == []
    calls.pause[0]()  # the pause landed: the hosted pick follows
    assert calls.set == [("anthropic", "claude-sonnet-5-5", "")]


def test_mixie_row_while_an_unpausable_key_answers_opens_the_settings(pick):
    run, calls, wm = pick
    credential_state.apply_from_payload({"byok_active": True, "items": [{"provider": "local", "model": "llama3"}]}, wm)
    assert run(TAB_MIXIE, "anthropic", "claude-sonnet-5-5") == {'FINISHED'}
    assert calls.dialog == [True] and calls.pause == [] and calls.set == []


def test_key_rows_switch_resume_or_open_the_settings(pick):
    run, calls, wm = pick
    # No key saved: the key tab's rows are footers, but a stray pick opens the settings.
    assert run(TAB_KEY, "anthropic", "claude-opus-5-5") == {'FINISHED'} and calls.dialog == [True]
    # In use: another model of the same provider switches in place; the same model is a no-op.
    credential_state.apply_from_payload({"byok_active": True, "items": [{"provider": "anthropic", "model": "claude-opus-5-5"}]}, wm)
    assert run(TAB_KEY, "anthropic", "claude-sonnet-5-5") == {'FINISHED'} and calls.switch == ["claude-sonnet-5-5"]
    assert run(TAB_KEY, "anthropic", "claude-opus-5-5") == {'FINISHED'} and calls.switch == ["claude-sonnet-5-5"]
    # Paused: a row resumes on that model.
    credential_state.apply_removed(wm)
    credential_state.set_resumable({"provider": "anthropic", "model": "claude-opus-5-5"})
    assert run(TAB_KEY, "anthropic", "claude-sonnet-5-5") == {'FINISHED'} and calls.resume == ["claude-sonnet-5-5"]
    assert len(calls.dialog) == 1


def test_the_pick_waits_for_a_turn_and_for_other_mutations(pick, monkeypatch):
    from mixar.modules.byok.ui.operators import agent_pick_ops as ops
    run, calls, wm = pick
    ctx = SimpleNamespace(window_manager=wm, scene=SimpleNamespace())
    monkeypatch.setattr(ops.MIXAR_OT_agent_pick, "poll_message_set", staticmethod(lambda m: None), raising=False)
    assert ops.MIXAR_OT_agent_pick.poll(ctx)
    monkeypatch.setattr(ops, "turn_in_flight", lambda context: True)
    assert not ops.MIXAR_OT_agent_pick.poll(ctx)
    assert run(TAB_MIXIE, "anthropic", "claude-opus-5-5") == {'CANCELLED'} and calls.set == []
    monkeypatch.setattr(ops, "turn_in_flight", lambda context: False)
    monkeypatch.setattr(ops, "account_busy", lambda: True)
    assert not ops.MIXAR_OT_agent_pick.poll(ctx)
