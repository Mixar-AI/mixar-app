# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The optional QA adapter exposes semantic input only on the chosen QA app."""

import base64
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

_PATH = Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/core/qa_adapter.py"
_SPEC = importlib.util.spec_from_file_location("mixar_qa_adapter_tests", _PATH)
qa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qa)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


def adapter(health=None):
    return qa.QAAdapter(4777, lambda: health if health is not None else {"qa_enabled": True, "qa_port": 4777})


@pytest.mark.parametrize("health", [{}, {"qa_enabled": False, "qa_port": 4777},
                                   {"qa_enabled": True, "qa_port": 4778}])
def test_non_qa_or_other_qa_instance_cannot_expose_or_run_tools(health):
    instance = adapter(health)
    instance._send = Mock()
    with pytest.raises(ValueError, match="selected Mixar desktop"):
        instance.tools()
    with pytest.raises(ValueError, match="selected Mixar desktop"):
        instance.call("mixar_qa_click", {"target": {"text": "File"}}, str(uuid4()))
    instance._send.assert_not_called()


def test_exact_tool_surface_contains_no_code_process_or_file_commands():
    names = {tool["name"] for tool in adapter().tools()}
    assert names == {"mixar_qa_" + command for command in (
        "status", "find", "dump", "click", "choose", "set_text", "type", "press", "drag", "snap")}
    for forbidden in ("eval", "raw", "quit", "start", "stop", "drop_file", "chat_send", "reset_state"):
        assert not qa.QAAdapter.handles("mixar_qa_" + forbidden)
        with pytest.raises(ValueError, match="Unknown"):
            adapter().call("mixar_qa_" + forbidden, {"code": "print(1)"}, str(uuid4()))


@pytest.mark.parametrize(("name", "arguments"), [
    ("mixar_qa_click", {"target": {"op": "wm.save_as_mainfile", "code": "bad"}}),
    ("mixar_qa_click", {"target": {"x": 1, "y": 2}}),
    ("mixar_qa_snap", {"path": "/tmp/user-controlled.png"}),
    ("mixar_qa_status", {"cmd": "eval"}),
    ("mixar_qa_press", {"key": "EXEC"}),
    ("mixar_qa_drag", {"from": {"surface": "a"}, "to": {"surface": "b"}, "steps": 100000}),
    ("mixar_qa_find", {"query": {}, "limit": True}),
    ("mixar_qa_type", {"text": "A" * 8193}),
])
def test_unreviewed_fields_keys_coordinates_and_unbounded_values_are_refused(name, arguments):
    instance = adapter()
    instance._send = Mock()
    with pytest.raises(ValueError):
        instance.call(name, arguments, str(uuid4()))
    instance._send.assert_not_called()


def test_health_is_rechecked_after_successful_discovery():
    health = {"qa_enabled": True, "qa_port": 4777}
    instance = adapter(health)
    assert instance.tools()
    health["qa_enabled"] = False
    instance._send = Mock()
    with pytest.raises(ValueError):
        instance.call("mixar_qa_status", {}, str(uuid4()))
    instance._send.assert_not_called()


@pytest.mark.parametrize(("name", "arguments", "command", "expected"), [
    ("find", {"query": {"prop": "mixie_chat_input"}, "limit": 8}, "find", {"prop": "mixie_chat_input", "limit": 8}),
    ("click", {"target": {"text": "File", "but_type": "Pulldown"}}, "click", {"text": "File", "but_type": "Pulldown", "double": False}),
    ("set_text", {"target": {"prop": "name"}, "text": "Chair"}, "set_text", {"widget": {"prop": "name"}, "text": "Chair"}),
    ("choose", {"target": {"prop": "p_aspect_ratio"}, "item": "16:9"}, "choose", {"widget": {"prop": "p_aspect_ratio"}, "item": "16:9"}),
])
def test_semantic_arguments_map_to_documented_harness_wire(name, arguments, command, expected):
    instance = adapter()
    instance._send = Mock(return_value={"ok": True, "result": {"total": 1}})
    result = instance.call("mixar_qa_" + name, arguments, str(uuid4()))
    instance._send.assert_called_once_with(command, expected)
    assert result["isError"] is False
    assert result["structuredContent"]["usage"]["credits_charged"] == 0
    assert "normal generation credits" in result["content"][0]["text"]


def test_snapshot_reads_only_its_own_temporary_file_and_returns_native_image():
    instance = adapter()
    capture = {}

    def send(command, arguments):
        assert command == "snap"
        path = Path(arguments["path"])
        capture["path"] = path
        path.write_bytes(PNG)
        return {"ok": True, "result": {"path": "/Users/private/do-not-read.png", "window": 7}}

    instance._send = send
    result = instance.call("mixar_qa_snap", {"area": "VIEW_3D"}, str(uuid4()))
    assert result["isError"] is False
    image = next(item for item in result["content"] if item["type"] == "image")
    assert image["mimeType"] == "image/png" and base64.b64decode(image["data"]) == PNG
    assert "path" not in result["structuredContent"]["result"]
    assert not capture["path"].exists()
    assert "/Users/private" not in json.dumps(result)


def test_snapshot_does_not_follow_a_server_supplied_symlink(tmp_path):
    original = tmp_path / "secret.png"
    original.write_bytes(PNG)
    instance = adapter()

    def send(command, arguments):
        Path(arguments["path"]).symlink_to(original)
        return {"ok": True, "result": {"path": str(original)}}

    instance._send = send
    result = instance.call("mixar_qa_snap", {}, str(uuid4()))
    assert result["isError"] is True
    assert all(item["type"] != "image" for item in result["content"])
    assert original.read_bytes() == PNG


def test_mutating_replay_does_not_click_twice_in_one_launcher_session():
    instance = adapter()
    instance._send = Mock(return_value={"ok": True, "result": True})
    call_id = str(uuid4())
    instance.call("mixar_qa_click", {"target": {"text": "File"}}, call_id)
    repeated = instance.call("mixar_qa_click", {"target": {"text": "File"}}, call_id)
    assert repeated["structuredContent"]["usage"]["replayed"] is True
    assert instance._send.call_count == 1
    with pytest.raises(ValueError, match="reused"):
        instance.call("mixar_qa_click", {"target": {"text": "Edit"}}, call_id)


def test_timeout_remains_uncertain_and_does_not_retry_on_recovery():
    instance = adapter()
    instance._send = Mock(side_effect=TimeoutError("local private detail"))
    call_id = str(uuid4())
    arguments = {"key": "RET"}
    first = instance.call("mixar_qa_press", arguments, call_id)
    second = instance.call("mixar_qa_press", arguments, call_id)
    assert first["isError"] and second["isError"]
    assert "private detail" not in str(first)
    assert instance._send.call_count == 1
