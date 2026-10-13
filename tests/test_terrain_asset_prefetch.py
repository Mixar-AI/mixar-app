# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Terrain preparation: one atomic background transfer, no GUI fallback."""
import io
import threading
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution import asset_cache
from mixar.modules.space_mixie_chat.core import script_prefetch
from mixar.modules.space_mixie_chat.core.sandbox_modules import RESTRICTED_URLLIB

URL = "https://bucket.s3.amazonaws.com/tree.blend?X-Amz-Signature=secret"


@pytest.fixture(autouse=True)
def cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(asset_cache.tempfile, "gettempdir", lambda: str(tmp_path))


def test_queued_terrain_warms_the_same_cache_without_main_thread_network(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def open_asset(url, **kw):
        calls.append(threading.current_thread())
        started.set()
        assert release.wait(3)
        return io.BytesIO(b"BLENDER asset")

    monkeypatch.setattr(RESTRICTED_URLLIB, "_urlopen", open_asset)
    handle = script_prefetch.maybe_start_prefetch(f'url = "{URL}"', "import_terrain_asset")
    try:
        assert started.wait(2)
        assert handle.state() == script_prefetch.PENDING
        assert RESTRICTED_URLLIB.cached_file(URL) is None
        assert calls[0] is not threading.current_thread()
    finally:
        release.set()
    assert handle._done.wait(2)
    assert handle.state() == script_prefetch.READY
    path = RESTRICTED_URLLIB.cached_file(URL)
    assert Path(path).read_bytes() == b"BLENDER asset"
    # The legacy consumer also uses this cache, rather than redownloading.
    assert RESTRICTED_URLLIB.prefetch([URL])[URL] == path
    assert len(calls) == 1


def test_cache_reuses_rotated_signatures_but_not_content_selectors():
    path = asset_cache.download(URL, opener=lambda *a, **kw: io.BytesIO(b"asset"))
    assert asset_cache.cached_path(URL.replace("secret", "rotated")) == path
    assert asset_cache.cached_path(URL + "&versionId=2") is None
    assert asset_cache.cached_path(URL.replace("bucket.", "other.")) is None
    assert asset_cache.cached_path(URL.replace("tree.blend", "rock.blend")) is None


def test_concurrent_downloads_publish_only_complete_files():
    started, release = threading.Event(), threading.Event()
    calls = []

    class Slow(io.BytesIO):
        def read(self, n=-1):
            started.set()
            assert release.wait(3)
            return super().read(n)

    def opener(*a, **kw):
        calls.append(1)
        return Slow(b"complete")

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(asset_cache.download, URL, opener=opener)
        assert started.wait(2)
        b = pool.submit(asset_cache.download, URL, opener=opener)
        try:
            assert asset_cache.cached_path(URL) is None
        finally:
            release.set()
        assert a.result() == b.result()
    assert calls == [1]
    assert Path(a.result()).read_bytes() == b"complete"


def test_failed_transfer_cleans_partial_file_and_can_retry(tmp_path):
    class Broken(io.BytesIO):
        def read(self, n=-1):
            if self.tell():
                raise OSError("connection lost")
            return super().read(n)

    with pytest.raises(OSError):
        asset_cache.download(URL, opener=lambda *a, **kw: Broken(b"partial"))
    assert asset_cache.cached_path(URL) is None
    assert not list(tmp_path.rglob("*.part"))
    assert not asset_cache._IN_FLIGHT
    assert asset_cache.download(URL, opener=lambda *a, **kw: io.BytesIO(b"ok"))


@pytest.mark.parametrize("url", ["https://evil.example/tree.blend", "file://amazonaws.com/tree.blend"])
def test_cache_consumer_keeps_the_host_and_transport_gate(url):
    with pytest.raises(PermissionError):
        RESTRICTED_URLLIB.cached_file(url)


def test_terrain_transport_failure_is_refused(monkeypatch):
    def fail(*a, **kw):
        raise OSError("offline")
    monkeypatch.setattr(RESTRICTED_URLLIB, "_urlopen", fail)
    handle = script_prefetch.maybe_start_prefetch(f'url = "{URL}"', "import_terrain_asset")
    assert handle._done.wait(2)
    assert handle.state() == script_prefetch.FAILED
    assert RESTRICTED_URLLIB.cached_file(URL) is None


def test_thread_start_failure_never_falls_through_to_script(monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("no thread")
    monkeypatch.setattr(threading.Thread, "start", fail)
    handle = script_prefetch.maybe_start_prefetch(f'url = "{URL}"', "import_terrain_asset")
    assert handle.state() == script_prefetch.FAILED


@pytest.mark.parametrize('role', ['', 'sandbox'])
def test_real_handshake_advertises_the_forest_runtime(monkeypatch, role):
    import json
    from types import SimpleNamespace
    from mixar.modules.space_mixie_chat.core import socket_connection, machine_info

    monkeypatch.setattr(machine_info, 'machine_block', lambda: {})
    monkeypatch.setattr(socket_connection, 'wait_for_handshake',
                        lambda *a, **kw: (socket_connection.HANDSHAKE_OK, None))
    client = SimpleNamespace(_next_request_id=lambda: 'review', _blender_version=None,
        _addon_version=None, _role=role, _device_id='', _parent_instance_id='parent',
        _ws=MagicMock(), _set_server_capabilities=lambda result: None)
    assert socket_connection.SocketConnection._perform_handshake(client) == socket_connection.HANDSHAKE_OK
    frame = json.loads(client._ws.send.call_args.args[0])
    assert 'forest_runtime_v1' in frame['params']['capabilities']
