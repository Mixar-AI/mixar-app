# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The thinking level of a user's own key, picked from the island card's key tab.

Pins the state parse (`thinking_level` on the credential view; absent on an
older backend = no level rows), the key tab's rows (the same disclosure and
level rows as the Mixie tab, from the catalog record's `thinking_levels`),
the chip, which request a level pick makes (`mixar.agent_pick` ->
`byok_switch_ops.set_level` -> `PATCH /agent/byok`) and how that request's
errors are shaped.
"""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import byok_client, credential_state, key_store, model_suggestions, picker, preference_state
from mixar.modules.byok.core.picker import TAB_KEY, TAB_MIXIE
from mixar.modules.common.api.exceptions import HTTPClientError
from mixar.modules.common.api.services import agent_service

CATALOG = {'providers': [
    {'id': 'anthropic', 'label': 'Anthropic', 'short_label': 'Claude API', 'models': [
        {'id': 'claude-opus-5-5', 'label': 'Claude Opus 5.5', 'short_label': 'Opus 5.5',
         'platform_available': True, 'thinking_levels': ['low', 'high']},
        {'id': 'claude-sonnet-5-5', 'label': 'Claude Sonnet 5.5', 'short_label': 'Sonnet 5.5',
         'platform_available': True},
    ]},
    {'id': 'openai', 'label': 'OpenAI', 'short_label': 'OpenAI API', 'models': [
        {'id': 'gpt-6-sol', 'label': 'GPT 6 Sol', 'platform_available': False,
         'thinking_levels': ['minimal', 'medium_high']},
    ]},
]}


@pytest.fixture
def catalog():
    import copy
    saved = (list(model_suggestions._provider_cache), copy.deepcopy(model_suggestions._model_cache),
             copy.deepcopy(model_suggestions._platform_records), model_suggestions._populated_once)
    model_suggestions.populate_from_payload(CATALOG)
    yield model_suggestions.get_platform_models()
    model_suggestions.populate(*saved[:3])
    model_suggestions._populated_once = saved[3]


def _key(provider="anthropic", model="claude-opus-5-5", **kw):
    item = {"provider": provider, "model": model, "key_preview": "sk-…1234"}
    item.update(kw)
    return credential_state._parse({"byok_active": True, "items": [item]})


def _state(credential, **kw):
    return picker.picker_state(credential, dict(preference_state._DEFAULTS, mixar_agent_model_byok_active=True), **kw)


def _key_rows(state, catalog):
    return [(r.kind, r.label, r.current, r.thinking) for r in picker.build_rows(state, catalog) if r.tab == TAB_KEY]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def test_the_credential_view_carries_the_level_and_an_older_backend_none():
    assert _key(thinking_level="high")["byok_current_thinking"] == "high"
    assert _key(thinking_level=None)["byok_current_thinking"] == ""  # null = the model's default
    assert _key()["byok_current_thinking"] is None  # field absent: a backend before levels
    assert credential_state._parse({"byok_active": False, "items": []})["byok_current_thinking"] is None


def test_the_patch_echo_shape_is_parsed_like_the_list():
    parsed = credential_state._parse({"byok_active": True, "default": {
        "role": "default", "provider": "anthropic", "model": "claude-opus-5-5", "thinking_level": "low"}})
    assert (parsed["byok_is_active"], parsed["byok_current_provider"], parsed["byok_current_model"],
            parsed["byok_current_thinking"]) == (True, "anthropic", "claude-opus-5-5", "low")
    assert credential_state._parse({"byok_active": False, "default": None})["byok_current_provider"] == ""


def test_catalog_levels_match_provider_and_model():
    model_suggestions.populate_from_payload(CATALOG)
    try:
        assert model_suggestions.thinking_levels("anthropic", "claude-opus-5-5") == ["low", "high"]
        # A BYOK-only record counts.
        assert model_suggestions.thinking_levels("openai", "gpt-6-sol") == ["minimal", "medium_high"]
        # Matched on the key's own provider, as the backend validates a level:
        # Codex borrows the openai model LIST, never its levels (the server
        # refuses every level for codex); OpenRouter / Local have no rows.
        assert model_suggestions.thinking_levels("codex", "gpt-6-sol") == []
        assert model_suggestions.thinking_levels("openrouter", "anthropic/claude-opus-5-5") == []
        assert model_suggestions.thinking_levels("local", "claude-opus-5-5") == []
        assert model_suggestions.thinking_levels("anthropic", "claude-sonnet-5-5") == []
        assert model_suggestions.thinking_levels("kimi", "k2") == []
    finally:
        model_suggestions.clear()


# ---------------------------------------------------------------------------
# Rows and chip
# ---------------------------------------------------------------------------

def test_the_key_tab_offers_the_levels_of_the_key_in_use(catalog):
    s = _state(_key(thinking_level="high"))
    assert s["key_thinking"] == "high"
    assert picker.chip(s)["name"] == "Opus 5.5 · High"
    assert _key_rows(s, catalog) == [
        ("model", "Claude Opus 5.5", True, "high"),  # re-picking it sends nothing
        ("thinking", "Thinking: High", False, ""),
        ("level", "Low", False, "low"),
        ("level", "High", True, "high"),
        ("model", "Claude Sonnet 5.5", False, ""),
        ("footer", "Manage key…", False, ""),
    ]
    rows = [r for r in picker.build_rows(s, catalog) if r.tab == TAB_KEY and r.kind == picker.ROW_LEVEL]
    assert {(r.provider, r.model) for r in rows} == {("anthropic", "claude-opus-5-5")}


def test_the_default_level_names_no_level(catalog):
    s = _state(_key(thinking_level=None))
    assert picker.chip(s)["name"] == "Opus 5.5"
    rows = _key_rows(s, catalog)
    assert ("thinking", "Thinking", False, "") in rows
    assert [r for r in rows if r[0] == "level" and r[2]] == []


@pytest.mark.parametrize("credential, kw", [
    (_key(), {}),  # an older backend: the field is absent
    (_key(model="claude-sonnet-5-5", thinking_level=None), {}),  # the model offers no levels
    (_key(model="k2", provider="kimi", thinking_level=None), {}),  # not in the catalog
    (_key(thinking_level="high"), {"switching": "claude-sonnet-5-5"}),  # a switch saving
    (_key(provider="codex", model="gpt-6-sol", thinking_level=None), {}),  # no codex catalog rows
    (_key(provider="openrouter", model="openai/gpt-6-sol", thinking_level=None), {}),
])
def test_no_level_rows_when_there_is_nothing_to_pick(catalog, credential, kw):
    s = _state(credential, **kw)
    kinds = [r[0] for r in _key_rows(s, catalog)]
    assert "thinking" not in kinds and "level" not in kinds


def test_a_paused_key_offers_no_levels(catalog):
    s = picker.picker_state(dict(credential_state._DEFAULTS, byok_key_resumable=True,
                                 byok_resume_provider="anthropic", byok_resume_model="claude-opus-5-5",
                                 byok_current_thinking="high"), dict(preference_state._DEFAULTS))
    assert s["key_thinking"] is None
    assert "level" not in [r[0] for r in _key_rows(s, catalog)]


def test_both_tabs_build_their_levels_in_one_place():
    source = (SCRIPTS / "mixar/modules/byok/core/picker.py").read_text(encoding="utf-8")
    assert source.count("Row(tab, ROW_LEVEL,") == 1 and source.count("_thinking_rows(TAB_") == 2
    assert "TAB_MIXIE, ROW_LEVEL" not in source and "TAB_KEY, ROW_LEVEL" not in source


# ---------------------------------------------------------------------------
# The pick
# ---------------------------------------------------------------------------

@pytest.fixture
def pick(monkeypatch):
    from mixar.modules.byok.ui.operators import agent_pick_ops as ops
    calls = SimpleNamespace(level=[], switch=[], dialog=[])
    monkeypatch.setattr(ops.byok_switch_ops, "set_level", lambda wm, level: calls.level.append(level) or True)
    monkeypatch.setattr(ops.byok_switch_ops, "switch", lambda wm, model: calls.switch.append(model) or True)
    monkeypatch.setattr(ops, "_open_settings", lambda: calls.dialog.append(True) or {'FINISHED'})
    monkeypatch.setattr(ops, "turn_in_flight", lambda context: False)
    monkeypatch.setattr(ops, "account_busy", lambda: False)
    monkeypatch.setattr(key_store, "check_resumable_async", lambda on_done: None)
    monkeypatch.setattr(key_store, "check_presence_async", lambda provider, on_done: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    wm = SimpleNamespace()
    credential_state.clear(wm)

    def run(provider, model, thinking=""):
        op = ops.MIXAR_OT_agent_pick()
        op.source, op.provider, op.model, op.thinking = TAB_KEY, provider, model, thinking
        return op.execute(SimpleNamespace(window_manager=wm, scene=SimpleNamespace()))

    yield run, calls, wm
    credential_state.clear(wm)


def _apply(wm, **item):
    credential_state.apply_from_payload({"byok_active": True, "items": [
        dict({"provider": "anthropic", "model": "claude-opus-5-5"}, **item)]}, wm)


def test_a_level_row_patches_and_the_current_level_is_a_no_op(pick):
    run, calls, wm = pick
    _apply(wm, thinking_level="high")
    assert run("anthropic", "claude-opus-5-5", "low") == {'FINISHED'} and calls.level == ["low"]
    assert run("anthropic", "claude-opus-5-5", "high") == {'FINISHED'} and calls.level == ["low"]
    # The current model's row carries its level: no request either.
    assert run("anthropic", "claude-opus-5-5") == {'FINISHED'} and calls.level == ["low"]
    # Another model is still a switch (no level: the new model starts on its default).
    assert run("anthropic", "claude-sonnet-5-5") == {'FINISHED'} and calls.switch == ["claude-sonnet-5-5"]
    assert calls.dialog == []


def test_an_older_backend_never_patches(pick):
    run, calls, wm = pick
    _apply(wm)  # no thinking_level in the view
    assert run("anthropic", "claude-opus-5-5", "low") == {'FINISHED'} and calls.level == []


def test_set_level_marks_the_mutation_and_adopts_the_echo(monkeypatch):
    from mixar.modules.byok.ui.operators import byok_switch_ops as ops
    sent, toasts = [], []
    monkeypatch.setattr(ops.byok_client, "set_thinking_level", lambda level, on_done: sent.append((level, on_done)))
    monkeypatch.setattr(ops, "_toast", lambda err, title=None: toasts.append((err, title)))
    monkeypatch.setattr(ops, "_redraw", lambda: None)
    monkeypatch.setattr(ops.preference_state, "refresh", lambda: None)
    monkeypatch.setattr(credential_state, "apply_to_wm", lambda wm=None: None)
    monkeypatch.setattr(credential_state.byok_client, "fetch_state", lambda on_done: None)
    monkeypatch.setattr(key_store, "check_resumable_async", lambda on_done: None)
    monkeypatch.setattr(key_store, "check_presence_async", lambda provider, on_done: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    credential_state.clear()
    try:
        _apply(None, thinking_level="high")
        assert ops.set_level(None, "low") is True
        assert credential_state.pending() == "level" and credential_state.switching() == ""
        assert ops.set_level(None, "high") is False  # one island mutation at a time
        level, done = sent[0]
        assert level == "low" and len(sent) == 1
        done(True, {"byok_active": True, "default": {"provider": "anthropic", "model": "claude-opus-5-5",
                                                     "thinking_level": "low"}}, None)
        assert credential_state.pending() == ""
        assert credential_state.snapshot()["byok_current_thinking"] == "low"
        # A 422 shows the server's words; a quiet failure (404 / 405) toasts nothing.
        ops.set_level(None, "high")
        sent[-1][1](False, None, "Model does not offer that level")
        ops.set_level(None, "high")
        sent[-1][1](False, None, None)
        assert toasts == [("Model does not offer that level", ops.LEVEL_TITLE)]
        assert credential_state.snapshot()["byok_current_thinking"] == "low"
    finally:
        credential_state.clear()


# ---------------------------------------------------------------------------
# The PATCH request
# ---------------------------------------------------------------------------

def test_the_patch_body_is_the_level_only():
    sent = {}

    class Service(agent_service.AgentService):
        def __init__(self):
            pass

        def patch(self, path, json=None, **_):
            sent["path"], sent["json"] = path, json
            return "resp"

    assert Service().patch_byok("high") == "resp"
    assert sent == {"path": "byok", "json": {"thinking_level": "high"}}
    Service().patch_byok(None)
    assert sent["json"] == {"thinking_level": None}


class _Inline(threading.Thread):
    def start(self):
        self.run()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(byok_client.threading, "Thread", _Inline)
    monkeypatch.setattr(byok_client, "_schedule_on_main", lambda cb, *args: cb(*args))
    byok_client.reset_in_flight()
    yield monkeypatch
    byok_client.reset_in_flight()


def _answer(monkeypatch, patch):
    monkeypatch.setattr(byok_client, "get_agent_service", lambda: SimpleNamespace(patch_byok=patch))
    answers = []
    byok_client.set_thinking_level("high", on_done=lambda *a: answers.append(a))
    assert not byok_client.mutation_in_flight()
    return answers[0]


def _raise(status, message="m", data=None):
    def patch(level):
        raise HTTPClientError(message, status_code=status, response_data=data)
    return patch


def test_the_patch_answers_in_the_tri_tuple(client):
    ok = SimpleNamespace(success=True, status_code=200, data={"status": "success", "message": "OK", "data": {
        "byok_active": True, "default": {"provider": "anthropic", "thinking_level": "high"}}})
    assert _answer(client, lambda level: ok) == (True, ok.data["data"], None)
    assert _answer(client, _raise(422, "Model does not offer that level")) == (
        False, None, "Model does not offer that level")
    # A schema 422 (FastAPI's list detail) is not user-safe: the category default.
    assert _answer(client, _raise(422, [{"loc": ["body"]}])) == (False, None, byok_client._VALIDATION_ERROR_MSG)
    assert _answer(client, _raise(404)) == (False, None, None)
    assert _answer(client, _raise(405)) == (False, None, None)
    assert _answer(client, _raise(500)) == (False, None, byok_client._GENERIC_SERVER_ERROR_MSG)


def test_the_servers_422_and_404_bodies_reach_the_tuple(client):
    """The backend's refusals carry `message` at the TOP level of the body (no
    `detail`): mapped through the real HTTP client, the 422 reads verbatim."""
    from mixar.modules.common.api.client import HTTPClient

    def body(status, payload):
        response = SimpleNamespace(status_code=status, json=lambda: payload, text="", headers={})
        return HTTPClient._map_exception(SimpleNamespace(), response)

    refused = ("'anthropic/claude-opus-5-5' does not take thinking level 'x'; "
               "choose one of: low, medium, high, max")

    def raise_(exc):
        def patch(level):
            raise exc
        return patch

    assert _answer(client, raise_(body(422, {"status": "failure", "message": refused}))) == (False, None, refused)
    assert _answer(client, raise_(body(404, {"status": "failure",
                                             "message": "No BYOK credential is configured."}))) == (False, None, None)


def test_a_level_sent_after_logout_is_never_patched(client):
    called = []
    client.setattr(byok_client, "get_agent_service", lambda: SimpleNamespace(patch_byok=called.append))
    client.setattr(byok_client, "_account_epoch", iter([1, 2]).__next__)
    answers = []
    byok_client.set_thinking_level("high", on_done=lambda *a: answers.append(a))
    assert called == [] and answers == [(False, None, byok_client._SIGNED_OUT_MSG)]


# ---------------------------------------------------------------------------
# The level a turn actually runs at: saved, else the catalog default
# ---------------------------------------------------------------------------

DEFAULTED = {'providers': [
    {'id': 'anthropic', 'label': 'Anthropic', 'short_label': 'Claude API', 'models': [
        {'id': 'claude-opus-5-5', 'label': 'Claude Opus 5.5', 'short_label': 'Opus 5.5',
         'platform_available': True, 'thinking_levels': ['low', 'medium', 'high'],
         'default_thinking_level': 'medium'},
        # A default the user is not offered is never shown.
        {'id': 'claude-sonnet-5-5', 'label': 'Claude Sonnet 5.5', 'short_label': 'Sonnet 5.5',
         'platform_available': True, 'thinking_levels': ['low'], 'default_thinking_level': 'max'},
    ]},
]}


@pytest.fixture
def defaulted(catalog):
    model_suggestions.populate_from_payload(DEFAULTED)
    return model_suggestions.get_platform_models()


def _hosted(thinking=""):
    return dict(preference_state._DEFAULTS, mixar_agent_model_provider="anthropic",
                mixar_agent_model_id="claude-opus-5-5", mixar_agent_model_label="Claude Opus 5.5",
                mixar_agent_model_thinking=thinking)


def _levels(rows, tab):
    return [(r.kind, r.label, r.current) for r in rows
            if r.tab == tab and r.kind in (picker.ROW_THINKING, picker.ROW_LEVEL)]


def test_the_catalog_default_is_kept_only_when_offered(defaulted):
    assert model_suggestions.default_thinking_level("anthropic", "claude-opus-5-5") == "medium"
    assert model_suggestions.default_thinking_level("anthropic", "claude-sonnet-5-5") == ""
    assert model_suggestions.default_thinking_level("codex", "claude-opus-5-5") == ""
    model_suggestions.populate_from_payload(CATALOG)  # an older backend: no field
    assert model_suggestions.default_thinking_level("anthropic", "claude-opus-5-5") == ""


def test_effective_thinking_is_the_saved_level_else_the_default(defaulted):
    from mixar.modules.byok.core import model_menu
    assert model_menu.effective_thinking("anthropic", "claude-opus-5-5", "high") == "high"
    assert model_menu.effective_thinking("anthropic", "claude-opus-5-5", "") == "medium"
    assert model_menu.effective_thinking("anthropic", "", "") == ""


def test_the_mixie_tab_names_and_ticks_the_default_when_nothing_is_saved(defaulted):
    s = picker.picker_state(dict(credential_state._DEFAULTS), _hosted())
    assert picker.chip(s)["name"] == "Claude Opus 5.5 · Medium"
    rows = picker.build_rows(s, defaulted)
    assert _levels(rows, TAB_MIXIE) == [("thinking", "Thinking: Medium", False), ("level", "Low", False),
                                        ("level", "Medium", True), ("level", "High", False)]
    current = next(r for r in rows if r.tab == TAB_MIXIE and r.kind == picker.ROW_MODEL and r.current)
    assert current.thinking == "medium"  # re-picking the row sends nothing
    # A saved level wins over the default.
    s = picker.picker_state(dict(credential_state._DEFAULTS), _hosted("high"))
    assert picker.chip(s)["name"] == "Claude Opus 5.5 · High"
    assert ("level", "High", True) in _levels(picker.build_rows(s, defaulted), TAB_MIXIE)


def test_the_key_tab_names_and_ticks_the_default_when_nothing_is_saved(defaulted):
    s = _state(_key(thinking_level=None))
    assert picker.chip(s)["name"] == "Opus 5.5 · Medium"
    assert _levels(picker.build_rows(s, defaulted), TAB_KEY) == [
        ("thinking", "Thinking: Medium", False), ("level", "Low", False),
        ("level", "Medium", True), ("level", "High", False)]
    # A backend that does not report the key's level: still no level rows, no level named.
    s = _state(_key())
    assert picker.chip(s)["name"] == "Opus 5.5"
    assert _levels(picker.build_rows(s, defaulted), TAB_KEY) == []


def test_without_a_catalog_default_nothing_is_spelled_out(catalog):
    s = picker.picker_state(dict(credential_state._DEFAULTS), _hosted())
    assert picker.chip(s)["name"] == "Claude Opus 5.5"
    assert ("thinking", "Thinking", False) in _levels(picker.build_rows(s, catalog), TAB_MIXIE)
    assert not [r for r in _levels(picker.build_rows(s, catalog), TAB_MIXIE) if r[2]]
    assert picker.chip(_state(_key(thinking_level=None)))["name"] == "Opus 5.5"


def test_the_legacy_label_mirror_names_the_default_too(defaulted, monkeypatch):
    monkeypatch.setattr(preference_state, "snapshot", lambda: _hosted())
    assert preference_state.chip_text() == "Claude Opus 5.5 · Medium"


def test_picking_the_default_level_with_nothing_saved_sends_nothing(pick, defaulted, monkeypatch):
    from mixar.modules.byok.ui.operators import agent_pick_ops as ops
    run, calls, wm = pick
    hosted = []
    monkeypatch.setattr(ops.agent_model_ops, "set_hosted",
                        lambda wm, p, m, t="", label="": hosted.append((p, m, t)) or True)
    monkeypatch.setattr(preference_state, "snapshot", lambda: _hosted())
    # Mixie: the default level, and the current row (it carries the default), are no-ops.
    op = ops.MIXAR_OT_agent_pick()
    ctx = SimpleNamespace(window_manager=wm, scene=SimpleNamespace())
    for thinking in ("medium", "high"):
        op.source, op.provider, op.model, op.thinking = TAB_MIXIE, "anthropic", "claude-opus-5-5", thinking
        assert op.execute(ctx) == {'FINISHED'}
    assert hosted == [("anthropic", "claude-opus-5-5", "high")]
    # Key tab: the same rule.
    _apply(wm, thinking_level=None)
    assert run("anthropic", "claude-opus-5-5", "medium") == {'FINISHED'} and calls.level == []
    assert run("anthropic", "claude-opus-5-5", "low") == {'FINISHED'} and calls.level == ["low"]
