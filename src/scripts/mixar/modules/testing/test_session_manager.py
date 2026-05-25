# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.core.session module.

Tests SessionManager singleton, state transitions, and status messages.
Uses mocks for bpy-dependent properties.
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


class TestSessionState(unittest.TestCase):
    """Tests for SessionState enum values."""

    def test_all_states_exist(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        expected = {"offline", "connecting", "idle", "busy", "modifying", "awaiting_input"}
        actual = {s.value for s in SessionState}
        self.assertEqual(actual, expected)

    def test_state_labels_complete(self):
        from mixar.modules.space_mixie_chat.constants import SessionState, STATE_LABELS
        for state in SessionState:
            self.assertIn(state, STATE_LABELS, f"Missing label for {state}")


class TestSessionManagerSingleton(unittest.TestCase):
    """Tests for SessionManager singleton pattern."""

    def setUp(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()
        self.mgr = SessionManager()

    def tearDown(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()

    def test_singleton_same_instance(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        mgr2 = SessionManager()
        self.assertIs(self.mgr, mgr2)

    def test_initial_state_is_offline(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.assertEqual(self.mgr.state, SessionState.OFFLINE)

    def test_initial_properties(self):
        self.assertFalse(self.mgr.is_connected)
        self.assertIsNone(self.mgr.last_error)
        self.assertEqual(self.mgr.user_request, "")

    def test_get_session_manager_helper(self):
        from mixar.modules.space_mixie_chat.core.session import get_session_manager
        mgr = get_session_manager()
        self.assertIs(mgr, self.mgr)


class TestSessionManagerStateTransitions(unittest.TestCase):
    """Tests for state transitions."""

    def setUp(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()
        self.mgr = SessionManager()

    def tearDown(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()

    def test_set_state(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.mgr.set_state(SessionState.BUSY)
        self.assertEqual(self.mgr.state, SessionState.BUSY)

    def test_set_connected(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.mgr.set_connected()
        self.assertEqual(self.mgr.state, SessionState.IDLE)
        self.assertTrue(self.mgr.is_connected)
        self.assertIsNone(self.mgr.last_error)

    def test_set_disconnected(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.mgr.set_connected()
        self.mgr.set_disconnected("server shutdown")
        self.assertEqual(self.mgr.state, SessionState.OFFLINE)
        self.assertFalse(self.mgr.is_connected)
        self.assertEqual(self.mgr.last_error, "server shutdown")

    def test_set_disconnected_no_reason(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.mgr.set_disconnected()
        self.assertEqual(self.mgr.state, SessionState.OFFLINE)
        self.assertIsNone(self.mgr.last_error)

    def test_set_error(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.mgr.set_error("timeout")
        self.assertEqual(self.mgr.state, SessionState.OFFLINE)
        self.assertEqual(self.mgr.last_error, "timeout")
        self.assertFalse(self.mgr.is_connected)

    def test_is_connected_states(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        # OFFLINE and CONNECTING are not connected
        for state in [SessionState.OFFLINE, SessionState.CONNECTING]:
            self.mgr.set_state(state)
            self.assertFalse(self.mgr.is_connected, f"Should not be connected in {state}")

        # IDLE, BUSY, MODIFYING, AWAITING_INPUT are connected
        for state in [SessionState.IDLE, SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT]:
            self.mgr.set_state(state)
            self.assertTrue(self.mgr.is_connected, f"Should be connected in {state}")

    def test_modifying_state(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.mgr.set_state(SessionState.MODIFYING)
        self.assertEqual(self.mgr.state, SessionState.MODIFYING)
        self.assertTrue(self.mgr.is_connected)

    def test_awaiting_input_state(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        self.mgr.set_state(SessionState.AWAITING_INPUT)
        self.assertEqual(self.mgr.state, SessionState.AWAITING_INPUT)
        self.assertTrue(self.mgr.is_connected)


class TestSessionManagerClearStreaming(unittest.TestCase):
    """Tests that clear_streaming is a safe no-op."""

    def setUp(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()
        self.mgr = SessionManager()

    def tearDown(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()

    def test_clear_streaming_is_noop(self):
        self.mgr.clear_streaming()


class TestSessionManagerStatusMessage(unittest.TestCase):
    """Tests for get_status_message()."""

    def setUp(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()
        self.mgr = SessionManager()

    def tearDown(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.reset()

    def test_offline_status(self):
        self.assertEqual(self.mgr.get_status_message(), "Not Connected")

    def test_idle_status(self):
        self.mgr.set_connected()
        self.assertEqual(self.mgr.get_status_message(), "Connected")

    def test_error_status(self):
        self.mgr.set_error("fail")
        # Error sets state to OFFLINE
        self.assertEqual(self.mgr.get_status_message(), "Not Connected")

    def test_all_states_have_labels(self):
        from mixar.modules.space_mixie_chat.constants import SessionState
        for state in SessionState:
            self.mgr.set_state(state)
            msg = self.mgr.get_status_message()
            self.assertIsInstance(msg, str)
            self.assertTrue(len(msg) > 0, f"Empty label for {state}")


class TestSessionManagerReset(unittest.TestCase):
    """Tests for reset functionality."""

    def test_reset_reinitializes(self):
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        from mixar.modules.space_mixie_chat.constants import SessionState
        mgr = SessionManager()
        mgr.set_state(SessionState.BUSY)
        mgr.set_error("test error")
        SessionManager.reset()
        self.assertEqual(mgr.state, SessionState.OFFLINE)
        self.assertIsNone(mgr.last_error)


if __name__ == "__main__":
    unittest.main()
