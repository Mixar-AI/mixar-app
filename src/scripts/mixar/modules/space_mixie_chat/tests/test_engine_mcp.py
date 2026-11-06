# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``engine_mcp``: Unreal's three editor MCP tools passed through to the agent
(list_toolsets, describe_toolset, call_tool), against a fake Unreal MCP
server client shaped like Unreal 5.8.3's answers (no engine, no Blender)."""

import json
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import engine_link as el  # noqa: E402
from mixar.modules.space_mixie_chat.core import engine_mcp as em  # noqa: E402

UNREAL = {"engine": "unreal", "transport": "unreal_mcp", "pid": 1, "_path": "x"}
GODOT = {"engine": "godot", "pid": 2, "token": "t", "_path": "y"}
LISTING = ("- SceneTools: Find, add and edit actors in the open level\n"
           "  and its sublevels.\n"
           "- ToolsetRegistry.AgentSkillToolset: Epic's agent skills\n")
PNG = "iVBORw0KGgo" + "A" * 200


def _text(value):
    return {"content": [{"type": "text", "text": value if isinstance(value, str) else json.dumps(value)}]}


def _toolset(name, count, description="Does a thing.\nSecond line of detail."):
    return {"name": name, "version": "1.0", "description": f"{name} tools",
            "tools": [{"name": f"{name}.tool_{i}", "description": description,
                       "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
                       "outputSchema": {}} for i in range(count)]}


class FakeUnreal(el.UnrealMcpClient):
    """Unreal's MCP server: the three top-level tools, answered by ``replies``."""

    def __init__(self, replies=None, instructions=""):
        super().__init__(9880, "/mcp", "mixar_link.toolsets.MixarLinkTools")
        self.replies = replies or {}
        self.calls = []
        self.server_instructions = instructions

    def initialize(self, timeout=10.0):
        self.session = "s"
        self.instructions = self.server_instructions
        return {}

    def _rpc(self, method, params, timeout):
        assert method == "tools/call"
        self.calls.append((params["name"], params["arguments"], timeout))
        reply = self.replies.get(params["name"])
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(params["arguments"])
        return 200, {}, {"result": reply if reply is not None else _text("")}


@pytest.fixture
def unreal(monkeypatch):
    holder = {"client": FakeUnreal(), "info": UNREAL}
    monkeypatch.setattr(el, "_connect", lambda engine: (holder["info"], holder["client"]))
    el._prefetched.clear()
    return holder


def test_list_returns_the_servers_text_verbatim(unreal):
    unreal["client"] = FakeUnreal({"list_toolsets": _text(LISTING)})
    out = em.link_mcp_list_toolsets()
    assert out == {"success": True, "data": {"toolsets": LISTING}}
    assert unreal["client"].calls[0][:2] == ("list_toolsets", {})  # the top-level tool, not Mixar Link's


def test_list_carries_server_instructions_when_sent(unreal):
    unreal["client"] = FakeUnreal({"list_toolsets": _text(LISTING)}, instructions="Read skills first.")
    assert em.link_mcp_list_toolsets()["data"]["instructions"] == "Read skills first."


def test_the_handshake_keeps_instructions_on_the_client():
    client = el.McpClient(1, "t")
    replies = iter([(200, {"mcp-session-id": "s"}, {"result": {"instructions": "Hi"}}), (202, {}, None)])
    client._post = lambda payload, timeout: next(replies)
    client.initialize()
    assert client.instructions == "Hi"


def test_describe_full_small_toolset(unreal):
    described = _toolset("SceneTools", 3)
    unreal["client"] = FakeUnreal({"describe_toolset": _text(described)})
    out = em.link_mcp_describe("SceneTools")
    assert out["success"] and out["data"] == described
    assert unreal["client"].calls[0][1] == {"toolset_name": "SceneTools"}


def test_describe_filters_by_short_or_full_name_and_names_the_missing(unreal):
    unreal["client"] = FakeUnreal({"describe_toolset": _text(_toolset("SequencerTools", 140))})
    out = em.link_mcp_describe("SequencerTools", tools=["tool_3", "SequencerTools.tool_7", "nope"])
    data = out["data"]
    assert [t["name"] for t in data["tools"]] == ["SequencerTools.tool_3", "SequencerTools.tool_7"]
    assert "inputSchema" in data["tools"][0]  # full schemas
    assert data["missing"] == ["nope"] and "truncated" not in data


def test_describe_compacts_a_large_toolset(unreal):
    big = _toolset("SequencerTools", 140, description="Adds a key.\n" + "detail " * 60)
    assert len(json.dumps(big)) > em.DESCRIBE_LIMIT
    unreal["client"] = FakeUnreal({"describe_toolset": _text(big)})
    data = em.link_mcp_describe("SequencerTools")["data"]
    assert data["truncated"] is True and "tools=[" in data["note"]
    assert len(data["tools"]) == 140
    assert data["tools"][0] == {"name": "SequencerTools.tool_0", "description": "Adds a key."}
    assert len(json.dumps(data)) < em.DESCRIBE_LIMIT


def test_describe_error_is_the_servers_text(unreal):
    unreal["client"] = FakeUnreal({"describe_toolset": {"isError": True, "content": [
        {"type": "text", "text": "Toolset 'Nope' not found"}]}})
    assert em.link_mcp_describe("Nope") == {"success": False, "error": "Toolset 'Nope' not found"}


def test_call_returns_the_return_value_and_passes_arguments_verbatim(unreal):
    actors = [{"refPath": "/Game/Map.Map:PersistentLevel.Cube_1"}]
    unreal["client"] = FakeUnreal({"call_tool": _text({"returnValue": actors})})
    args = {"name": "Cube", "tag": "", "collision_channels": []}
    out = em.link_mcp_call("find_actors", "SceneTools", args, timeout=12)
    assert out == {"success": True, "data": {"result": actors}}
    name, sent, timeout = unreal["client"].calls[0]
    assert name == "call_tool" and timeout == 12.0
    assert sent == {"tool_name": "find_actors", "toolset_name": "SceneTools", "arguments": args}


def test_call_without_toolset_omits_it_and_plain_text_comes_back_as_text(unreal):
    unreal["client"] = FakeUnreal({"call_tool": _text("Done.")})
    out = em.link_mcp_call("get_current_level")  # bare: a top-level tool (dotted names split)
    assert out["data"]["result"] == "Done."
    assert "toolset_name" not in unreal["client"].calls[0][1]
    assert unreal["client"].calls[0][1]["arguments"] == {}


def test_call_error_is_the_servers_text_scrubbed(unreal):
    msg = "Missing argument 'tag'\nschema: {...}\nat C:\\Users\\me\\Proj\\Content\\x.py"
    unreal["client"] = FakeUnreal({"call_tool": {"isError": True, "content": [{"type": "text", "text": msg}]}})
    out = em.link_mcp_call("find_actors", "SceneTools", {})
    assert out["success"] is False
    assert out["error"].startswith("Missing argument 'tag'\nschema")
    assert "C:\\Users" not in out["error"] and "<local path>" in out["error"]


def test_call_mcp_image_items_become_images(unreal):
    content = [{"type": "image", "data": PNG, "mimeType": "image/png"} for _ in range(4)]
    unreal["client"] = FakeUnreal({"call_tool": {"content": content}})
    out = em.link_mcp_call("CaptureEditorImage", "EditorAppToolset")
    assert out["success"] and len(out["images"]) == 3
    assert out["images"][0] == {"data": PNG, "mime": "image/png"}


def test_call_capture_json_images_are_lifted_out_of_the_result(unreal):
    # CaptureViewport, as Unreal 5.8.3 answers it: the image inside the returnValue.
    value = {"image": {"mimeType": "image/png", "data": PNG}, "cameraLocation": {"x": 1, "y": 2, "z": 3}}
    unreal["client"] = FakeUnreal({"call_tool": _text({"returnValue": value})})
    out = em.link_mcp_call("CaptureViewport", "EditorAppToolset", {})
    assert out["images"] == [{"data": PNG, "mime": "image/png"}]
    assert out["data"]["result"] == {"image": {"mimeType": "image/png", "attached": True},
                                     "cameraLocation": {"x": 1, "y": 2, "z": 3}}
    assert PNG not in json.dumps(out["data"])
    # CaptureAssetImage: the returnValue is the image itself.
    unreal["client"] = FakeUnreal({"call_tool": _text({"returnValue": {"mimeType": "image/jpeg", "data": PNG}})})
    out = em.link_mcp_call("CaptureAssetImage", "EditorAppToolset", {"asset": "/Game/SM_Cube"})
    assert out["images"] == [{"data": PNG, "mime": "image/jpeg"}]
    assert out["data"]["result"] == {"mimeType": "image/jpeg", "attached": True}


def test_more_than_three_lifted_images_are_marked_not_attached(unreal):
    value = [{"mimeType": "image/png", "data": PNG} for _ in range(5)]
    unreal["client"] = FakeUnreal({"call_tool": _text({"returnValue": value})})
    out = em.link_mcp_call("x")
    assert len(out["images"]) == 3
    assert [v["attached"] for v in out["data"]["result"]] == [True, True, True, False, False]


def test_a_large_result_is_capped_with_totals(unreal):
    actors = [{"refPath": f"/Game/Map.Map:PersistentLevel.Actor_{i}", "label": "x" * 50} for i in range(3000)]
    unreal["client"] = FakeUnreal({"call_tool": _text({"returnValue": {"actors": actors, "note": "y" * 90000}})})
    data = em.link_mcp_call("find_actors", "SceneTools", {})["data"]
    assert data["truncated"] is True and data["total"] == {"result.actors": 3000}
    assert len(json.dumps(data)) <= em.RESULT_LIMIT + 200
    assert data["result"]["actors"][0]["refPath"].endswith("Actor_0")
    assert "more characters" in data["result"]["note"]


def test_results_are_scrubbed_keys_included_but_game_paths_kept(unreal):
    value = {"/Users/me/Proj/Saved/a.png": "D:\\Proj\\Content\\b.uasset", "asset": "/Game/Mixar/Tree"}
    unreal["client"] = FakeUnreal({"call_tool": _text({"returnValue": value})})
    result = em.link_mcp_call("x")["data"]["result"]
    assert result == {"<local path>": "<local path>", "asset": "/Game/Mixar/Tree"}


def test_a_timed_out_call_may_have_completed(unreal):
    unreal["client"] = FakeUnreal({"call_tool": el._unanswered(TimeoutError("timed out"))})
    assert em.link_mcp_call("x") == {"success": False, "error": em.CALL_TIMED_OUT}


def test_godot_refuses_all_three(unreal):
    unreal["info"] = GODOT
    for out in (em.link_mcp_list_toolsets(), em.link_mcp_describe("SceneTools"), em.link_mcp_call("x")):
        assert out == {"success": False, "error": em.GODOT_REFUSAL}
    assert unreal["client"].calls == []


def test_no_engine_never_raises(monkeypatch):
    monkeypatch.setattr(el, "adapters", lambda engine=None: [])
    assert em.link_mcp_call("x") == {"success": False, "error": el.NO_ENGINE}


def test_status_flags_editor_toolsets_for_unreal_only(monkeypatch):
    status = {"content": [{"type": "text", "text": json.dumps({"tools": ["status"]})}]}
    for info, flagged in ((UNREAL, True), (GODOT, False)):
        client = MagicMock()
        client.call.return_value = status
        monkeypatch.setattr(el, "adapters", lambda engine=None, i=info: [i])
        monkeypatch.setattr(el, "_connect", lambda engine, i=info, c=client: (i, c))
        data = el.link_status.__wrapped__()["data"]
        assert data.get("editor_toolsets", False) is flagged
        assert "assets" in data["tools"]


# ---------------------------------------------------------------------------
# Prefetch: the backend's script runs the call on a worker thread
# ---------------------------------------------------------------------------

def _backend_script(module, fn, kwargs):
    # modules/agent/tools/domains/engine.py:_link with helper=<module>, verbatim in shape.
    encoded = json.dumps(kwargs)
    return ("import json\n"
            f"from mixar.modules.space_mixie_chat.core.{module} import {fn}\n"
            f"result = {{'engine_link': {fn}(**json.loads({encoded!r}))}}\n"
            "print('\\n__RESULT__' + json.dumps(result))\n")


def test_prefetch_parses_both_modules_and_checks_the_function_module():
    from mixar.modules.space_mixie_chat.core import engine_prefetch as ep
    kwargs = {"tool_name": "find_actors", "toolset_name": "SceneTools", "arguments": {"tag": ""}, "timeout": 30}
    assert ep.parse(_backend_script("engine_mcp", "link_mcp_call", kwargs)) == ("link_mcp_call", kwargs)
    assert ep.parse(_backend_script("engine_mcp", "link_mcp_list_toolsets", {})) == ("link_mcp_list_toolsets", {})
    assert ep.parse(_backend_script("engine_mcp", "link_mcp_describe", {"toolset_name": "A"}))[0] == "link_mcp_describe"
    assert ep.parse(_backend_script("engine_link", "link_status", {})) == ("link_status", {})
    assert ep.parse(_backend_script("engine_link", "link_mcp_call", kwargs)) is None  # wrong module
    assert ep.parse(_backend_script("engine_mcp", "link_status", {})) is None
    assert ep.parse(_backend_script("engine_other", "link_mcp_call", kwargs)) is None


@pytest.mark.parametrize("tool, fn, kwargs", [
    ("engine_list_toolsets", "link_mcp_list_toolsets", {}),
    ("engine_describe_toolset", "link_mcp_describe", {"toolset_name": "SceneTools"}),
    ("engine_call_tool", "link_mcp_call", {"tool_name": "x", "timeout": 5}),
])
def test_the_backend_tool_names_route_to_the_engine_worker(unreal, tool, fn, kwargs):
    from mixar.modules.space_mixie_chat.core import engine_prefetch as ep
    from mixar.modules.space_mixie_chat.core import script_prefetch as sp
    handle = sp.maybe_start_prefetch(_backend_script("engine_mcp", fn, kwargs), tool)
    assert isinstance(handle, ep.EngineCallPrefetch) and handle.fn == fn
    budget = kwargs.get("timeout") or ep.DEFAULT_TIMEOUT_S[fn]
    assert budget == (5 if fn == "link_mcp_call" else 30.0)
    deadline = time.time() + 10
    while handle.state() != "ready" and time.time() < deadline:
        time.sleep(0.02)
    assert el.take_prefetched(handle.key) is not None


def test_the_worker_answer_is_reused_by_the_script(unreal):
    from mixar.modules.space_mixie_chat.core import engine_prefetch as ep
    unreal["client"] = FakeUnreal({"call_tool": _text({"returnValue": {"ok": 1}})})
    script = _backend_script("engine_mcp", "link_mcp_call",
                             {"tool_name": "get_current_level", "toolset_name": "SceneTools", "timeout": 20})
    handle = ep.maybe_start(script)
    deadline = time.time() + 10
    while handle.state() != "ready" and time.time() < deadline:
        time.sleep(0.02)
    assert handle.state() == "ready"
    assert len(unreal["client"].calls) == 1 and unreal["client"].calls[0][2] == 20.0
    scope = {}
    exec(compile(script.replace("print(", "_ = ("), "<engine script>", "exec"), scope)
    assert len(unreal["client"].calls) == 1  # the script took the stored answer
    assert scope["result"]["engine_link"] == {"success": True, "data": {"result": {"ok": 1}}}


def test_a_full_size_capture_is_fitted_for_the_model():
    """Epic's CaptureViewport answers the viewport at full size (2545x1910,
    ~6 MB of base64 live); the agent gets it at most MAX_IMAGE_SIDE long."""
    import base64
    import io
    import random

    from PIL import Image

    from mixar.modules.space_mixie_chat.core import engine_mcp

    rng = random.Random(7)
    big = Image.frombytes("RGB", (2545, 1910), bytes(rng.getrandbits(8) for _ in range(2545 * 1910 * 3)))
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode()
    fitted = engine_mcp.fit_image(data, "image/png")
    with Image.open(io.BytesIO(base64.b64decode(fitted["data"]))) as out:
        assert max(out.size) == engine_mcp.MAX_IMAGE_SIDE
    assert len(base64.b64decode(fitted["data"])) <= engine_mcp.MAX_IMAGE_BYTES
    small = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(small, format="PNG")
    tiny = base64.b64encode(small.getvalue()).decode()
    assert engine_mcp.fit_image(tiny, "image/png") == {"data": tiny, "mime": "image/png"}
    assert engine_mcp.fit_image("not base64 at all", "image/png")["data"] == "not base64 at all"


def test_a_full_tool_name_is_split_the_way_call_tool_takes_it():
    """describe_toolset names tools in full; Unreal's call_tool refuses a full
    name ("Tool '…' not found", live 5.8.3) and wants the toolset apart."""
    from mixar.modules.space_mixie_chat.core.engine_mcp import split_tool_name

    scene = "editor_toolset.toolsets.scene.SceneTools"
    assert split_tool_name(f"{scene}.find_actors") == (scene, "find_actors")
    assert split_tool_name(f"{scene}.find_actors", scene) == (scene, "find_actors")
    assert split_tool_name("find_actors", scene) == (scene, "find_actors")
    assert split_tool_name("CaptureViewport", "EditorToolset.EditorAppToolset") == \
        ("EditorToolset.EditorAppToolset", "CaptureViewport")
    assert split_tool_name("list_toolsets") == ("", "list_toolsets")  # a top-level tool
