# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for common.websocket.protocol module.

Tests WebSocket message serialization, deserialization, and
the SafeJSONEncoder for Blender-safe encoding.
"""

# Install bpy mock before any mixar imports
import sys, os
_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
try:
    import bpy
except ImportError:
    import importlib.util
    _mock_spec = importlib.util.spec_from_file_location(
        "mock_bpy", os.path.join(_test_dir, "mock_bpy.py"))
    _mock_mod = importlib.util.module_from_spec(_mock_spec)
    _mock_spec.loader.exec_module(_mock_mod)

import json
import time
import unittest


class TestSafeJSONEncoder(unittest.TestCase):
    """Tests for SafeJSONEncoder."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.common.websocket.protocol import SafeJSONEncoder
        cls.encoder_cls = SafeJSONEncoder

    def _encode(self, obj):
        return json.dumps(obj, cls=self.encoder_cls)

    def test_normal_types_pass_through(self):
        data = {"key": "value", "num": 42, "arr": [1, 2, 3], "flag": True}
        result = json.loads(self._encode(data))
        self.assertEqual(result, data)

    def test_bpy_like_object_with_name(self):
        class FakeBlenderObj:
            bl_rna = True
            name = "Cube"
        result = self._encode({"obj": FakeBlenderObj()})
        parsed = json.loads(result)
        self.assertIn("FakeBlenderObj", parsed["obj"])
        self.assertIn("Cube", parsed["obj"])

    def test_bpy_like_object_without_name(self):
        class FakeBlenderObj:
            bl_rna = True
        result = self._encode({"obj": FakeBlenderObj()})
        parsed = json.loads(result)
        self.assertIn("FakeBlenderObj", parsed["obj"])

    def test_non_serializable_falls_back_to_str(self):
        class Custom:
            def __str__(self):
                return "custom_string"
        result = self._encode({"obj": Custom()})
        parsed = json.loads(result)
        self.assertEqual(parsed["obj"], "custom_string")

    def test_set_is_converted(self):
        result = self._encode({"s": {1, 2, 3}})
        parsed = json.loads(result)
        self.assertIsInstance(parsed["s"], str)


class TestMessageType(unittest.TestCase):
    """Tests for MessageType enum."""

    def test_message_types_exist(self):
        from mixar.modules.common.websocket.protocol import MessageType
        self.assertEqual(MessageType.CONNECTED.value, "connection_established")
        self.assertEqual(MessageType.DISCONNECTED.value, "disconnected")
        self.assertEqual(MessageType.PING.value, "ping")
        self.assertEqual(MessageType.PONG.value, "pong")
        self.assertEqual(MessageType.ERROR.value, "error")


class TestMessage(unittest.TestCase):
    """Tests for Message dataclass."""

    def test_default_fields(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        msg = Message(type=MessageType.PING)
        self.assertEqual(msg.payload, {})
        self.assertEqual(msg.session_id, "")
        self.assertEqual(msg.instance_id, "")
        self.assertIsInstance(msg.timestamp, float)

    def test_custom_fields(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        msg = Message(
            type=MessageType.CONNECTED,
            payload={"version": "1.0"},
            session_id="sess-123",
            instance_id="inst-456",
        )
        self.assertEqual(msg.payload["version"], "1.0")
        self.assertEqual(msg.session_id, "sess-123")


class TestSerializeMessage(unittest.TestCase):
    """Tests for serialize_message()."""

    def test_basic_serialization(self):
        from mixar.modules.common.websocket.protocol import (
            Message, MessageType, serialize_message,
        )
        msg = Message(
            type=MessageType.PING,
            session_id="s1",
            instance_id="i1",
            payload={"hello": "world"},
        )
        result = serialize_message(msg)
        parsed = json.loads(result)
        self.assertEqual(parsed["action"], "ping")
        self.assertEqual(parsed["session_id"], "s1")
        self.assertEqual(parsed["blender_instance_id"], "i1")
        self.assertEqual(parsed["payload"]["hello"], "world")

    def test_serialization_uses_action_key(self):
        from mixar.modules.common.websocket.protocol import (
            Message, MessageType, serialize_message,
        )
        msg = Message(type=MessageType.CONNECTED)
        parsed = json.loads(serialize_message(msg))
        self.assertIn("action", parsed)
        self.assertEqual(parsed["action"], "connection_established")

    def test_serialization_handles_non_serializable_payload(self):
        from mixar.modules.common.websocket.protocol import (
            Message, MessageType, serialize_message,
        )

        class Unserializable:
            def __str__(self):
                return "fallback"

        msg = Message(
            type=MessageType.PING,
            payload={"obj": Unserializable()},
        )
        # Should not raise
        result = serialize_message(msg)
        parsed = json.loads(result)
        self.assertEqual(parsed["payload"]["obj"], "fallback")


class TestDeserializeMessage(unittest.TestCase):
    """Tests for deserialize_message()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.common.websocket.protocol import (
            deserialize_message, MessageType,
        )
        cls.deserialize = staticmethod(deserialize_message)
        cls.MessageType = MessageType

    def test_server_event_type(self):
        data = json.dumps({
            "event_type": "connection_established",
            "payload": {"msg": "hello"},
            "session_id": "s1",
            "blender_instance_id": "i1",
        })
        msg = self.deserialize(data)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.type, self.MessageType.CONNECTED)
        self.assertEqual(msg.payload["msg"], "hello")
        self.assertEqual(msg.session_id, "s1")
        self.assertEqual(msg.instance_id, "i1")

    def test_client_action_type(self):
        data = json.dumps({"action": "ping"})
        msg = self.deserialize(data)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.type, self.MessageType.PING)

    def test_bytes_input(self):
        data = json.dumps({"event_type": "pong"}).encode("utf-8")
        msg = self.deserialize(data)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.type, self.MessageType.PONG)

    def test_unknown_event_type_returns_none(self):
        data = json.dumps({"event_type": "unknown_custom_type"})
        msg = self.deserialize(data)
        self.assertIsNone(msg)

    def test_missing_event_type_returns_none(self):
        data = json.dumps({"payload": {}})
        msg = self.deserialize(data)
        self.assertIsNone(msg)

    def test_invalid_json_returns_none(self):
        msg = self.deserialize("not json")
        self.assertIsNone(msg)

    def test_empty_string_returns_none(self):
        msg = self.deserialize("")
        self.assertIsNone(msg)

    def test_custom_type_mapping(self):
        from mixar.modules.common.websocket.protocol import MessageType
        custom_mapping = {"my_event": MessageType.CONNECTED}
        data = json.dumps({"event_type": "my_event"})
        msg = self.deserialize(data, type_mapping=custom_mapping)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.type, MessageType.CONNECTED)

    def test_default_payload(self):
        data = json.dumps({"event_type": "error"})
        msg = self.deserialize(data)
        self.assertEqual(msg.payload, {})


class TestCreatePingMessage(unittest.TestCase):
    """Tests for create_ping_message()."""

    def test_creates_ping(self):
        from mixar.modules.common.websocket.protocol import (
            create_ping_message, MessageType,
        )
        msg = create_ping_message("inst-1")
        self.assertEqual(msg.type, MessageType.PING)
        self.assertEqual(msg.instance_id, "inst-1")
        self.assertEqual(msg.payload, {})


class TestRegisterMessageType(unittest.TestCase):
    """Tests for register_message_type()."""

    def test_register_custom_type(self):
        from mixar.modules.common.websocket.protocol import (
            register_message_type, MessageType, SERVER_EVENT_TYPES,
            deserialize_message,
        )
        register_message_type("test_custom_event", MessageType.CONNECTED)
        self.assertEqual(SERVER_EVENT_TYPES["test_custom_event"], MessageType.CONNECTED)

        # Should now deserialize
        data = json.dumps({"event_type": "test_custom_event"})
        msg = deserialize_message(data)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.type, MessageType.CONNECTED)

        # Cleanup
        del SERVER_EVENT_TYPES["test_custom_event"]


if __name__ == "__main__":
    unittest.main()
