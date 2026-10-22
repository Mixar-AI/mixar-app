# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Private asset-cache ownership, safe hits and atomic transfer boundaries."""

import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from mixar.modules.common.agent_execution import asset_cache as cache
from mixar.modules.common.agent_execution import asset_cache_directory as storage

URL = "https://bucket.s3.amazonaws.com/asset.blend?X-Amz-Signature=first"


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(storage.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(cache, "_DIRECTORY", None)
    yield
    assert not cache._IN_FLIGHT


def _download(payload=b"asset"):
    return Path(cache.download(URL, opener=lambda *a, **kw: io.BytesIO(payload)))


def _symlink(path, target, *, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")


def test_cold_lookup_does_not_create_storage_or_take_downloader_locks(monkeypatch, tmp_path):
    def unexpected():
        pytest.fail("A GUI cache miss created its backing directory")

    monkeypatch.setattr(cache, "CacheDirectory", unexpected)
    with cache._LOCK, cache._DIRECTORY_LOCK:
        assert cache.cached_path(URL) is None
    assert list(tmp_path.iterdir()) == []


def test_legacy_shared_cache_is_never_adopted(tmp_path):
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"private sentinel")
    legacy = tmp_path / "mixar_agent_assets"
    legacy.mkdir()
    _symlink(legacy / cache._name(URL), sentinel)
    assert cache.cached_path(URL) is None
    path = _download(b"downloaded asset")
    assert path.parent != legacy
    assert path.read_bytes() == b"downloaded asset"
    assert sentinel.read_bytes() == b"private sentinel"
    if os.name != "nt":
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_poisoned_file_hit_is_refused_and_replaced_without_touching_target(tmp_path, kind):
    path = _download()
    path.unlink()
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"private sentinel")
    if kind == "symlink":
        _symlink(path, sentinel)
    else:
        os.link(sentinel, path)
    assert cache.cached_path(URL) is None
    assert _download(b"replacement") == path
    assert path.read_bytes() == b"replacement"
    assert not path.is_symlink()
    assert path.stat().st_nlink == 1
    assert sentinel.read_bytes() == b"private sentinel"


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_replaced_directory_fails_closed_before_network(tmp_path, replacement):
    path = _download()
    directory = cache._DIRECTORY
    directory.path.rename(tmp_path / "original")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"private sentinel")
    if replacement == "symlink":
        _symlink(directory.path, outside, directory=True)
    else:
        directory.path.mkdir(mode=0o700)
        (directory.path / "sentinel").write_bytes(b"replacement belongs elsewhere")

    def unexpected(*a, **kw):
        pytest.fail("An unsafe root reached the network")

    assert cache.cached_path(URL) is None
    with pytest.raises(OSError, match="directory"):
        cache.download(URL, opener=unexpected)
    assert sentinel.read_bytes() == b"private sentinel"
    assert directory.path.exists()
    assert path.name not in {p.name for p in outside.iterdir()}


@pytest.mark.skipif(os.name == "nt", reason="Windows permissions use ACLs")
@pytest.mark.parametrize("target", ["directory", "file"])
def test_non_private_permissions_are_refused(target):
    path = _download()
    victim = path.parent if target == "directory" else path
    victim.chmod(0o755 if target == "directory" else 0o644)
    assert cache.cached_path(URL) is None
    if target == "directory":
        with pytest.raises(OSError, match="directory"):
            _download()
    else:
        assert _download(b"replacement").read_bytes() == b"replacement"


@pytest.mark.skipif(os.name == "nt", reason="Windows ownership uses ACLs")
def test_foreign_posix_owner_is_not_private():
    assert not storage._private(SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=0o700))


def test_windows_reparse_point_is_rejected_even_when_it_looks_regular():
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_file_attributes=0x400)
    assert storage._redirected(info)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO check")
def test_fifo_is_never_opened_or_waited_on(monkeypatch):
    path = _download()
    path.unlink()
    os.mkfifo(path)
    original = storage.os.open

    def checked_open(filename, *a, **kw):
        assert Path(filename).name != path.name, "Tried to open a cache FIFO"
        return original(filename, *a, **kw)

    monkeypatch.setattr(storage.os, "open", checked_open)
    assert cache.cached_path(URL) is None


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow race check")
def test_entry_swapped_to_link_between_stat_and_open_is_not_followed(monkeypatch, tmp_path):
    path = _download()
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"private sentinel")
    original = storage.os.open

    def swap_before_open(filename, flags, *a, **kw):
        if Path(filename).name == path.name:
            path.unlink()
            path.symlink_to(sentinel)
            assert flags & os.O_NOFOLLOW
        return original(filename, flags, *a, **kw)

    monkeypatch.setattr(storage.os, "open", swap_before_open)
    assert cache.cached_path(URL) is None
    assert sentinel.read_bytes() == b"private sentinel"


@pytest.mark.skipif(not storage._DIR_FD, reason="POSIX directory-descriptor race check")
def test_root_swapped_during_transfer_is_not_used_for_publication(tmp_path):
    _download()
    directory = cache._DIRECTORY
    path = directory.path / cache._name(URL)
    path.unlink()
    original = tmp_path / "original"
    outside = tmp_path / "outside"
    outside.mkdir()

    class SwapRoot(io.BytesIO):
        def read(self, n=-1):
            chunk = super().read(n)
            if chunk:
                directory.path.rename(original)
                _symlink(directory.path, outside, directory=True)
            return chunk

    with pytest.raises(OSError, match="directory"):
        cache.download(URL, opener=lambda *a, **kw: SwapRoot(b"asset"))
    assert list(outside.iterdir()) == []
    if storage._DIR_FD:
        assert list(original.iterdir()) == []  # cleanup uses the pinned dirfd


def test_completed_resource_path_survives_normal_exit_and_next_launch(tmp_path):
    # Loading the package by its real __path__ avoids Blender bootstrap; neither
    # cache module may depend on bpy/config access, even in a fresh interpreter.
    setup = """
import importlib, io, sys, tempfile, types
package = types.ModuleType('cache_exit_test')
package.__path__ = [sys.argv[1]]
sys.modules[package.__name__] = package
cache = importlib.import_module('cache_exit_test.asset_cache')
tempfile.tempdir = sys.argv[2]
"""
    create = setup + """
print(cache.download(sys.argv[3], opener=lambda *a, **kw: io.BytesIO(b'persisted image')))
"""
    args = [str(Path(cache.__file__).parent), str(tmp_path), URL]
    completed = subprocess.run([sys.executable, "-I", "-c", create, *args],
                               check=True, capture_output=True, text=True, timeout=10)
    path = Path(completed.stdout.strip())
    assert path.read_bytes() == b"persisted image"
    reopen = setup + """
from pathlib import Path
assert cache.cached_path(sys.argv[3]) is None  # lookups are process-local
assert Path(sys.argv[4]).read_bytes() == b'persisted image'
"""
    subprocess.run([sys.executable, "-I", "-c", reopen, *args, str(path)],
                   check=True, capture_output=True, text=True, timeout=10)


def test_rotated_signatures_coalesce_even_before_directory_creation(monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = cache.CacheDirectory
    calls = []

    def delayed_directory():
        started.set()
        assert release.wait(3)
        return original()

    def opener(*a, **kw):
        calls.append(1)
        return io.BytesIO(b"asset")

    monkeypatch.setattr(cache, "CacheDirectory", delayed_directory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.download, URL, opener=opener)
        assert started.wait(2)
        second = pool.submit(cache.download, URL.replace("first", "second"), opener=opener)
        try:
            assert cache.cached_path(URL) is None
        finally:
            release.set()
        assert first.result() == second.result()
    assert calls == [1]


@pytest.mark.parametrize("payload,length", [(b"", None), (b"short", "20")])
def test_empty_or_incomplete_download_is_never_published(payload, length, tmp_path):
    response = io.BytesIO(payload)
    response.headers = {} if length is None else {"Content-Length": length}
    with pytest.raises(OSError, match="empty or incomplete"):
        cache.download(URL, opener=lambda *a, **kw: response)
    assert response.closed
    assert cache.cached_path(URL) is None
    assert not list(tmp_path.rglob("*.part"))
    assert _download(b"recovered").read_bytes() == b"recovered"


def test_directory_creation_failure_clears_inflight_and_allows_retry(monkeypatch):
    original = cache.CacheDirectory

    def fail():
        raise OSError("not writable")

    monkeypatch.setattr(cache, "CacheDirectory", fail)
    with pytest.raises(OSError, match="not writable"):
        _download()
    assert cache._DIRECTORY is None
    assert not cache._IN_FLIGHT
    monkeypatch.setattr(cache, "CacheDirectory", original)
    assert _download(b"recovered").read_bytes() == b"recovered"


def test_platform_without_dirfd_keeps_safe_hits_and_atomic_replacement(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "_DIR_FD", False)
    path = _download()
    assert cache.cached_path(URL) == str(path)
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"private sentinel")
    path.unlink()
    _symlink(path, sentinel)
    assert cache.cached_path(URL) is None
    assert _download(b"replacement").read_bytes() == b"replacement"
    assert sentinel.read_bytes() == b"private sentinel"


def test_removed_cache_gets_a_fresh_private_directory_on_download():
    path = _download()
    path.unlink()
    path.parent.rmdir()
    assert cache.cached_path(URL) is None
    replacement = _download(b"recovered")
    assert replacement.parent != path.parent
    assert replacement.read_bytes() == b"recovered"
    assert not path.parent.exists()
