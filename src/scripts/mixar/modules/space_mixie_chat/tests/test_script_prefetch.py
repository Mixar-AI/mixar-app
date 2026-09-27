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
from mixar.modules.space_mixie_chat.core import script_lanes as lanes  # noqa: E402
from mixar.modules.common.agent_execution.request import ExecutionRequest  # noqa: E402


def _put(ex, legacy_tuple):
    assert lanes.enqueue(ExecutionRequest.from_legacy(legacy_tuple))
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
            lambda: SimpleNamespace(has_active_session=lambda session_id="": True),
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

        def fake_execute(script, push_undo=True, session_id=""):
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
        monkeypatch.setattr(ex, "_execution_gate_until", 0.0)
        lanes.clear()
        return ex, sent, executed

    def test_holds_then_executes_when_ready(self, executor_mod):
        ex, sent, executed = executor_mod

        class FakePrefetch:
            def __init__(self):
                self.is_ready = False

            def ready(self):
                return self.is_ready

        pf = FakePrefetch()
        _put(ex, ("req-1", "print('apply')", "create_layered_material", "", None, pf))

        # Assets still downloading: held, nothing executed, timer keeps ticking.
        assert ex._process_one_request() is not None
        assert executed == [] and sent == []
        assert lanes.held("") is not None
        assert ex.has_pending_requests()

        # Assets ready: executes and responds exactly once.
        pf.is_ready = True
        ex._process_one_request()
        assert executed == ["print('apply')"]
        assert sent == [("req-1", {"success": True})]
        assert not ex.has_pending_requests()

    def test_script_without_prefetch_runs_immediately(self, executor_mod):
        ex, sent, executed = executor_mod
        _put(ex, ("req-2", "print('now')", "execute_bpy_script", "", None, None))
        ex._process_one_request()
        assert executed == ["print('now')"]
        assert sent == [("req-2", {"success": True})]

    def test_a_held_prefetch_blocks_only_its_own_tab(self, executor_mod):
        """Parallel scene tabs: tab A's texture download must not park tab B."""
        ex, sent, executed = executor_mod

        class FakePrefetch:
            is_ready = False

            def ready(self):
                return self.is_ready

        pf = FakePrefetch()
        _put(ex, ("a-1", "print('A apply')", "create_layered_material", "", {"chat_session_id": "A"}, pf))
        _put(ex, ("b-1", "print('B')", "execute_bpy_script", "", {"chat_session_id": "B"}, None))
        ex._process_one_request()
        assert executed == ["print('B')"]
        assert lanes.held("A") is not None and ex.has_pending_requests()
        pf.is_ready = True
        ex._process_one_request()
        assert executed == ["print('B')", "print('A apply')"]
        assert [rid for rid, _ in sent] == ["b-1", "a-1"]

    def test_tabs_are_served_round_robin(self, executor_mod):
        """A queue of tab-A scripts delays a tab-B script by at most one script,
        and the tick after a tab switch has no 0.5 s breather."""
        ex, sent, executed = executor_mod
        for n in range(3):
            _put(ex, (f"a-{n}", f"print('A{n}')", "execute_bpy_script", "", {"chat_session_id": "A"}, None))
        _put(ex, ("b-0", "print('B0')", "execute_bpy_script", "", {"chat_session_id": "B"}, None))
        _put(ex, ("lane-0", "print('A lane')", "execute_bpy_script", "",
                  {"chat_session_id": "A"}, None))
        intervals = [ex._process_one_request() for _ in range(5)]
        assert executed == ["print('A0')", "print('B0')", "print('A1')", "print('A2')", "print('A lane')"]
        # A0 -> (B pending) short tick; B0 -> short; A1 -> A2 same tab: breather.
        assert intervals[0] < 0.1 and intervals[1] < 0.1 and intervals[2] == 0.50
        assert intervals[-1] is None and not ex.has_pending_requests()

    def test_flush_session_drops_only_that_tab(self, executor_mod):
        ex, sent, executed = executor_mod
        _put(ex, ("a-0", "print('A0')", "execute_bpy_script", "", {"chat_session_id": "A"}, None))
        _put(ex, ("b-0", "print('B0')", "execute_bpy_script", "", {"chat_session_id": "B"}, None))
        _put(ex, ("a-1", "print('A1')", "execute_bpy_script", "", {"chat_session_id": "A"}, None))
        assert ex.flush_session("A") == 2
        assert sorted(rid for rid, _ in sent) == ["a-0", "a-1"]
        assert all(not res.get("success") for _, res in sent)
        ex._process_one_request()
        assert executed == ["print('B0')"]
        assert not ex.has_pending_requests()

    def test_cleanup_with_an_empty_session_id_keeps_every_other_tab(self, executor_mod):
        """A tab that has not sent its first message (session id "") owns no
        scripts: New Chat / close on it must not take the global reset that
        wipes the other tabs' queued scripts without an error reply."""
        ex, sent, executed = executor_mod
        _put(ex, ("a-0", "print('A0')", "execute_bpy_script", "", {"chat_session_id": "A"}, None))
        _put(ex, ("b-0", "print('B0')", "execute_bpy_script", "", {"chat_session_id": "B"}, None))
        ex.cleanup(session_id="")
        assert sent == [] and ex.has_pending_requests() and lanes.count() == 2
        ex.cleanup(session_id=None)
        assert not ex.has_pending_requests() and lanes.count() == 0
