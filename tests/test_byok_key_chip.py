# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island key chip: switch your key's model without the settings dialog.

While the user's own key is in use, the composer shows a chip after the
Mixie | Custom AI toggle naming the provider and model ("Claude API" /
"Opus 5.5"); the model pill is a dropdown whose rows re-send the SAME key —
the one this computer holds (`core/key_store`) — on another model
(`byok_client.resave_stored_key` → `PUT /agent/byok`, sealed like a save).
The server keeps no key, so nothing is "reused" server-side.

Pinned here: the WindowManager mirrors the C++ chip reads, the in-flight
switch state, the re-save worker (what it sends and what it refuses), the
callback's success/failure handling and the menu rows. The native chip itself
is proven by tests/qa/agent_key_toggle_e2e.py.
"""

import ast
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

from mixar.modules.byok.core import (
    byok_client, catalog_labels, codex_auth, credential_state, key_store, model_suggestions, picker,
    preference_state, transport_seal,
)
from mixar.modules.byok.constants import BYOK_TURN_ACCOUNT_FIELD, BYOK_TURN_KEY_FIELD

BYOK = SCRIPTS / "mixar" / "modules" / "byok"
SWITCH_OPS = BYOK / "ui" / "operators" / "byok_switch_ops.py"
PROPS = BYOK / "ui" / "properties" / "agent_model_props.py"
PROVIDER_CC = (ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
               / "agent_ui_provider.cc")
CARD_DATA_CC = PROVIDER_CC.parent / "agent_ui_model_card_data.cc"

# As the backend sends it: short labels are the catalog's, never the client's.
CATALOG = {'providers': [
    {'id': 'anthropic', 'label': 'Anthropic', 'short_label': 'Claude API', 'models': [
        {'id': 'claude-opus-5-5', 'label': 'Claude Opus 5.5', 'short_label': 'Opus 5.5',
         'platform_available': True},
        {'id': 'claude-sonnet-5-5', 'label': 'Claude Sonnet 5.5', 'short_label': 'Sonnet 5.5',
         'platform_available': True},
    ]},
    # A provider with no catalog models (the key's own model still gets a row).
    {'id': 'kimi', 'label': 'Moonshot Kimi', 'short_label': 'Kimi API', 'models': []},
]}


def _payload(provider='anthropic', model='claude-opus-5-5', active=True):
    return {'byok_active': active, 'items': [
        {'provider': provider, 'model': model, 'key_preview': 'sk-ant-…1234'}] if active else []}


@pytest.fixture
def state(monkeypatch):
    """A clean credential state over a known catalog; the key store is never
    touched; restored afterwards."""
    import copy
    saved_cache = (list(model_suggestions._provider_cache),
                   copy.deepcopy(model_suggestions._model_cache),
                   copy.deepcopy(model_suggestions._platform_records))
    saved_loaded = model_suggestions._populated_once
    monkeypatch.setattr(key_store, "check_resumable_async", lambda on_done: None)
    monkeypatch.setattr(key_store, "check_presence_async", lambda provider, on_done: None)
    monkeypatch.setattr(credential_state, "_redraw", lambda: None)
    model_suggestions.populate_from_payload(CATALOG)
    credential_state.clear(SimpleNamespace())
    yield credential_state
    credential_state.clear(SimpleNamespace())
    model_suggestions.populate(*saved_cache)
    model_suggestions._populated_once = saved_loaded


def _chip():
    """What the island chip draws: (source, badge, name, state)."""
    st = picker.picker_state(credential_state.snapshot(), preference_state.snapshot(),
                             pending=credential_state.pending(),
                             switching=credential_state.switching())
    c = picker.chip(st)
    return c["source"], c["label"], c["name"], c["state"]


def _key_models():
    """The key tab's model rows: [(model, current)]."""
    st = picker.picker_state(credential_state.snapshot(), preference_state.snapshot(),
                             pending=credential_state.pending(),
                             switching=credential_state.switching())
    return [(r.model, r.current) for r in picker.build_rows(st, [])
            if r.tab == picker.TAB_KEY and r.kind == picker.ROW_MODEL]


# ---------------------------------------------------------------------------
# What the island chip and the popup's key tab show
# ---------------------------------------------------------------------------

def test_an_active_cloud_key_names_provider_and_model_and_lists_its_models(state):
    state.apply_from_payload(_payload(), SimpleNamespace())
    assert _chip() == ('KEY', 'Claude API', 'Opus 5.5', 'OK')
    assert _key_models() == [('claude-opus-5-5', True), ('claude-sonnet-5-5', False)]


def test_openrouter_offers_only_its_slug(state):
    state.apply_from_payload(_payload('openrouter', 'some/model'), SimpleNamespace())
    assert _chip() == ('KEY', 'OpenRouter', 'some/model', 'OK')
    assert _key_models() == [('some/model', True)]


def test_a_local_model_is_its_own_source(state):
    state.apply_from_payload(_payload('local', 'some/model'), SimpleNamespace())
    assert _chip() == ('LOCAL', 'Local', 'some/model', 'OK')
    assert _key_models() == []  # nothing on the key tab: no key is in use


def test_no_key_means_mixie_answers(state):
    state.apply_from_payload(_payload(active=False), SimpleNamespace())
    assert _chip()[0] == 'MIXIE'
    assert _key_models() == []


def test_a_model_the_catalog_does_not_list_keeps_its_row(state):
    state.apply_from_payload(_payload('kimi', 'kimi-k2'), SimpleNamespace())
    assert _chip()[:2] == ('KEY', 'Kimi API')
    assert _key_models() == [('kimi-k2', True)]


def test_the_picker_mirrors_are_registered_and_read_by_the_cpp():
    source = PROPS.read_text(encoding='utf-8')
    names = ('mixar_agent_source', 'mixar_agent_source_label', 'mixar_agent_chip_name',
             'mixar_agent_source_state', 'mixar_agent_tabs', 'mixar_agent_rows')
    for name in names:
        assert f"WM.{name} = " in source
        assert f"'{name}'," in source  # unregistered with the rest
    assert 'mixar_agent_key_' not in source  # the old key chip's mirrors are gone
    cpp = PROVIDER_CC.read_text(encoding='utf-8') + CARD_DATA_CC.read_text(encoding='utf-8')
    for name in names:
        assert f'"{name}"' in cpp, name


# ---------------------------------------------------------------------------
# A switch in flight
# ---------------------------------------------------------------------------

def test_a_switch_in_flight_names_the_target_dimmed_until_it_lands(state):
    wm = SimpleNamespace()
    state.apply_from_payload(_payload(), wm)
    assert state.begin_switch('claude-sonnet-5-5', wm)
    assert state.switching() == 'claude-sonnet-5-5' and state.pending() == 'switch'
    assert _chip() == ('KEY', 'Claude API', 'Sonnet 5.5', 'BUSY')
    assert _key_models() == [('claude-opus-5-5', False), ('claude-sonnet-5-5', True)]
    # One island mutation at a time.
    assert not state.begin_switch('claude-opus-5-5', wm)
    assert not state.begin_toggle(False, wm)
    state.end_pending(wm)
    assert state.switching() == ''
    assert _chip() == ('KEY', 'Claude API', 'Opus 5.5', 'OK')


def test_logout_drops_a_pending_switch(state):
    wm = SimpleNamespace()
    state.apply_from_payload(_payload(), wm)
    state.begin_switch('claude-sonnet-5-5', wm)
    state.clear(wm)
    assert state.switching() == ''
    assert _chip()[0] == 'MIXIE'
    assert _key_models() == []


# ---------------------------------------------------------------------------
# The re-save worker: the key this computer holds goes out, sealed; nothing
# is typed; a record that cannot be re-sent is refused before anything is sent
# ---------------------------------------------------------------------------

class _Sync(threading.Thread):
    """Run the worker inline so the callback lands before the assertion."""

    def start(self):
        self.run()


def _run_resave(monkeypatch, record, model='claude-sonnet-5-5', response=None, raises=None,
                live=None, logout_in_worker=False):
    calls, results, updates = [], [], []

    def save(**kwargs):
        calls.append(kwargs)
        if raises:
            raise raises
        return response or SimpleNamespace(success=True, status_code=200,
                                           data={'data': _payload(model=model or record.get('model'))})

    monkeypatch.setattr(byok_client, 'get_agent_service',
                        lambda: SimpleNamespace(save_credentials_all=save))
    monkeypatch.setattr(byok_client.threading, 'Thread', _Sync)
    monkeypatch.setattr(byok_client, '_schedule_on_main', lambda cb, *args: cb(*args))
    monkeypatch.setattr(transport_seal, 'seal', lambda secret: 'sealed:' + secret)
    def load(user_id=None):
        if logout_in_worker:
            credential_state.clear(SimpleNamespace())  # logout while the worker runs
        return record

    monkeypatch.setattr(key_store, 'load', load)
    monkeypatch.setattr(key_store, 'current_user_id', lambda: 'user-at-submit')
    monkeypatch.setattr(key_store, 'update',
                        lambda changes, user_id=None: updates.append((changes, user_id)) or True)
    monkeypatch.setattr(key_store, 'materialize',
                        lambda rec: (live, None) if live is not None else (rec, None))
    monkeypatch.setattr(codex_auth, 'needs_refresh', lambda token, now=None: False)
    byok_client.reset_in_flight()
    byok_client.resave_stored_key(model, on_done=lambda *args: results.append(args))
    return calls, results, updates


def test_a_cloud_record_is_resent_sealed_on_the_new_model(monkeypatch):
    record = key_store.make_record('anthropic', 'sk-ant-x', model='claude-opus-5-5')
    calls, results, updates = _run_resave(monkeypatch, record)
    assert calls == [{'provider': 'anthropic', 'model': 'claude-sonnet-5-5',
                      'api_key': 'sealed:sk-ant-x', 'base_url': None, 'supports_vision': None,
                      'account_id': None}]
    assert results == [(True, _payload(model='claude-sonnet-5-5'), None)]
    # A later resume re-sends this model; written for the account the record
    # was loaded for, never the token of the moment (a logout + sign-in
    # inside the round trip).
    assert updates == [({'model': 'claude-sonnet-5-5'}, 'user-at-submit')]
    assert not byok_client.mutation_in_flight()


def test_a_resume_resends_the_record_s_own_model(monkeypatch):
    record = key_store.make_record('anthropic', 'sk-ant-x', model='claude-opus-5-5')
    calls, results, _ = _run_resave(monkeypatch, record, model=None)
    assert calls[0]['model'] == 'claude-opus-5-5' and results[0][0] is True


def test_a_codex_record_sends_the_live_token_and_account(monkeypatch):
    record = key_store.make_record('codex', None, auth_path='', model='gpt-6-astra')
    live = dict(record, key='at-live', refresh_token='rt', account_id='acct', expired=False,
                can_persist=True)
    calls, results, _ = _run_resave(monkeypatch, record, model='gpt-6-sol', live=live)
    assert calls[0]['api_key'] == 'sealed:at-live' and calls[0]['account_id'] == 'acct'
    assert calls[0]['model'] == 'gpt-6-sol' and results[0][0] is True


@pytest.mark.parametrize('record', [
    None,
    key_store.make_record('local', 'bearer', model='llama'),
    key_store.make_record('anthropic', 'sk-ant-x'),          # an earlier build: no model
    key_store.make_record('anthropic', None, model='m'),     # no key material
])
def test_a_record_that_cannot_be_resent_is_refused_before_anything_goes_out(monkeypatch, record):
    calls, results, updates = _run_resave(monkeypatch, record, model=None)
    assert calls == [] and updates == []
    assert results[0][0] is False and results[0][2]
    assert not byok_client.mutation_in_flight()


def test_a_revoked_codex_sign_in_is_refused_with_its_message(monkeypatch):
    record = key_store.make_record('codex', None, auth_path='', model='gpt-6-astra')
    live = dict(record, key='at', refresh_token='rt', account_id='a', expired=True, can_persist=True)
    calls, results, _ = _run_resave(monkeypatch, record, live=live)
    assert calls == [] and results == [(False, None, codex_auth.MSG_SIGN_IN_EXPIRED)]


def test_a_resave_that_outlives_a_logout_sends_nothing(monkeypatch):
    """A Codex refresh can take seconds; logging out and in as another
    account meanwhile must not register the first account's key on the
    second account's row with the new token."""
    record = key_store.make_record('anthropic', 'sk-ant-x', model='claude-opus-5-5')
    calls, results, updates = _run_resave(monkeypatch, record, live=None,
                                          logout_in_worker=True)
    assert calls == [] and updates == []
    assert results[0][0] is False and results[0][2]
    assert not byok_client.mutation_in_flight()


def test_a_provider_rejection_keeps_the_server_message(monkeypatch):
    class Rejected(Exception):
        status_code = 400
        message = 'Model not available: not on this key'

    record = key_store.make_record('anthropic', 'sk-ant-x', model='claude-opus-5-5')
    _, results, updates = _run_resave(monkeypatch, record, raises=Rejected())
    assert results == [(False, None, 'Model not available: not on this key')]
    assert updates == []  # the record keeps the model the server still runs


def test_the_record_remembers_the_model_a_save_was_made_on():
    assert key_store.make_record('openai', 'sk', model=' gpt-5 ')['model'] == 'gpt-5'
    assert key_store.make_record('codex', None, auth_path='/p', model='m')['model'] == 'm'
    assert key_store.make_record('openai', 'sk')['model'] == ''
    source = (BYOK / "core" / "byok_client.py").read_text(encoding='utf-8')
    assert "key_store.make_record(provider, api_key, auth_path=codex_auth_path, model=model)" in source


def test_resumable_summary_is_the_pure_rule(monkeypatch):
    assert key_store.resumable_summary(None) is None
    assert key_store.resumable_summary(key_store.make_record('anthropic', 'sk', model='m')) == {
        'provider': 'anthropic', 'model': 'm'}
    assert key_store.resumable_summary(key_store.make_record('anthropic', 'sk')) is None
    assert key_store.resumable_summary(key_store.make_record('anthropic', None, model='m')) is None
    assert key_store.resumable_summary(key_store.make_record('local', 'b', model='m')) is None
    codex = key_store.make_record('codex', None, auth_path='', model='m')
    monkeypatch.setattr(key_store, 'materialize', lambda rec: (dict(rec, expired=False), None))
    assert key_store.resumable_summary(codex) == {'provider': 'codex', 'model': 'm'}
    monkeypatch.setattr(key_store, 'materialize', lambda rec: (dict(rec, expired=True), None))
    assert key_store.resumable_summary(codex) is None
    monkeypatch.setattr(key_store, 'materialize', lambda rec: (None, 'no sign-in'))
    assert key_store.resumable_summary(codex) is None


# ---------------------------------------------------------------------------
# The callback and the operator
# ---------------------------------------------------------------------------

def test_success_adopts_the_echo_and_failure_keeps_the_model_and_toasts(state, monkeypatch):
    from mixar.modules.byok.ui.operators import byok_switch_ops as ops

    toasts, refreshed = [], []
    monkeypatch.setattr(ops, '_toast', toasts.append)
    monkeypatch.setattr(ops, '_redraw', lambda: None)
    monkeypatch.setattr(ops.preference_state, 'refresh', lambda: refreshed.append(True))
    monkeypatch.setattr(credential_state, 'apply_to_wm', lambda wm=None: None)
    monkeypatch.setattr(credential_state.byok_client, 'fetch_state', lambda on_done: None)
    state.apply_from_payload(_payload())

    epoch = state.current_epoch()
    state.begin_switch('claude-sonnet-5-5')
    ops._on_switch_done(True, _payload(model='claude-sonnet-5-5'), None, epoch)
    assert state.switching() == ''
    assert state.snapshot()['byok_current_model'] == 'claude-sonnet-5-5'
    assert refreshed == [True] and toasts == []

    state.begin_switch('claude-opus-5-5')
    ops._on_switch_done(False, None, 'Model not available: nope', epoch)
    assert state.switching() == ''
    assert state.snapshot()['byok_current_model'] == 'claude-sonnet-5-5'
    assert toasts == ['Model not available: nope']


def test_a_switch_that_lands_after_logout_is_dropped(state, monkeypatch):
    from mixar.modules.byok.ui.operators import byok_switch_ops as ops

    monkeypatch.setattr(ops, '_redraw', lambda: None)
    monkeypatch.setattr(ops, '_toast', lambda err: None)
    monkeypatch.setattr(credential_state, 'apply_to_wm', lambda wm=None: None)
    state.apply_from_payload(_payload())
    epoch = state.current_epoch()
    state.clear()
    ops._on_switch_done(True, _payload(model='claude-sonnet-5-5'), None, epoch)
    assert state.snapshot()['byok_is_active'] is False


def test_the_switch_is_the_island_cards_and_never_opens_the_dialog():
    """`mixar_byok.switch_model` had no caller once the card ran every pick
    through `mixar.agent_pick`; `switch()` is what that pick runs."""
    tree = ast.parse(SWITCH_OPS.read_text(encoding='utf-8'))
    source = SWITCH_OPS.read_text(encoding='utf-8')
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert 'mixar_byok.switch_model' not in source
    assert 'byok_client.resave_stored_key(model, on_done=_done)' in source
    assert 'credential_state.begin_switch(' in source
    assert 'open_dialog' not in source
    assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                if isinstance(t, ast.Name)}
    assert 'classes' in assigned


def test_chip_labels_are_brand_names_and_only_local_is_translated(state):
    source = (BYOK / "core" / "catalog_labels.py").read_text(encoding='utf-8')
    assert 'LOCAL_CHIP_LABEL = n_("Local")' in source
    assert catalog_labels.chip_provider_label('anthropic') == 'Claude API'
    # Only the providers the desktop defines itself are named in the client.
    assert set(catalog_labels._CLIENT_PROVIDER_CHIP_LABELS) == {'openrouter', 'codex'}
    assert catalog_labels.chip_provider_label('codex') == 'Codex'


def test_short_labels_are_the_backends_and_an_older_backend_gets_full_names(state):
    assert catalog_labels.chip_model_label('anthropic', 'claude-opus-5-5') == 'Opus 5.5'
    # Codex shows the openai group: its short labels too.
    model_suggestions.populate_from_payload({'providers': [
        {'id': 'openai', 'label': 'OpenAI', 'short_label': 'OpenAI API', 'models': [
            {'id': 'gpt-6-sol', 'label': 'GPT 6 Sol', 'short_label': 'GPT 6 Sol'}]}]})
    assert catalog_labels.chip_model_label('codex', 'gpt-6-sol') == 'GPT 6 Sol'
    # A backend from before short_label: full names, never a client-side cut.
    model_suggestions.populate_from_payload({'providers': [
        {'id': 'anthropic', 'label': 'Anthropic', 'models': [
            {'id': 'claude-opus-5-5', 'label': 'Claude Opus 5.5'}]}]})
    assert catalog_labels.chip_provider_label('anthropic') == 'Anthropic'
    assert catalog_labels.chip_model_label('anthropic', 'claude-opus-5-5') == 'Claude Opus 5.5'
    model_suggestions.clear()
    assert model_suggestions.provider_short_label('anthropic') == ''


def test_the_island_builds_the_provider_sources():
    cmake = (PROVIDER_CC.parent / "CMakeLists.txt").read_text(encoding='utf-8')
    for name in ("agent_ui_provider.cc", "agent_ui_provider_chevron.cc", "agent_ui_provider.hh",
                 "agent_ui_model_card.cc", "agent_ui_model_card_data.cc",
                 "agent_ui_model_card_draw.cc", "agent_ui_model_card_layout.cc",
                 "agent_ui_model_card_qa.cc", "agent_ui_model_card.hh",
                 "agent_ui_model_card_intern.hh"):
        assert f"  {name}\n" in cmake
