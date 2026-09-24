# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Background map prefetch for the agent apply path (no Blender needed).

The backend starts a finish's map downloads with a quick call, polls
``prefetch_status`` between other agents' scripts, and sends the apply script
only once every map is on disk, so the apply holds the connection for the
build alone. These tests pin the registry that makes that safe: idempotent
starts, honest status, failures that do not restart in a loop, and a
synchronous prefetch that waits for an in-flight download instead of fetching
the same URL twice.
"""

import importlib.util
import sys
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_PY = ROOT / "src/scripts/mixar/modules/paint/layered_build/download.py"
PREFETCH_PY = ROOT / "src/scripts/mixar/modules/paint/core/agent_tools/map_prefetch.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def download(tmp_path, monkeypatch):
    mod = _load("lb_download_prefetch", DOWNLOAD_PY)
    monkeypatch.setattr(mod.tempfile, "gettempdir", lambda: str(tmp_path))
    return mod


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_start_is_background_idempotent_and_reports_progress(download, monkeypatch):
    release = threading.Event()
    calls = []

    def fake_read(url, timeout):
        calls.append(url)
        release.wait(5)
        return b"PNG"

    monkeypatch.setattr(download, "_read_url", fake_read)
    urls = ["https://s3.example/a/basecolor.png", "https://s3.example/a/normal.png"]

    assert download.start_prefetch(urls) == 2
    assert _wait(lambda: len(calls) == 2)
    status = download.prefetch_status(urls)
    assert status == {"total": 2, "ready": 0, "pending": 2, "missing": 0, "failed": []}
    # Already downloading: a second start begins nothing new.
    assert download.start_prefetch(urls) == 0

    release.set()
    assert _wait(lambda: download.prefetch_status(urls)["ready"] == 2)
    assert download.start_prefetch(urls) == 0  # cached now
    assert len(calls) == 2


def test_a_failure_is_reported_and_not_restarted_in_a_loop(download, monkeypatch):
    def fake_read(url, timeout):
        raise PermissionError("403 Forbidden")

    monkeypatch.setattr(download, "_read_url", fake_read)
    url = "https://s3.example/a/roughness.png"
    download.start_prefetch([url])
    assert _wait(lambda: download.prefetch_status([url])["failed"])
    status = download.prefetch_status([url])
    assert status["pending"] == 0 and status["ready"] == 0
    assert "PermissionError" in status["failed"][0]
    assert download.start_prefetch([url]) == 0


def test_a_refused_scheme_fails_instead_of_staying_missing(download):
    url = "file:///etc/passwd.png"
    download.start_prefetch([url])
    assert _wait(lambda: download.prefetch_status([url])["failed"])
    assert download.prefetch_status([url])["missing"] == 0


def test_the_sync_prefetch_waits_for_an_inflight_download(download, monkeypatch):
    release = threading.Event()
    calls = []

    def fake_read(url, timeout):
        calls.append(url)
        release.wait(5)
        return b"PNG"

    monkeypatch.setattr(download, "_read_url", fake_read)
    url = "https://s3.example/a/height.png"
    download.start_prefetch([url])
    assert _wait(lambda: calls)
    threading.Timer(0.2, release.set).start()
    assert download.prefetch_urls([url]) == {}
    assert calls == [url]  # fetched once, by the background worker


def test_the_agent_helper_starts_and_reports(download, monkeypatch):
    monkeypatch.setattr(download, "_read_url", lambda url, timeout: b"PNG")
    for name in ("mixar", "mixar.modules", "mixar.modules.paint", "mixar.modules.paint.layered_build"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "mixar.modules.paint.layered_build.download", download)
    helper = _load("agent_map_prefetch_under_test", PREFETCH_PY)

    urls = ["https://s3.example/b/basecolor.png", "https://s3.example/b/normal.png"]
    first = helper.prefetch_layered_maps(urls)
    assert first["success"] is True and first["started"] == 2 and first["total"] == 2
    assert _wait(lambda: helper.prefetch_layered_maps(urls, start=False)["complete"])
    again = helper.prefetch_layered_maps(urls)
    assert again["started"] == 0 and again["complete"] is True
    assert helper.prefetch_layered_maps([])["complete"] is False


def test_a_resigned_url_hits_the_same_cache_entry(download):
    first = ("https://bucket.s3.amazonaws.com/pbr/users/7/generations/r1/basecolor_r1.png"
             "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=a&X-Amz-Date=1&X-Amz-Expires=900"
             "&X-Amz-Signature=abc&X-Amz-Security-Token=t1")
    resigned = first.replace("X-Amz-Signature=abc", "X-Amz-Signature=def").replace("t1", "t2")
    assert download._filename_for_url(first) == download._filename_for_url(resigned)
    other = first.replace("basecolor_r1", "normal_r1")
    assert download._filename_for_url(first) != download._filename_for_url(other)
    # A query that names the asset (not a signature) still separates entries.
    assert download._filename_for_url("https://cdn.example/t.png?id=1") != \
        download._filename_for_url("https://cdn.example/t.png?id=2")
