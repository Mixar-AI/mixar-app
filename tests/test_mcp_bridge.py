# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit + loopback-integration tests for the MCP bridge module.

Runs outside Blender: bpy is stubbed (root conftest + mock_bpy) and the
space_mixie_chat executor modules are replaced with fakes that run
main-thread jobs inline.
"""

import json
import sys
import types
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()


# ── Fake the space_mixie_chat executor seam ─────────────────────────────────

class _FakeExecutionResult:
    def __init__(self, script):
        self.script = script

    def to_dict(self):
        return {"success": True, "executed_script": self.script}


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, script, push_undo=True):
        self.calls.append((script, push_undo))
        return _FakeExecutionResult(script)


FAKE_EXECUTOR = _FakeExecutor()


def _install_executor_fakes():
    mte = types.ModuleType("mixar.modules.space_mixie_chat.core.main_thread_executor")
    mte.run_on_main_thread = lambda fn: fn()  # run inline
    mte.resume = lambda: None

    ex = types.ModuleType("mixar.modules.space_mixie_chat.core.executor")
    ex.get_executor = lambda: FAKE_EXECUTOR

    pkg_names = [
        "mixar.modules.space_mixie_chat",
        "mixar.modules.space_mixie_chat.core",
    ]
    for name in pkg_names:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["mixar.modules.space_mixie_chat.core.main_thread_executor"] = mte
    sys.modules["mixar.modules.space_mixie_chat.core.executor"] = ex


_install_executor_fakes()

from mixar.modules.mcp_bridge.constants import TOKEN_HEADER  # noqa: E402
from mixar.modules.mcp_bridge.core import executor_bridge, handlers  # noqa: E402

# The bridge now schedules onto Blender's main thread via its own
# `_schedule_on_main_thread` (bpy.app.timers). Outside Blender, run the job
# inline by default; specific tests override this to exercise the async path.
executor_bridge._schedule_on_main_thread = lambda fn: fn()


# ── build_script: the __PARAMS__ contract ────────────────────────────────────

def test_build_script_without_params_is_untouched():
    assert executor_bridge.build_script("x = 1") == "x = 1"


def test_build_script_injects_params_as_json_loads():
    script = executor_bridge.build_script("y = __PARAMS__['a']", {"a": 1, "b": "it's"})
    first_line, rest = script.split("\n", 1)
    assert first_line.startswith("__PARAMS__ = json.loads(")
    assert rest == "y = __PARAMS__['a']"
    # The embedded literal must round-trip through eval+json.loads unchanged.
    literal = first_line[len("__PARAMS__ = json.loads("):-1]
    assert json.loads(eval(literal)) == {"a": 1, "b": "it's"}  # noqa: S307


def test_build_script_params_survive_quotes_and_newlines():
    params = {"text": 'he said "hi"\nline2', "n": [1, 2]}
    script = executor_bridge.build_script("pass", params)
    first_line = script.split("\n", 1)[0]
    literal = first_line[len("__PARAMS__ = json.loads("):-1]
    assert json.loads(eval(literal)) == params  # noqa: S307


# ── execute_script through the (faked) main-thread seam ─────────────────────

def test_execute_script_returns_executor_envelope():
    result = executor_bridge.execute_script("bpy.ops.mesh.primitive_cube_add()")
    assert result["success"] is True
    assert "primitive_cube_add" in result["executed_script"]


def test_execute_script_rejects_empty_script():
    result = executor_bridge.execute_script("   ")
    assert result["success"] is False
    assert "non-empty" in result["error"]


def test_execute_script_passes_push_undo_flag():
    FAKE_EXECUTOR.calls.clear()
    executor_bridge.execute_script("pass", push_undo=False)
    assert FAKE_EXECUTOR.calls[-1][1] is False


def test_run_local_tool_rejects_unknown_domain():
    result = executor_bridge.run_local_tool("nope", "anything")
    assert result["success"] is False
    assert "unknown tool domain" in result["error"]
    assert "scene_graph" in result["available_domains"]


# ── Route table ──────────────────────────────────────────────────────────────

def test_route_request_unknown_endpoint_lists_routes():
    result = handlers.route_request("/nope", {})
    assert result["success"] is False
    assert "/execute" in result["available"]
    assert "/byok/set" in result["available"]


def test_route_request_rejects_non_dict_body():
    result = handlers.route_request("/execute", "not a dict")
    assert result["success"] is False


def test_route_request_execute_dispatches(monkeypatch):
    captured = {}

    def fake_execute(script, params=None, push_undo=True, timeout=None):
        captured.update(script=script, params=params, push_undo=push_undo, timeout=timeout)
        return {"success": True}

    monkeypatch.setattr(handlers.executor_bridge, "execute_script", fake_execute)
    result = handlers.route_request(
        "/execute",
        {"script": "pass", "params": {"k": 1}, "push_undo": False, "timeout": 5},
    )
    assert result["success"] is True
    assert captured == {"script": "pass", "params": {"k": 1}, "push_undo": False, "timeout": 5}


def test_route_request_byok_set_requires_fields(monkeypatch):
    # services_bridge validates presence before any network call.
    from mixar.modules.mcp_bridge.core import services_bridge

    result = services_bridge.byok_set("", "", "")
    assert result["success"] is False
    assert "required" in result["error"]


def test_generation_enqueue_requires_service_and_model():
    from mixar.modules.mcp_bridge.core import services_bridge

    result = services_bridge.generation_enqueue("", "", {})
    assert result["success"] is False


def test_generation_enqueue_rejects_non_dict_payload():
    from mixar.modules.mcp_bridge.core import services_bridge

    # A JSON string instead of an object (a plausible LLM slip) must fail loudly,
    # not silently submit an empty-payload job.
    result = services_bridge.generation_enqueue("image_gen", "flux", '{"prompt":"x"}')
    assert result["success"] is False
    assert "payload" in result["error"]


def test_redact_matches_secret_shaped_substrings():
    from mixar.modules.mcp_bridge.core import services_bridge

    data = {
        "byok_active": True,
        "api_key": "sk-should-hide",
        "access_token_full": "tok-should-hide",
        "client_key_preview": "kp-should-hide",
        "nested": {"user_secret_hint": "shh", "safe": "ok"},
        "items": [{"provider": "anthropic", "model_key": "hide-me"}],
    }
    red = services_bridge._redact(data)
    assert red["byok_active"] is True
    assert red["api_key"] == "***redacted***"
    assert red["access_token_full"] == "***redacted***"
    assert red["client_key_preview"] == "***redacted***"
    assert red["nested"]["user_secret_hint"] == "***redacted***"
    assert red["nested"]["safe"] == "ok"
    assert red["items"][0]["model_key"] == "***redacted***"
    assert red["items"][0]["provider"] == "anthropic"


def test_run_on_main_thread_sync_releases_lock_after_completion():
    # Two sequential calls must both succeed: the lock is released when the job
    # completes, so the second call is not answered "busy". (Inline schedule.)
    from mixar.modules.mcp_bridge.core import executor_bridge

    r1 = executor_bridge.run_on_main_thread_sync(lambda: {"success": True, "n": 1})
    r2 = executor_bridge.run_on_main_thread_sync(lambda: {"success": True, "n": 2})
    assert r1 == {"success": True, "n": 1}
    assert r2 == {"success": True, "n": 2}
    # Lock is free afterward (not stuck held).
    assert executor_bridge._EXEC_LOCK.acquire(blocking=False) is True
    executor_bridge._EXEC_LOCK.release()


def test_run_on_main_thread_sync_abandons_job_on_blend_load(monkeypatch):
    # If a .blend is loaded (generation bumped) between scheduling and the job
    # running, the job must be skipped (not run against the new file) and the
    # lock still released — never held forever.
    from mixar.modules.mcp_bridge.core import executor_bridge

    ran = {"called": False}

    def _fn():
        ran["called"] = True
        return {"success": True}

    # Simulate a file load happening before the (inline) job runs by bumping the
    # generation inside the scheduler, right before invoking the job.
    def _sched(fn):
        executor_bridge._on_load_post()  # a .blend was loaded
        fn()

    monkeypatch.setattr(executor_bridge, "_schedule_on_main_thread", _sched)
    result = executor_bridge.run_on_main_thread_sync(_fn)
    assert result.get("abandoned") is True
    assert ran["called"] is False  # fn must NOT run against the new file
    # Lock released despite the abandon.
    assert executor_bridge._EXEC_LOCK.acquire(blocking=False) is True
    executor_bridge._EXEC_LOCK.release()


def test_run_on_main_thread_sync_abandons_ghost_job_after_shutdown(monkeypatch):
    # Reload Scripts / shutdown force-releases the lock but the persistent timer
    # may still fire later. signal_shutdown() bumps the staleness epoch, so when
    # that orphaned job finally runs it must SKIP fn() (no unsupervised "ghost"
    # execution) rather than run against the reloaded state.
    from mixar.modules.mcp_bridge.core import executor_bridge

    ran = {"called": False}

    def _fn():
        ran["called"] = True
        return {"success": True}

    def _sched(fn):
        # Simulate: job scheduled, then a shutdown occurs before the timer fires.
        executor_bridge.signal_shutdown()
        try:
            fn()  # the persistent timer eventually fires post-reload
        finally:
            executor_bridge.clear_shutdown()

    monkeypatch.setattr(executor_bridge, "_schedule_on_main_thread", _sched)
    result = executor_bridge.run_on_main_thread_sync(_fn)
    assert result.get("abandoned") is True
    assert ran["called"] is False  # no ghost execution
    assert executor_bridge._EXEC_LOCK.acquire(blocking=False) is True
    executor_bridge._EXEC_LOCK.release()


def test_run_on_main_thread_sync_async_busy_then_release(monkeypatch):
    # Exercise the REAL async path (job runs on a background thread, not inline):
    # while a long job holds the lock, an overlapping caller must get "busy";
    # once the job completes the lock frees and a later call succeeds — proving
    # the busy-on-retry guarantee without releasing a still-running job's lock.
    import threading as _t

    from mixar.modules.mcp_bridge.core import executor_bridge

    monkeypatch.setattr(
        executor_bridge,
        "_schedule_on_main_thread",
        lambda fn: _t.Thread(target=fn, daemon=True).start(),
    )
    # Shorten the busy-wait so the test is fast but still real.
    monkeypatch.setattr(executor_bridge, "_LOCK_ACQUIRE_TIMEOUT_S", 0.3)

    release_a = _t.Event()
    a_started = _t.Event()
    a_result = {}

    def _slow():
        a_started.set()
        release_a.wait(5.0)  # hold the main-thread slot until the test frees it
        return {"success": True, "job": "A"}

    def _run_a():
        a_result["r"] = executor_bridge.run_on_main_thread_sync(_slow, timeout=5.0)

    ta = _t.Thread(target=_run_a, daemon=True)
    ta.start()
    assert a_started.wait(2.0), "job A never started"

    # B overlaps while A holds the lock → must be answered busy (no duplicate run).
    b = executor_bridge.run_on_main_thread_sync(lambda: {"success": True, "job": "B"}, timeout=2.0)
    assert b.get("busy") is True

    # Let A finish; the lock frees, and a later call C succeeds.
    release_a.set()
    ta.join(5.0)
    assert a_result["r"] == {"success": True, "job": "A"}
    c = executor_bridge.run_on_main_thread_sync(lambda: {"success": True, "job": "C"}, timeout=2.0)
    assert c == {"success": True, "job": "C"}


# ── Vendored Blender handler surface (/api/*) ────────────────────────────────

def test_route_request_delegates_api_paths(monkeypatch):
    from mixar.modules.mcp_bridge.core import blender_dispatch

    seen = {}

    def fake_dispatch(path, params):
        seen["path"] = path
        seen["params"] = params
        return {"success": True, "data": {"ok": 1}}

    # route_request lazy-imports dispatch_blender from this module at call time,
    # so patching the attribute here is honored.
    monkeypatch.setattr(blender_dispatch, "dispatch_blender", fake_dispatch)
    result = handlers.route_request("/api/scene/info", {"a": 1})
    assert result == {"success": True, "data": {"ok": 1}}
    assert seen["path"] == "/api/scene/info"
    assert seen["params"] == {"a": 1}


def test_route_request_api_rejects_non_dict_body():
    result = handlers.route_request("/api/scene/info", "nope")
    assert result["success"] is False


def test_blender_queue_shim_timeout_selection():
    from mixar.modules.mcp_bridge.blender.utils import queue as q

    # Every genuinely long-running route must get the extended timeout —
    # including the non-obvious ones (anim bake, offscreen viewport render).
    for long_route in ("render/image", "physics/bake", "physics/free-bake",
                       "export/fbx", "texture/bake", "anim/bake",
                       "viewport/render-preview"):
        assert q._select_timeout(long_route) == q.LONG_OPERATION_TIMEOUT, long_route
    # Fast routes keep the default.
    for short_route in ("scene/info", "object/create", "anim/get-keyframes", None):
        assert q._select_timeout(short_route) == q.RESULT_TIMEOUT, short_route


def test_python_exec_gate_blocks_when_disabled(monkeypatch):
    from mixar.modules.mcp_bridge.core import blender_dispatch

    monkeypatch.setenv("MIXAR_MCP_ALLOW_PYTHON_EXEC", "0")
    for route in ("/api/python/exec", "/api/python/exec-file"):
        result = blender_dispatch.dispatch_blender(route, {"code": "x = 1"})
        assert result["success"] is False
        assert "disabled" in result["error"]


def test_python_exec_gate_default_enabled(monkeypatch):
    # Default (unset) must NOT be treated as disabled — the gate only trips on
    # explicit off values, so a normal call proceeds past the gate to dispatch.
    from mixar.modules.mcp_bridge.core import blender_dispatch

    monkeypatch.delenv("MIXAR_MCP_ALLOW_PYTHON_EXEC", raising=False)
    assert blender_dispatch._python_exec_allowed() is True


def test_dispatch_blender_never_raises():
    # blender_dispatch wraps the handler import so a failure (e.g. Blender math
    # modules unavailable outside a real Blender process) degrades to an error
    # envelope instead of a 500. Inside real Mixar it returns the handler
    # result; either way it must be a dict carrying "success".
    from mixar.modules.mcp_bridge.core.blender_dispatch import dispatch_blender

    result = dispatch_blender("/api/scene/info", {})
    assert isinstance(result, dict)
    assert "success" in result


# ── Loopback HTTP server integration (real socket, ephemeral port) ──────────

@pytest.fixture()
def bridge_server(monkeypatch):
    from mixar.modules.mcp_bridge.core import server as server_mod

    server_mod.stop_server()
    # Fixed token for deterministic tests (avoids touching the token file).
    monkeypatch.setenv("MIXAR_MCP_TOKEN", "test-token")
    srv = server_mod.start_server(host="127.0.0.1", port=0)
    assert srv is not None
    port = srv.server_address[1]
    yield server_mod, port, "test-token"
    server_mod.stop_server()


def _post(port, path, body, headers=None, content_type="application/json", token="test-token"):
    hdrs = {}
    if content_type is not None:
        hdrs["Content-Type"] = content_type
    if token is not None:
        hdrs[TOKEN_HEADER] = token
    hdrs.update(headers or {})
    req = urllib.request.Request(
        "http://127.0.0.1:{0}{1}".format(port, path),
        data=json.dumps(body).encode("utf-8"),
        headers=hdrs,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health_requires_token(bridge_server):
    _, port, _token = bridge_server
    # No token → 401.
    req = urllib.request.Request("http://127.0.0.1:{0}/health".format(port))
    try:
        urllib.request.urlopen(req, timeout=10)
        status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 401


def test_health_endpoint_with_token(bridge_server):
    _, port, token = bridge_server
    req = urllib.request.Request(
        "http://127.0.0.1:{0}/health".format(port), headers={TOKEN_HEADER: token}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    assert data["success"] is True
    assert data["app"] == "mixar"


def test_post_execute_roundtrip(bridge_server):
    _, port, _token = bridge_server
    status, data = _post(port, "/execute", {"script": "pass"})
    assert status == 200
    assert data["success"] is True


def test_post_unknown_route_is_self_diagnosing(bridge_server):
    _, port, _token = bridge_server
    status, data = _post(port, "/does-not-exist", {})
    assert status == 200
    assert data["success"] is False
    assert "/tool" in data["available"]


def test_post_invalid_json_is_400(bridge_server):
    _, port, token = bridge_server
    req = urllib.request.Request(
        "http://127.0.0.1:{0}/execute".format(port),
        data=b"{not json",
        headers={"Content-Type": "application/json", TOKEN_HEADER: token},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        raised = False
    except urllib.error.HTTPError as exc:
        raised = exc.code == 400
    assert raised


def test_missing_token_is_401(bridge_server):
    _, port, _token = bridge_server
    status, data = _post(port, "/execute", {"script": "pass"}, token=None)
    assert status == 401
    assert data["success"] is False


def test_non_json_content_type_is_415(bridge_server):
    _, port, _token = bridge_server
    status, data = _post(port, "/execute", {"script": "pass"}, content_type="text/plain")
    assert status == 415


def test_origin_header_is_forbidden(bridge_server):
    _, port, _token = bridge_server
    status, data = _post(
        port, "/execute", {"script": "pass"}, headers={"Origin": "http://evil.example"}
    )
    assert status == 403
    assert "Origin" in data["error"]


def test_host_header_parsing_including_ipv6():
    from mixar.modules.mcp_bridge.core import server as server_mod

    ok = server_mod._host_header_ok
    assert ok("127.0.0.1:9877", 9877) is True
    assert ok("localhost", 9877) is True
    assert ok("[::1]:9877", 9877) is True
    assert ok("[::1]", 9877) is True  # bracketed IPv6 without port
    assert ok("attacker.example", 9877) is False
    assert ok("evil.example:80", 9877) is False
    assert ok("", 9877) is False


def test_non_loopback_host_header_is_forbidden(bridge_server):
    _, port, _token = bridge_server
    status, data = _post(
        port, "/execute", {"script": "pass"}, headers={"Host": "attacker.example"}
    )
    assert status == 403


def test_refuses_non_loopback_bind(monkeypatch):
    from mixar.modules.mcp_bridge.core import server as server_mod

    server_mod.stop_server()
    srv = server_mod.start_server(host="0.0.0.0", port=0)
    assert srv is None
    assert server_mod.is_running() is False


def test_auto_token_generated_when_env_unset(monkeypatch):
    from mixar.modules.mcp_bridge.core import server as server_mod

    server_mod.stop_server()
    monkeypatch.delenv("MIXAR_MCP_TOKEN", raising=False)
    srv = server_mod.start_server(host="127.0.0.1", port=0)
    try:
        assert srv is not None
        # A token was established; unauthenticated POST is rejected.
        port = srv.server_address[1]
        status, _ = _post(port, "/execute", {"script": "pass"}, token=None)
        assert status == 401
        # With the generated token it passes.
        status, data = _post(port, "/execute", {"script": "pass"}, token=server_mod._active_token)
        assert status == 200
        assert data["success"] is True
    finally:
        server_mod.stop_server()
