# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lifecycle and authoritative-empty regression coverage for generation caches."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy

bpy.types.Panel.bl_rna = SimpleNamespace(
    properties={"bl_space_type": SimpleNamespace(enum_items=[])}
)

from mixar.bootstrap import chat_generate_options_cache as CHAT_CACHE
from mixar.bootstrap import generation_catalog_cache as CATALOG_CACHE
from mixar.bootstrap.generation_catalog import storage as CATALOG_STORAGE
from mixar.modules.auth.core import auth as AUTH
from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.services import generation_catalog_service as SERVICE


@pytest.fixture(autouse=True)
def _reset_cache_state(monkeypatch):
    """Keep module singletons deterministic across cache tests."""
    with CATALOG_CACHE._lock:
        CATALOG_CACHE._catalog = None
        CATALOG_CACHE._etag = None
        CATALOG_CACHE._cache_error = None
        CATALOG_CACHE._is_loading = False
        CATALOG_CACHE._shutdown_requested = False
        CATALOG_CACHE._lifecycle_epoch += 1
    with CHAT_CACHE._lock:
        CHAT_CACHE._options_data = None
        CHAT_CACHE._etag = None
        CHAT_CACHE._cache_error = None
        CHAT_CACHE._is_loading = False
        CHAT_CACHE._shutdown_requested = False
        CHAT_CACHE._lifecycle_epoch += 1

    monkeypatch.setattr(AUTH, "get_access_token", lambda: "test-token")
    monkeypatch.setattr(CATALOG_CACHE, "_schedule_catalog_swapped", lambda: None)
    monkeypatch.setattr(CHAT_CACHE, "_schedule_redraw", lambda: None)


def _catalog_response(capabilities):
    return APIResponse(
        success=True,
        status_code=200,
        data={
            "data": {
                "catalog_version": "empty-v1",
                "capabilities": capabilities,
            }
        },
        headers={"ETag": '"empty-v1"'},
    )


def _chat_response(options):
    return APIResponse(
        success=True,
        status_code=200,
        data={
            "data": {
                "catalog_version": "empty-v1",
                "options": options,
            }
        },
        headers={"ETag": '"empty-v1"'},
    )


def test_generation_catalog_accepts_and_persists_authoritative_empty(monkeypatch):
    saved = []
    service = SimpleNamespace(get_catalog=lambda **_kwargs: _catalog_response([]))
    monkeypatch.setattr(SERVICE, "get_generation_catalog_service", lambda: service)
    monkeypatch.setattr(
        CATALOG_STORAGE,
        "save",
        lambda etag, data: saved.append((etag, data)),
    )

    CATALOG_CACHE._fetch_data_sync()

    assert CATALOG_CACHE.is_loaded() is True
    assert CATALOG_CACHE.get_capabilities() == []
    assert CATALOG_CACHE.get_cache_error() is None
    assert saved == [('"empty-v1"', {
        "catalog_version": "empty-v1",
        "capabilities": [],
    })]


def test_chat_options_accept_empty_and_do_not_resurrect_static_services(monkeypatch):
    saved = []
    service = SimpleNamespace(get_chat_options=lambda **_kwargs: _chat_response([]))
    monkeypatch.setattr(SERVICE, "get_generation_catalog_service", lambda: service)
    monkeypatch.setattr(
        CHAT_CACHE,
        "_save_to_disk",
        lambda etag, data: saved.append((etag, data)),
    )

    CHAT_CACHE._fetch_data_sync()

    assert CHAT_CACHE.is_loaded() is True
    assert CHAT_CACHE.get_options() == []
    assert CHAT_CACHE.get_service_keys() == []
    assert CHAT_CACHE.resolve_service_key("image_gen") == ""
    assert CHAT_CACHE.get_generate_type_enum_items()[0][0] == "NONE"
    assert CHAT_CACHE.get_cache_error() is None
    assert saved == [('"empty-v1"', {
        "catalog_version": "empty-v1",
        "options": [],
    })]


def test_logout_invalidates_inflight_generation_catalog_response(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    saved = []

    class BlockingService:
        @staticmethod
        def get_catalog(**_kwargs):
            entered.set()
            assert release.wait(2.0)
            return _catalog_response([{"key": "image_gen"}])

    monkeypatch.setattr(
        SERVICE, "get_generation_catalog_service", lambda: BlockingService()
    )
    monkeypatch.setattr(CATALOG_STORAGE, "delete", lambda: None)
    monkeypatch.setattr(
        CATALOG_STORAGE,
        "save",
        lambda etag, data: saved.append((etag, data)),
    )

    worker = threading.Thread(target=CATALOG_CACHE._fetch_data_sync)
    worker.start()
    assert entered.wait(1.0)
    CATALOG_CACHE.clear_generation_catalog_cache()
    release.set()
    worker.join(2.0)

    assert not worker.is_alive()
    assert CATALOG_CACHE.is_loaded() is False
    assert CATALOG_CACHE.is_cache_loading() is False
    assert saved == []


def test_logout_invalidates_inflight_chat_options_response(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    saved = []

    class BlockingService:
        @staticmethod
        def get_chat_options(**_kwargs):
            entered.set()
            assert release.wait(2.0)
            return _chat_response([{"service_key": "image_gen"}])

    monkeypatch.setattr(
        SERVICE, "get_generation_catalog_service", lambda: BlockingService()
    )
    monkeypatch.setattr(CHAT_CACHE, "_delete_disk_cache", lambda: None)
    monkeypatch.setattr(
        CHAT_CACHE,
        "_save_to_disk",
        lambda etag, data: saved.append((etag, data)),
    )

    worker = threading.Thread(target=CHAT_CACHE._fetch_data_sync)
    worker.start()
    assert entered.wait(1.0)
    CHAT_CACHE.clear_chat_generate_options_cache()
    release.set()
    worker.join(2.0)

    assert not worker.is_alive()
    assert CHAT_CACHE.is_loaded() is False
    assert CHAT_CACHE.is_cache_loading() is False
    assert saved == []


def test_catalog_storage_path_is_resolved_before_worker_persistence(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setattr(CATALOG_STORAGE, "_resolved_disk_path", None)
    monkeypatch.setattr(CATALOG_STORAGE, "_data_dir", lambda: str(tmp_path))

    expected = tmp_path / "generation_catalog.json"
    assert CATALOG_STORAGE.initialize_disk_path() == str(expected)

    def _must_not_resolve_on_worker():
        raise AssertionError("worker attempted to resolve Blender user resource")

    monkeypatch.setattr(CATALOG_STORAGE, "_data_dir", _must_not_resolve_on_worker)
    thread = threading.Thread(
        target=CATALOG_STORAGE.save,
        args=('"etag"', {"catalog_version": "v1", "capabilities": []}),
    )
    thread.start()
    thread.join(2.0)

    assert not thread.is_alive()
    assert json.loads(expected.read_text(encoding="utf-8"))["data"][
        "capabilities"
    ] == []
