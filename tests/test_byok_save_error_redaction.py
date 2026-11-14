# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""AUTH-12: a save error the server built from the submitted key never
shows, toasts or logs that key.

The backend's validation messages are fixed strings today, but the client
shows a 4xx message verbatim; the PUT's key is the one plaintext copy the
client holds, so it is masked out of the message before anything reads it.
"""

import logging
from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import byok_client, transport_seal
from mixar.modules.common.api.exceptions import HTTPClientError

KEY = "sk-QA-ONLY-canary-9ce41f57b803446596bddc503a8a98fe"


def _put(monkeypatch, raise_exc=None, envelope=None, status=200, key=KEY):
    monkeypatch.setattr(transport_seal, "seal", lambda secret: "mxs1.kid.sealed")

    def save_credentials_all(**_kw):
        if raise_exc is not None:
            raise raise_exc
        return SimpleNamespace(success=status < 400, status_code=status, data=envelope)

    monkeypatch.setattr(byok_client, "get_agent_service",
                        lambda: SimpleNamespace(save_credentials_all=save_credentials_all))
    return byok_client._put_sealed("openai", "gpt-5", key, None, None, None)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 502])
def test_an_http_error_echoing_the_key_is_masked_in_the_message_and_log(monkeypatch, caplog, status):
    exc = HTTPClientError("Provider rejected credential " + KEY, status_code=status)
    logger = logging.getLogger(byok_client.logger.name)
    monkeypatch.setattr(logger, "propagate", True)
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        success, data, err = _put(monkeypatch, raise_exc=exc)
    assert success is False and data is None
    assert err == "Provider rejected credential ••••"
    assert KEY not in caplog.text and "Provider rejected credential ••••" in caplog.text


def test_a_failure_envelope_echoing_the_key_is_masked(monkeypatch):
    success, _, err = _put(monkeypatch, envelope={"status": "failure", "message": "bad key " + KEY},
                           status=400)
    assert success is False and KEY not in (err or "")


def test_an_ordinary_error_is_unchanged(monkeypatch):
    exc = HTTPClientError("API key rejected: OpenAI rejected the API key.", status_code=400)
    assert _put(monkeypatch, raise_exc=exc)[2] == "API key rejected: OpenAI rejected the API key."


@pytest.mark.parametrize("key", ["x", "key", "1234567"])
def test_a_short_local_key_never_mangles_the_message(monkeypatch, key):
    message = "Invalid key for model 'mixtral-8x7b' at 127.0.0.1:1234567"
    assert key in message  # the short key occurs in ordinary words
    exc = HTTPClientError(message, status_code=400)
    assert _put(monkeypatch, raise_exc=exc, key=key)[2] == message
