# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every BYOK request answers, and a request in flight is never forgotten.

The dialog can be closed with Esc mid-request, so `byok_client` counts sent
saves / removals / re-saves (`mutation_in_flight()`), and every key action —
the dialog's and the island's — waits for them. That count must never stick: each request goes
through `_run_worker`, which always delivers its callback (a failure tuple
when anything goes wrong, even error classification), logout resets it, and a
request from before the reset never releases into the next account's count.
Pinned here, plus the Local custom save (counted from its ping) and the
dialog keeping a request's progress when reopened.
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

from mixar.modules.byok.core import byok_client, credential_state, preference_state, transport_seal


class _Inline(threading.Thread):
    def start(self):
        self.run()


@pytest.fixture
def client(monkeypatch):
    delivered = []
    monkeypatch.setattr(byok_client.threading, "Thread", _Inline)
    monkeypatch.setattr(byok_client, "_schedule_on_main",
                        lambda cb, *args: (delivered.append(args), cb(*args)))
    # The PUT carries the key sealed and a 200 writes this device's store:
    # neither the transport key nor the keychain is touched here.
    monkeypatch.setattr(transport_seal, "seal", lambda secret: secret)
    monkeypatch.setattr(byok_client, "_store_local_key", lambda *a: True)
    byok_client.reset_in_flight()
    yield delivered
    byok_client.reset_in_flight()


def _service(**methods):
    return lambda: SimpleNamespace(**methods)


def test_a_worker_that_dies_still_answers_and_releases(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("socket gone")

    monkeypatch.setattr(byok_client, "get_agent_service", _service(save_credentials_all=boom))
    # Even the error classification failing must not swallow the answer.
    monkeypatch.setattr(byok_client, "_translate_exception",
                        lambda e: (_ for _ in ()).throw(ValueError("classifier broke")))
    answers = []
    byok_client.save_credentials("openai", "m", "k", on_done=lambda *a: answers.append(a))
    assert answers and answers[0][0] is False
    assert not byok_client.mutation_in_flight()


def test_a_removal_answers_in_its_own_shape_when_it_fails(client, monkeypatch):
    def boom():
        raise RuntimeError("socket gone")

    monkeypatch.setattr(byok_client, "get_agent_service",
                        _service(delete_credentials_all=boom))
    monkeypatch.setattr(byok_client, "_translate_exception", lambda e: (False, None, "offline"))
    answers = []
    byok_client.delete_credentials(on_done=lambda *a: answers.append(a))
    assert answers == [(False, 0, "offline")]
    assert not byok_client.mutation_in_flight()


def test_no_timer_releases_without_touching_bpy_off_thread(client, monkeypatch):
    def no_timer(cb, *args):
        raise RuntimeError("interpreter shutting down")

    monkeypatch.setattr(byok_client, "_schedule_on_main", no_timer)
    monkeypatch.setattr(byok_client, "get_agent_service", _service(
        save_credentials_all=lambda **k: SimpleNamespace(success=True, status_code=200,
                                                         data={"data": {}})))
    answers = []
    byok_client.save_credentials("openai", "m", "k", on_done=lambda *a: answers.append(a))
    assert answers == []  # never called from the worker thread
    assert not byok_client.mutation_in_flight()


def test_a_worker_that_cannot_start_answers_on_the_calling_thread(client, monkeypatch):
    class NoThreads(threading.Thread):
        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(byok_client.threading, "Thread", NoThreads)
    answers = []
    byok_client.delete_credentials(on_done=lambda *a: answers.append(a))
    assert answers and answers[0][0] is False
    assert not byok_client.mutation_in_flight()


def test_logout_resets_and_an_older_request_never_releases_into_the_next_account(client):
    pending = []
    byok_client._schedule_on_main = lambda cb, *args: pending.append((cb, args))
    try:
        byok_client.reset_in_flight()
        old = byok_client._track(lambda *a: None)
        assert byok_client.mutation_in_flight()
        byok_client.reset_in_flight()  # logout
        assert not byok_client.mutation_in_flight()
        new = byok_client._track(lambda *a: None)
        old(True, None, None)  # the previous account's answer lands late
        assert byok_client.mutation_in_flight()  # the new account's request still counts
        new(True, None, None)
        assert not byok_client.mutation_in_flight()
    finally:
        del byok_client._schedule_on_main


def test_logout_resets_the_count():
    source = (SCRIPTS / "mixar" / "modules" / "auth" / "core" / "auth_hooks.py").read_text(
        encoding="utf-8")
    body = source[source.index("def invalidate_agent_settings"):]
    end = body.find("\ndef ", 1)
    assert "byok_client.reset_in_flight()" in (body if end < 0 else body[:end])


def test_a_local_custom_save_counts_from_its_ping(client, monkeypatch):
    from mixar.modules.byok.core import local_provider
    import mixar.modules.local_models.core.relay as relay

    monkeypatch.setattr(relay, "validate_base_url", lambda base: None)
    pings = []
    monkeypatch.setattr(local_provider, "_ping_models_endpoint",
                        lambda base: pings.append(byok_client.mutation_in_flight()))
    sent = []
    monkeypatch.setattr(byok_client, "save_credentials",
                        lambda **kw: sent.append(byok_client.mutation_in_flight()))
    wm = SimpleNamespace(byok_form_local_custom_base="http://127.0.0.1:11434",
                         byok_form_local_custom_model="llama3", byok_form_local_custom_key="")
    started, err = local_provider.save_custom_async(wm, on_done=lambda *a: None)
    assert started and err is None
    assert pings == [True]  # counted while the ping runs
    assert sent == [False]  # released just before the (self-counting) PUT
    assert not byok_client.mutation_in_flight()


def test_reopening_the_dialog_keeps_a_request_s_progress():
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
              / "byok_ops.py").read_text(encoding="utf-8")
    invoke = source[source.index("    def invoke(self, context, event):"):]
    invoke = invoke[:invoke.index("    def execute(")]
    assert ("if not byok_client.mutation_in_flight():\n"
            "            wm.byok_dialog_state = 'IDLE'") in invoke


def test_save_and_remove_wait_for_a_hosted_pick(monkeypatch):
    from mixar.modules.byok.ui.operators import byok_ops
    monkeypatch.setattr(preference_state, "mutation_pending", lambda: True)
    ctx = SimpleNamespace(window_manager=SimpleNamespace(byok_dialog_state='IDLE'))
    assert not byok_ops.MIXAR_BYOK_OT_save.poll(ctx)
    assert not byok_ops.MIXAR_BYOK_OT_confirm_remove.poll(ctx)
    monkeypatch.setattr(preference_state, "mutation_pending", lambda: False)
    monkeypatch.setattr(credential_state, "pending", lambda: "")
    byok_client.reset_in_flight()
    assert byok_ops.MIXAR_BYOK_OT_save.poll(ctx)
    assert byok_ops.MIXAR_BYOK_OT_confirm_remove.poll(ctx)


def test_a_local_save_that_cannot_start_shows_its_error_not_saving(monkeypatch):
    from mixar.modules.byok.core import local_provider
    from mixar.modules.byok.ui.operators import byok_local_ops

    wm = SimpleNamespace(byok_form_local_mode='CUSTOM', byok_dialog_state='IDLE',
                         byok_last_error='')

    def answers_at_once(wm_, on_done):
        on_done(False, None, "worker not started")
        return True, None

    def on_done(success, data, err):
        wm.byok_dialog_state, wm.byok_last_error = 'ERROR', err

    monkeypatch.setattr(local_provider, "save_custom_async", answers_at_once)
    assert byok_local_ops.execute_local(None, wm, on_done) == {'FINISHED'}
    assert wm.byok_dialog_state == 'ERROR' and wm.byok_last_error == "worker not started"


def test_a_local_save_never_lands_on_the_next_account(client, monkeypatch):
    from mixar.modules.byok.core import local_provider
    import mixar.modules.local_models.core.relay as relay

    monkeypatch.setattr(relay, "validate_base_url", lambda base: None)
    monkeypatch.setattr(local_provider, "_ping_models_endpoint",
                        lambda base: credential_state.clear(SimpleNamespace()))  # logout mid-ping
    sent, answers = [], []
    monkeypatch.setattr(byok_client, "save_credentials", lambda **kw: sent.append(kw))
    wm = SimpleNamespace(byok_form_local_custom_base="http://127.0.0.1:11434",
                         byok_form_local_custom_model="llama3", byok_form_local_custom_key="")
    local_provider.save_custom_async(wm, on_done=lambda *a: answers.append(a))
    assert sent == [] and answers and answers[0][0] is False
    assert not byok_client.mutation_in_flight()


def test_the_local_ping_hold_is_released_even_without_a_timer(client, monkeypatch):
    from mixar.modules.byok.core import local_provider
    import mixar.modules.local_models.core.relay as relay

    monkeypatch.setattr(relay, "validate_base_url", lambda base: None)
    monkeypatch.setattr(local_provider, "_ping_models_endpoint", lambda base: None)

    def no_timer(cb, *args):
        raise RuntimeError("interpreter shutting down")

    monkeypatch.setattr(byok_client, "_schedule_on_main", no_timer)
    wm = SimpleNamespace(byok_form_local_custom_base="http://127.0.0.1:11434",
                         byok_form_local_custom_model="llama3", byok_form_local_custom_key="")
    local_provider.save_custom_async(wm, on_done=lambda *a: None)
    assert not byok_client.mutation_in_flight()
