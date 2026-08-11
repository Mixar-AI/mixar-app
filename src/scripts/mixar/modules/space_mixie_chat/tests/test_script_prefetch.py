# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enqueue-time script asset prefetch + the executor's hold-until-ready gate.

Texture-apply scripts execute synchronously on Blender's main thread; these
tests pin the contract that keeps the UI responsive: asset downloads start at
enqueue time on background threads, and the executor timer holds the script
(cheap flag check per tick) until the cache is warm — never blocking the main
thread on the network.
"""

import importlib
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

# The runtime `mixar` package is synthesized by Blender's bootstrap; for
# pytest, src/scripts on sys.path + PEP 420 namespace packages give the same
# import surface (bpy is stubbed by the root conftest). Embedded-Python
# third-party deps pulled in by package __init__ chains are stubbed the same
# way the root conftest stubs bpy.
_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

from unittest.mock import MagicMock  # noqa: E402

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import script_prefetch  # noqa: E402
from mixar.modules.paint.layered_build import download as download_mod  # noqa: E402


def _manifest_script(urls):
    blob = ", ".join(f'"{u}"' for u in urls)
    return f'__PARAMS__ = {{"manifest": {{"maps": [{blob}]}}}}\nprint("apply")'


class TestExtractAssetUrls:
    def test_image_urls_with_presigned_query(self):
        script = _manifest_script([
            "https://s3.aws.com/maps/base.png?X-Amz-Signature=abc&X-Amz-Expires=900",
            "https://s3.aws.com/maps/normal.png",
        ])
        urls = script_prefetch.extract_asset_urls(script)
        assert len(urls) == 2
        assert urls[0].startswith("https://s3.aws.com/maps/base.png?X-Amz")

    def test_filters_non_image_urls_and_dedupes(self):
        script = (
            'a = "https://api.example.com/v1/jobs"\n'
            'b = "https://cdn.x.com/m.png"\n'
            'c = "https://cdn.x.com/m.png"\n'
        )
        assert script_prefetch.extract_asset_urls(script) == ["https://cdn.x.com/m.png"]

    def test_empty_script(self):
        assert script_prefetch.extract_asset_urls("") == []


class TestMaybeStartPrefetch:
    def test_gated_by_tool_name(self, monkeypatch):
        monkeypatch.setattr(
            download_mod, "download_to_tempfile", lambda url, **kw: "/tmp/x.png"
        )
        script = _manifest_script(["https://cdn.x.com/m.png"])
        assert script_prefetch.maybe_start_prefetch(script, "execute_bpy_script") is None
        handle = script_prefetch.maybe_start_prefetch(script, "create_layered_material")
        assert handle is not None
        assert handle.url_count == 1

    def test_no_urls_no_prefetch(self):
        assert (
            script_prefetch.maybe_start_prefetch("print('x')", "create_layered_material")
            is None
        )


class TestScriptAssetPrefetch:
    def test_ready_after_downloads_finish(self, monkeypatch):
        done_urls = []
        monkeypatch.setattr(
            download_mod,
            "download_to_tempfile",
            lambda url, **kw: done_urls.append(url) or "/tmp/x.png",
        )
        handle = script_prefetch.ScriptAssetPrefetch(
            [f"https://cdn.x.com/{i}.png" for i in range(4)]
        )
        deadline = time.monotonic() + 5.0
        while not handle.ready() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert handle.ready()
        assert len(done_urls) == 4

    def test_download_failure_still_sets_ready(self, monkeypatch):
        def boom(url, **kw):
            raise ValueError("dead url")

        monkeypatch.setattr(download_mod, "download_to_tempfile", boom)
        handle = script_prefetch.ScriptAssetPrefetch(["https://cdn.x.com/a.png"])
        deadline = time.monotonic() + 5.0
        while not handle.ready() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert handle.ready()

    def test_wait_cap_bounds_a_hung_download(self, monkeypatch):
        monkeypatch.setattr(script_prefetch, "PREFETCH_WAIT_CAP_SECONDS", 0.05)
        started = threading.Event()

        def hang(url, **kw):
            started.set()
            time.sleep(2.0)
            return "/tmp/x.png"

        monkeypatch.setattr(download_mod, "download_to_tempfile", hang)
        handle = script_prefetch.ScriptAssetPrefetch(["https://cdn.x.com/a.png"])
        assert started.wait(2.0)
        assert not handle._done.is_set()
        time.sleep(0.06)
        assert handle.ready()  # deadline passed — the executor must not stall


class TestExecutorHoldsForPrefetch:
    """The main-thread executor must hold a script whose assets are still
    downloading (returning a next-tick interval, executing nothing) and run
    it once ready — strict FIFO, response sent exactly once."""

    @pytest.fixture()
    def executor_mod(self, monkeypatch):
        ex = importlib.import_module(
            "mixar.modules.space_mixie_chat.core.main_thread_executor"
        )
        qp = importlib.import_module(
            "mixar.modules.space_mixie_chat.core.queue_processor"
        )
        sess = importlib.import_module("mixar.modules.space_mixie_chat.core.session")
        jc = importlib.import_module(
            "mixar.modules.space_mixie_chat.core.jsonrpc_client"
        )

        monkeypatch.setattr(qp, "drain_pending_events", lambda: 0)
        monkeypatch.setattr(
            sess,
            "get_session_manager",
            lambda: SimpleNamespace(has_active_session=lambda: True),
        )
        sent = []
        monkeypatch.setattr(
            jc,
            "get_jsonrpc_client",
            lambda: SimpleNamespace(
                is_connected=True,
                queue_response=lambda rid, res: sent.append((rid, res)),
            ),
        )
        executed = []

        def fake_execute(script):
            executed.append(script)
            return SimpleNamespace(success=True, to_dict=lambda: {"success": True})

        monkeypatch.setattr(
            ex,
            "get_executor",
            lambda: SimpleNamespace(
                _execution_lock=threading.Lock(), execute=fake_execute
            ),
        )
        # Skip scene routing: empty session follows the active window; None
        # window short-circuits every bpy.context branch.
        monkeypatch.setattr(ex, "bpy", SimpleNamespace(context=SimpleNamespace(window=None)))
        monkeypatch.setattr(ex, "_held", None)
        monkeypatch.setattr(ex, "_execution_gate_until", 0.0)
        while not ex._request_queue.empty():
            ex._request_queue.get_nowait()
        return ex, sent, executed

    def test_holds_then_executes_when_ready(self, executor_mod):
        ex, sent, executed = executor_mod

        class FakePrefetch:
            def __init__(self):
                self.is_ready = False

            def ready(self):
                return self.is_ready

        pf = FakePrefetch()
        ex._request_queue.put_nowait(("req-1", "print('apply')", "create_layered_material", "", None, pf))

        # Assets still downloading: held, nothing executed, timer keeps ticking.
        assert ex._process_one_request() is not None
        assert executed == [] and sent == []
        assert ex._held is not None
        assert ex.has_pending_requests()

        # Assets ready: executes and responds exactly once.
        pf.is_ready = True
        ex._process_one_request()
        assert executed == ["print('apply')"]
        assert sent == [("req-1", {"success": True})]
        assert ex._held is None

    def test_script_without_prefetch_runs_immediately(self, executor_mod):
        ex, sent, executed = executor_mod
        ex._request_queue.put_nowait(("req-2", "print('now')", "execute_bpy_script", "", None, None))
        ex._process_one_request()
        assert executed == ["print('now')"]
        assert sent == [("req-2", {"success": True})]
