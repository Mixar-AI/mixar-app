# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Codex model chips follow the signed-in ChatGPT account's own listing.

mixar-backend#1809: the top reason AI Provider saves failed was a Codex
``model_not_found`` -- the user picked a model their ChatGPT plan cannot run.
`core/codex_models` asks the account (the listing the Codex CLI fetches for its
own picker) and the dialog keeps to it. These pin the request, the parse, the
fail-open cases and the main-thread apply.
"""

import base64
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import requests

from mixar.modules.byok.constants import CODEX_AUTH_CLAIM, CODEX_MODELS_URL
from mixar.modules.byok.core import codex_models, model_suggestions

CATALOG = [("gpt-6.1-terra", "GPT 6.1 Terra", "GPT 6.1 Terra"),
           ("gpt-6-astra", "GPT 6 Astra", "GPT 6 Astra"),
           ("gpt-6-luna", "GPT 6 Luna", "GPT 6 Luna")]


def _jwt(claims):
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


def _auth_file(tmp_path, exp_in_s=3600):
    token = _jwt({CODEX_AUTH_CLAIM: {"chatgpt_account_id": "acct-7"},
                  "exp": int(time.time()) + exp_in_s})
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"tokens": {"access_token": token, "refresh_token": "rt"}}))
    return str(path), token


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def catalog():
    model_suggestions.populate(providers=[("openai", "OpenAI", "OpenAI")],
                               models={"openai": list(CATALOG)})
    yield
    model_suggestions.clear()


def test_parse_models_reads_slugs_and_treats_odd_answers_as_unknown():
    listing = {"models": [{"slug": "gpt-6-luna", "visibility": "list"},
                          {"slug": "gpt-reserve", "visibility": "hide"},
                          {"display_name": "no slug"}, "junk"]}
    assert codex_models.parse_models(listing) == {"gpt-6-luna", "gpt-reserve"}
    for odd in (None, [], {}, {"models": None}, {"models": []}, {"models": [{}]}):
        assert codex_models.parse_models(odd) is None


def test_fetch_asks_the_account_with_its_sign_in_and_never_logs_the_token(
        monkeypatch, tmp_path, caplog):
    path, token = _auth_file(tmp_path)
    calls = []

    def _get(url, params=None, headers=None, timeout=None):
        calls.append(dict(url=url, params=params, headers=headers, timeout=timeout))
        return _Response(200, {"models": [{"slug": "gpt-6-luna"}]})

    monkeypatch.setattr(requests, "get", _get)
    with caplog.at_level(logging.DEBUG):
        assert codex_models.fetch(path) == {"gpt-6-luna"}
    assert calls[0]["url"] == CODEX_MODELS_URL
    # The listing hides models newer than the reported client (0.20.0 got an
    # empty list; 0.166.0 was the newest gate seen): report one past them all.
    version = tuple(int(p) for p in calls[0]["params"]["client_version"].split("."))
    assert version >= (1, 0, 0)
    assert calls[0]["headers"]["Authorization"] == f"Bearer {token}"
    assert calls[0]["headers"]["chatgpt-account-id"] == "acct-7"
    assert calls[0]["timeout"]
    assert token not in caplog.text


@pytest.mark.parametrize("answer", [
    _Response(401, {"detail": "expired"}),
    _Response(500, {}),
    _Response(200, ValueError("not json")),
    _Response(200, {"unexpected": True}),
])
def test_fetch_fails_open_on_any_unusable_answer(monkeypatch, tmp_path, answer):
    path, _token = _auth_file(tmp_path)
    monkeypatch.setattr(requests, "get", lambda *a, **k: answer)
    assert codex_models.fetch(path) is None


def test_fetch_fails_open_offline_without_a_sign_in_or_with_an_expired_token(
        monkeypatch, tmp_path):
    def _offline(*_a, **_k):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", _offline)
    path, _token = _auth_file(tmp_path)
    assert codex_models.fetch(path) is None

    def _never(*_a, **_k):
        raise AssertionError("no request for a sign-in that cannot answer")

    monkeypatch.setattr(requests, "get", _never)
    assert codex_models.fetch(str(tmp_path / "missing.json")) is None
    expired, _token = _auth_file(tmp_path, exp_in_s=-60)
    assert codex_models.fetch(expired) is None


def test_apply_narrows_the_chips_and_never_rewrites_the_form(monkeypatch, catalog):
    monkeypatch.setattr(codex_models, "_generation", 5)
    codex_models.apply(5, frozenset({"gpt-6-luna"}))
    assert [item[0] for item in model_suggestions.get_model_items("codex")] == ["gpt-6-luna"]
    assert model_suggestions.codex_models_hidden() is True
    # apply() takes no form at all: a pick is changed only by the user.
    assert codex_models.apply.__code__.co_argcount == 2


def test_apply_drops_a_superseded_answer(monkeypatch, catalog):
    monkeypatch.setattr(codex_models, "_generation", 6)
    codex_models.apply(5, frozenset({"gpt-6-luna"}))
    assert model_suggestions.get_model_items("codex") == CATALOG


def test_logout_drops_the_list_and_any_answer_still_in_flight(monkeypatch, catalog):
    from mixar.modules.byok.core import models_cache, models_storage

    monkeypatch.setattr(models_storage, "delete", lambda: None)
    monkeypatch.setattr(codex_models, "_generation", 7)
    monkeypatch.setattr(codex_models, "_inflight", ("auth.json", 0.0))
    codex_models.apply(7, frozenset({"gpt-6-luna"}))
    monkeypatch.setattr(codex_models, "_inflight", ("auth.json", 0.0))   # a second fetch
    models_cache.clear()                                                  # logout
    assert codex_models._inflight is None
    model_suggestions.populate(providers=[("openai", "OpenAI", "OpenAI")],
                               models={"openai": list(CATALOG)})
    codex_models.apply(7, frozenset({"gpt-6-luna"}))                      # it lands late
    assert model_suggestions.get_model_items("codex") == CATALOG


def test_a_saved_model_the_list_hides_keeps_its_catalog_name(catalog):
    from mixar.modules.byok.core import catalog_labels

    model_suggestions.set_codex_account_models({"gpt-6-luna"})
    assert catalog_labels.lookup_model_label("codex", "gpt-6-astra") == "GPT 6 Astra"
    assert catalog_labels.lookup_model_label("codex", "gpt-unknown") == "gpt-unknown"


def test_refresh_runs_one_fetch_per_sign_in_file(monkeypatch, tmp_path):
    started = []

    class _Thread:
        def __init__(self, target=None, **_kwargs):
            started.append(target)

        def start(self):
            pass

    monkeypatch.setattr(codex_models.threading, "Thread", _Thread)
    monkeypatch.setattr(codex_models, "_inflight", None)
    a, b = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    codex_models.refresh_async(a)
    codex_models.refresh_async(a)        # dialog open + pick at once: one request
    assert len(started) == 1
    codex_models.refresh_async(b)        # another file: its own request
    assert len(started) == 2

    # Only a Codex form asks.
    codex_models.refresh_for_form(SimpleNamespace(byok_form_provider="openai",
                                                  byok_form_codex_path=a))
    assert len(started) == 2
