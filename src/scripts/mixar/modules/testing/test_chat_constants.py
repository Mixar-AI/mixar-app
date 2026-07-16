# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.constants module.

Tests enum definitions and configuration values.
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

import unittest


class TestSessionStateEnum(unittest.TestCase):
    """Tests for SessionState enum."""

    def test_state_count(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.assertEqual(len(SessionState), 6)

    def test_unique_values(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        values = [s.value for s in SessionState]
        self.assertEqual(len(values), len(set(values)))

    def test_all_states_exist(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        expected = {"offline", "connecting", "idle", "busy", "modifying", "awaiting_input"}
        actual = {s.value for s in SessionState}
        self.assertEqual(actual, expected)


class TestJSONRPCMethod(unittest.TestCase):
    """Tests for JSONRPCMethod constants."""

    def test_client_methods(self):
        from mixar.modules.space_mixie_chat.constants import JSONRPCMethod
        self.assertEqual(JSONRPCMethod.SYSTEM_HANDSHAKE, "system.handshake")
        self.assertEqual(JSONRPCMethod.SYSTEM_PING, "system.ping")

    def test_server_methods(self):
        from mixar.modules.space_mixie_chat.constants import JSONRPCMethod
        self.assertEqual(JSONRPCMethod.BLENDER_EXECUTE_SCRIPT, "blender.execute_script")
        self.assertEqual(JSONRPCMethod.AGENT_TOOL_START, "agent.tool_start")
        self.assertEqual(JSONRPCMethod.AGENT_TOOL_EXECUTING, "agent.tool_executing")
        self.assertEqual(JSONRPCMethod.AGENT_TOOL_END, "agent.tool_end")


class TestJSONRPCErrorCode(unittest.TestCase):
    """Tests for JSONRPCErrorCode constants."""

    def test_standard_codes(self):
        from mixar.modules.space_mixie_chat.constants import JSONRPCErrorCode
        self.assertEqual(JSONRPCErrorCode.PARSE_ERROR, -32700)
        self.assertEqual(JSONRPCErrorCode.INVALID_REQUEST, -32600)
        self.assertEqual(JSONRPCErrorCode.METHOD_NOT_FOUND, -32601)
        self.assertEqual(JSONRPCErrorCode.INVALID_PARAMS, -32602)
        self.assertEqual(JSONRPCErrorCode.INTERNAL_ERROR, -32603)

    def test_custom_codes(self):
        from mixar.modules.space_mixie_chat.constants import JSONRPCErrorCode
        self.assertEqual(JSONRPCErrorCode.SERVER_ERROR, -32000)
        self.assertEqual(JSONRPCErrorCode.NOT_AUTHENTICATED, -32004)
        self.assertEqual(JSONRPCErrorCode.BLENDER_ERROR, -32006)


class TestStreamingConstants(unittest.TestCase):
    """Tests for streaming configuration values."""

    def test_streaming_batch_limit(self):
        from mixar.modules.space_mixie_chat.constants import STREAMING_BATCH_LIMIT
        self.assertEqual(STREAMING_BATCH_LIMIT, 8)

    def test_timer_interval(self):
        from mixar.modules.space_mixie_chat.constants import TIMER_INTERVAL
        self.assertAlmostEqual(TIMER_INTERVAL, 1 / 60, places=4)

    def test_script_timeout_threshold(self):
        from mixar.modules.space_mixie_chat.constants import SCRIPT_TIMEOUT_THRESHOLD
        self.assertEqual(SCRIPT_TIMEOUT_THRESHOLD, 30.0)


class TestImageConstants(unittest.TestCase):
    """Tests for image attachment configuration."""

    def test_size_limits(self):
        from mixar.modules.space_mixie_chat.constants import (
            MAX_IMAGE_SIZE_MB, MAX_IMAGE_SIZE_BYTES,
            MAX_IMAGE_DIMENSION, MAX_ATTACHMENTS_PER_MESSAGE,
        )
        self.assertEqual(MAX_IMAGE_SIZE_MB, 10)
        self.assertEqual(MAX_IMAGE_SIZE_BYTES, 10 * 1024 * 1024)
        self.assertEqual(MAX_IMAGE_DIMENSION, 16384)
        self.assertEqual(MAX_ATTACHMENTS_PER_MESSAGE, 5)

    def test_supported_formats(self):
        from mixar.modules.space_mixie_chat.constants import SUPPORTED_IMAGE_FORMATS
        self.assertIn('.png', SUPPORTED_IMAGE_FORMATS)
        self.assertIn('.jpg', SUPPORTED_IMAGE_FORMATS)
        self.assertIn('.jpeg', SUPPORTED_IMAGE_FORMATS)
        self.assertIn('.bmp', SUPPORTED_IMAGE_FORMATS)
        self.assertNotIn('.gif', SUPPORTED_IMAGE_FORMATS)
        self.assertNotIn('.svg', SUPPORTED_IMAGE_FORMATS)


class TestWebSocketConstants(unittest.TestCase):
    """Tests for WebSocket configuration constants."""

    def test_close_code(self):
        from mixar.modules.space_mixie_chat.constants import WS_CLOSE_AUTH_FAILED
        self.assertEqual(WS_CLOSE_AUTH_FAILED, 4001)

    def test_default_config(self):
        from mixar.modules.space_mixie_chat.constants import (
            DEFAULT_WS_URL_TEMPLATE,
            DEFAULT_RECONNECT_DELAY,
            DEFAULT_MAX_RECONNECT_DELAY,
            DEFAULT_PING_INTERVAL,
        )
        self.assertEqual(DEFAULT_WS_URL_TEMPLATE, "/api/agent/ws")
        self.assertGreater(DEFAULT_RECONNECT_DELAY, 0)
        self.assertGreater(DEFAULT_MAX_RECONNECT_DELAY, DEFAULT_RECONNECT_DELAY)
        self.assertGreater(DEFAULT_PING_INTERVAL, 0)

    def test_agent_chat_endpoint(self):
        from mixar.modules.space_mixie_chat.constants import AGENT_CHAT_ENDPOINT
        self.assertIn("/agent/chat", AGENT_CHAT_ENDPOINT)

    def test_agent_input_endpoint(self):
        from mixar.modules.space_mixie_chat.constants import AGENT_INPUT_ENDPOINT
        self.assertIn("/agent/input", AGENT_INPUT_ENDPOINT)

    def test_sse_read_timeout(self):
        # Must comfortably exceed the backend's ~15s SSE keepalive cadence
        # (so a healthy-but-quiet stream never trips it) while staying far
        # below the old 630s that left a dead mid-turn stream undetected
        # for 10+ minutes.
        from mixar.modules.space_mixie_chat.constants import SSE_READ_TIMEOUT
        self.assertEqual(SSE_READ_TIMEOUT, 75.0)


class TestUIConstants(unittest.TestCase):
    """Tests for UI configuration constants."""

    def test_chat_placeholders(self):
        from mixar.modules.space_mixie_chat.constants import (
            CHAT_PLACEHOLDER_TEXT,
            CHAT_INPUT_PLACEHOLDER,
        )
        self.assertIsInstance(CHAT_PLACEHOLDER_TEXT, str)
        self.assertIsInstance(CHAT_INPUT_PLACEHOLDER, str)
        self.assertTrue(len(CHAT_PLACEHOLDER_TEXT) > 0)
        self.assertTrue(len(CHAT_INPUT_PLACEHOLDER) > 0)

    def test_chat_input_limits(self):
        from mixar.modules.space_mixie_chat.constants import (
            CHAT_INPUT_DEFAULT,
            CHAT_INPUT_MAXLEN,
        )
        self.assertEqual(CHAT_INPUT_DEFAULT, "")
        self.assertEqual(CHAT_INPUT_MAXLEN, 2048)

    def test_max_message_length(self):
        from mixar.modules.space_mixie_chat.constants import MAX_MESSAGE_LENGTH
        self.assertEqual(MAX_MESSAGE_LENGTH, 100000)


if __name__ == "__main__":
    unittest.main()
