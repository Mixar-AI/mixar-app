# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for common.websocket.message_queue module.

Tests thread-safe inbound/outbound message queues.
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
import unittest


class TestMessageQueues(unittest.TestCase):
    """Tests for MessageQueues singleton."""

    def setUp(self):
        from mixar.modules.common.websocket.message_queue import MessageQueues
        MessageQueues.reset()
        self.queues = MessageQueues()

    def tearDown(self):
        from mixar.modules.common.websocket.message_queue import MessageQueues
        MessageQueues.reset()

    def test_singleton(self):
        from mixar.modules.common.websocket.message_queue import MessageQueues
        q1 = MessageQueues()
        q2 = MessageQueues()
        self.assertIs(q1, q2)

    def test_send_serializes_message(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        msg = Message(
            type=MessageType.PING,
            payload={"key": "val"},
            instance_id="inst-1",
        )
        self.queues.send(msg)
        serialized = self.queues.get_outbound(timeout=0.1)
        self.assertIsNotNone(serialized)
        self.assertIsInstance(serialized, str)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["action"], "ping")
        self.assertEqual(parsed["payload"]["key"], "val")

    def test_receive_empty_returns_none(self):
        result = self.queues.receive()
        self.assertIsNone(result)

    def test_put_inbound_and_receive(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        msg = Message(type=MessageType.PONG, payload={"status": "ok"})
        self.queues.put_inbound(msg)
        result = self.queues.receive()
        self.assertIsNotNone(result)
        self.assertEqual(result.type, MessageType.PONG)
        self.assertEqual(result.payload["status"], "ok")

    def test_receive_blocking_timeout(self):
        import time
        start = time.perf_counter()
        result = self.queues.receive_blocking(timeout=0.1)
        elapsed = time.perf_counter() - start
        self.assertIsNone(result)
        self.assertGreaterEqual(elapsed, 0.05)  # Should have waited

    def test_get_outbound_timeout(self):
        result = self.queues.get_outbound(timeout=0.05)
        self.assertIsNone(result)

    def test_clear_inbound(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        for _ in range(3):
            self.queues.put_inbound(Message(type=MessageType.PONG))
        cleared = self.queues.clear_inbound()
        self.assertEqual(cleared, 3)
        self.assertEqual(self.queues.inbound_size(), 0)

    def test_clear_outbound(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        for _ in range(2):
            self.queues.send(Message(type=MessageType.PING))
        cleared = self.queues.clear_outbound()
        self.assertEqual(cleared, 2)
        self.assertEqual(self.queues.outbound_size(), 0)

    def test_clear_all(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        self.queues.put_inbound(Message(type=MessageType.PONG))
        self.queues.send(Message(type=MessageType.PING))
        inbound_cleared, outbound_cleared = self.queues.clear_all()
        self.assertEqual(inbound_cleared, 1)
        self.assertEqual(outbound_cleared, 1)

    def test_size_tracking(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        self.assertEqual(self.queues.inbound_size(), 0)
        self.assertEqual(self.queues.outbound_size(), 0)
        self.queues.put_inbound(Message(type=MessageType.PONG))
        self.queues.send(Message(type=MessageType.PING))
        self.assertEqual(self.queues.inbound_size(), 1)
        self.assertEqual(self.queues.outbound_size(), 1)

    def test_fifo_ordering(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        for i in range(5):
            self.queues.put_inbound(
                Message(type=MessageType.PONG, payload={"idx": i})
            )
        for i in range(5):
            msg = self.queues.receive()
            self.assertEqual(msg.payload["idx"], i)

    def test_get_message_queues_helper(self):
        from mixar.modules.common.websocket.message_queue import get_message_queues
        q = get_message_queues()
        self.assertIs(q, self.queues)

    def test_reset_clears_and_invalidates(self):
        from mixar.modules.common.websocket.protocol import Message, MessageType
        from mixar.modules.common.websocket.message_queue import MessageQueues
        self.queues.put_inbound(Message(type=MessageType.PONG))
        MessageQueues.reset()
        # New instance should be clean
        new_q = MessageQueues()
        self.assertEqual(new_q.inbound_size(), 0)


if __name__ == "__main__":
    unittest.main()
