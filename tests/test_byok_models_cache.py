# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent models catalog: disk cache + ETag revalidation.

The BYOK provider/model dropdowns used to be empty until a network round trip
landed — and under the WebSocket transport that round trip could not even be
attempted until the agent socket had handshaken. Persisting the catalog and
revalidating it with an ETag means the dropdowns are populated the first time
they draw, offline included.

The 304 path carries the load-bearing subtlety: `APIResponse.success` is
`response.ok`, which is True at 304, and the body is empty. Checking success
before the status would swap a live catalog for nothing.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api.response import APIResponse
from mixar.modules.byok.core import model_suggestions, models_cache, models_storage

PAYLOAD = {
    "providers": [
        {
            "id": "anthropic",
            "label": "Anthropic",
            "models": [{"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5"}],
        }
    ]
}


def _response(status=200, data=None, etag=None):
    return APIResponse(
        success=status < 400,
        status_code=status,
        data=data,
        message="",
        headers={"ETag": etag} if etag else {},
    )


def _envelope(payload):
    return {"status": "success", "message": "Models retrieved.", "data": payload}


class _InlineThread:
    """Run the worker synchronously so tests need no timing."""

    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self._target, self._args = target, args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    models_storage.set_path_for_tests(str(tmp_path / "agent_models.json"))
    model_suggestions.clear()
    models_cache.reset_lifecycle()
    monkeypatch.setattr(models_cache.threading, "Thread", _InlineThread)
    # Apply on the calling thread instead of a bpy timer.
    monkeypatch.setattr(
        models_cache, "_schedule_populate",
        lambda epoch, data: model_suggestions.populate_from_payload(data),
    )
    yield
    model_suggestions.clear()
    models_storage.set_path_for_tests(None)


def _serve(monkeypatch, response, seen=None):
    def _service():
        class _S:
            def list_models(self, etag=None):
                if seen is not None:
                    seen.append(etag)
                return response
        return _S()

    monkeypatch.setattr(models_cache, "get_agent_service", _service)


# ---------------------------------------------------------------------------

def test_a_200_populates_persists_and_records_the_etag(monkeypatch):
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))

    models_cache.refresh()

    assert model_suggestions.is_loaded()
    assert [p[0] for p in model_suggestions.get_provider_items()][0] == "anthropic"
    stored = json.loads(Path(models_storage._disk_path()).read_text())
    assert stored["etag"] == 'W/"abc"'
    assert stored["data"] == PAYLOAD


def test_the_stored_etag_is_sent_back_for_revalidation(monkeypatch):
    seen = []
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'), seen)
    models_cache.refresh()
    models_cache.refresh()

    assert seen == [None, 'W/"abc"']


def test_a_304_leaves_the_cache_completely_alone(monkeypatch):
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))
    models_cache.refresh()
    before = list(model_suggestions.get_provider_items())

    # A 304 has no body AND reports success — the status must be read first.
    _serve(monkeypatch, _response(304, None, etag='W/"abc"'))
    models_cache.refresh()

    assert model_suggestions.get_provider_items() == before
    assert model_suggestions.is_loaded()


def test_disk_cache_populates_before_any_network_call():
    """The instant-render claim: a second launch renders from disk."""
    models_storage.save('W/"abc"', PAYLOAD)
    model_suggestions.clear()

    assert models_cache.load_from_disk() is True
    assert [p[0] for p in model_suggestions.get_provider_items()][0] == "anthropic"


def test_an_authoritative_empty_catalog_replaces_the_cache(monkeypatch):
    """Backend-authoritative lists fail closed — an empty list is a kill switch."""
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))
    models_cache.refresh()

    _serve(monkeypatch, _response(200, _envelope({"providers": []}), etag='W/"def"'))
    models_cache.refresh()

    ids = [p[0] for p in model_suggestions.get_provider_items()]
    assert "anthropic" not in ids
    assert model_suggestions.is_loaded()  # fetched-and-empty, not never-fetched


def test_a_malformed_payload_keeps_the_previous_catalog(monkeypatch):
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))
    models_cache.refresh()

    _serve(monkeypatch, _response(200, _envelope({"nonsense": True}), etag='W/"def"'))
    models_cache.refresh()

    assert [p[0] for p in model_suggestions.get_provider_items()][0] == "anthropic"


def test_a_transport_failure_keeps_the_previous_catalog(monkeypatch):
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))
    models_cache.refresh()

    def _boom():
        class _S:
            def list_models(self, etag=None):
                raise ConnectionError("Failed to connect")
        return _S()

    monkeypatch.setattr(models_cache, "get_agent_service", _boom)
    models_cache.refresh()

    assert [p[0] for p in model_suggestions.get_provider_items()][0] == "anthropic"


def test_logout_clears_memory_and_the_disk_file(monkeypatch):
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))
    models_cache.refresh()
    path = Path(models_storage._disk_path())
    assert path.is_file()

    models_cache.clear()

    assert not path.exists()
    assert not model_suggestions.is_loaded()


def test_a_response_that_lands_after_logout_is_dropped(monkeypatch):
    """The epoch guard: a late 200 must not repopulate after a clear()."""
    captured = {}

    def _service():
        class _S:
            def list_models(self, etag=None):
                # Simulate the logout happening while this request is open.
                models_cache.clear()
                captured["cleared"] = True
                return _response(200, _envelope(PAYLOAD), etag='W/"abc"')
        return _S()

    monkeypatch.setattr(models_cache, "get_agent_service", _service)
    models_cache.refresh()

    assert captured["cleared"]
    assert not model_suggestions.is_loaded()
    assert not Path(models_storage._disk_path()).exists()


def test_the_disk_path_is_resolved_before_any_worker_persists(monkeypatch, tmp_path):
    """Workers must never touch bpy.utils — the path is resolved on the main thread.

    Resolution goes through the real `_data_dir()`, so `bpy.utils.user_resource`
    must answer with a sandbox path: the mock returns a MagicMock, which fails
    the str check and falls through to `~/.mixar` — a write outside pytest.
    """
    import bpy

    monkeypatch.setattr(
        bpy.utils, "user_resource", lambda *a, **k: str(tmp_path / "datafiles" / "mixar")
    )
    models_storage.set_path_for_tests(None)

    def _explode():
        raise AssertionError("_data_dir() reached from a worker")

    resolved = models_storage.initialize_disk_path()
    monkeypatch.setattr(models_storage, "_data_dir", _explode)
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))

    models_cache.refresh()  # must not raise

    assert models_storage._disk_path() == resolved
    assert Path(resolved).parent == tmp_path / "datafiles" / "mixar"
    assert Path(resolved).exists()


def test_an_unauthenticated_fetch_is_skipped_not_attempted(monkeypatch):
    """The bootstrap timer can beat the login hook.

    Spending a guaranteed 401 on every launch is pure noise — the auth hook
    re-fires the fetch the moment the token is validated.
    """
    import mixar.modules.auth.core.auth as auth

    monkeypatch.setattr(auth, "get_access_token", lambda: None)

    called = []

    def _service():
        class _S:
            def list_models(self, etag=None):
                called.append(etag)
                return _response(200, _envelope(PAYLOAD), etag='W/"abc"')
        return _S()

    monkeypatch.setattr(models_cache, "get_agent_service", _service)
    models_cache.refresh()

    assert called == []
    assert not model_suggestions.is_loaded()


def test_a_logout_between_the_epoch_check_and_the_disk_write_never_recreates_the_file(monkeypatch):
    """The invariant `_persistence_lock` exists for: clear() bumps the epoch under
    `_lock` and deletes the file under `_persistence_lock`, but a worker that
    passed its `_lock` epoch check just before may still be heading for its
    save. The disk write must re-check the epoch under the persistence lock.
    """
    original_populate = model_suggestions.populate_from_payload

    def _populate_then_logout(epoch, data):
        original_populate(data)   # the in-memory apply already went through
        models_cache.clear()      # ...and the user logs out before the save

    monkeypatch.setattr(models_cache, "_schedule_populate", _populate_then_logout)
    _serve(monkeypatch, _response(200, _envelope(PAYLOAD), etag='W/"abc"'))

    models_cache.refresh()

    assert not Path(models_storage._disk_path()).exists()
    assert not model_suggestions.is_loaded()
