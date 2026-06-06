# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for common.api.request_queue module.

Tests thread-safe request/response queues and callback management.
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

import time
import unittest


class TestResponseStatus(unittest.TestCase):
    """Tests for ResponseStatus enum."""

    def test_status_values(self):
        from mixar.modules.common.api.request_queue import ResponseStatus
        self.assertEqual(ResponseStatus.SUCCESS.value, "success")
        self.assertEqual(ResponseStatus.ERROR.value, "error")
        self.assertEqual(ResponseStatus.CANCELLED.value, "cancelled")
        self.assertEqual(ResponseStatus.TIMEOUT.value, "timeout")


class TestAsyncResponse(unittest.TestCase):
    """Tests for AsyncResponse dataclass."""

    def test_default_fields(self):
        from mixar.modules.common.api.request_queue import AsyncResponse, ResponseStatus
        resp = AsyncResponse(request_id="req-1", status=ResponseStatus.SUCCESS)
        self.assertEqual(resp.request_id, "req-1")
        self.assertIsNone(resp.result)
        self.assertIsNone(resp.error)
        self.assertIsNone(resp.callback_id)
        self.assertEqual(resp.metadata, {})
        self.assertEqual(resp.elapsed_ms, 0)

    def test_error_response(self):
        from mixar.modules.common.api.request_queue import AsyncResponse, ResponseStatus
        err = ValueError("test")
        resp = AsyncResponse(
            request_id="req-2",
            status=ResponseStatus.ERROR,
            error=err,
            elapsed_ms=150,
        )
        self.assertEqual(resp.status, ResponseStatus.ERROR)
        self.assertIs(resp.error, err)
        self.assertEqual(resp.elapsed_ms, 150)


class TestRequestQueues(unittest.TestCase):
    """Tests for RequestQueues singleton."""

    def setUp(self):
        from mixar.modules.common.api.request_queue import RequestQueues
        RequestQueues.reset()
        self.queues = RequestQueues()

    def tearDown(self):
        from mixar.modules.common.api.request_queue import RequestQueues
        RequestQueues.reset()

    def test_singleton(self):
        from mixar.modules.common.api.request_queue import RequestQueues
        q1 = RequestQueues()
        q2 = RequestQueues()
        self.assertIs(q1, q2)

    def test_register_callback(self):
        callback_id = self.queues.register_callback(
            on_success=lambda r: None,
            timeout=30.0,
        )
        self.assertIsInstance(callback_id, str)
        self.assertEqual(self.queues.callback_count(), 1)

    def test_get_callback_removes_it(self):
        callback_id = self.queues.register_callback(on_success=lambda r: None)
        cb = self.queues.get_callback(callback_id)
        self.assertIsNotNone(cb)
        self.assertEqual(cb.callback_id, callback_id)
        # Should be removed now
        self.assertIsNone(self.queues.get_callback(callback_id))

    def test_cancel_callback(self):
        callback_id = self.queues.register_callback()
        self.assertTrue(self.queues.cancel_callback(callback_id))
        self.assertFalse(self.queues.cancel_callback(callback_id))  # already removed

    def test_put_and_get_response(self):
        from mixar.modules.common.api.request_queue import AsyncResponse, ResponseStatus
        resp = AsyncResponse(request_id="r1", status=ResponseStatus.SUCCESS, result="data")
        self.queues.put_response(resp)
        self.assertEqual(self.queues.response_count(), 1)
        got = self.queues.get_response()
        self.assertIsNotNone(got)
        self.assertEqual(got.request_id, "r1")
        self.assertEqual(got.result, "data")

    def test_get_response_empty_returns_none(self):
        self.assertIsNone(self.queues.get_response())

    def test_get_responses_batch(self):
        from mixar.modules.common.api.request_queue import AsyncResponse, ResponseStatus
        for i in range(5):
            self.queues.put_response(
                AsyncResponse(request_id=f"r{i}", status=ResponseStatus.SUCCESS)
            )
        batch = self.queues.get_responses(max_count=3)
        self.assertEqual(len(batch), 3)
        # 2 remaining
        self.assertEqual(self.queues.response_count(), 2)

    def test_get_responses_less_than_max(self):
        from mixar.modules.common.api.request_queue import AsyncResponse, ResponseStatus
        self.queues.put_response(
            AsyncResponse(request_id="r1", status=ResponseStatus.SUCCESS)
        )
        batch = self.queues.get_responses(max_count=10)
        self.assertEqual(len(batch), 1)

    def test_cleanup_expired_callbacks(self):
        # Register a callback with a very short timeout
        callback_id = self.queues.register_callback(timeout=0.001)
        # Wait for it to expire
        time.sleep(0.01)
        expired = self.queues.cleanup_expired_callbacks()
        self.assertEqual(expired, 1)
        self.assertEqual(self.queues.callback_count(), 0)
        # Expired callback should be in expired dict
        self.assertEqual(self.queues.expired_callback_count(), 1)

    def test_cleanup_expired_callbacks_queues_timeout_response(self):
        self.queues.register_callback(timeout=0.001)
        time.sleep(0.01)
        self.queues.cleanup_expired_callbacks()
        resp = self.queues.get_response()
        from mixar.modules.common.api.request_queue import ResponseStatus
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status, ResponseStatus.TIMEOUT)

    def test_non_expired_callbacks_not_cleaned(self):
        self.queues.register_callback(timeout=300.0)
        expired = self.queues.cleanup_expired_callbacks()
        self.assertEqual(expired, 0)
        self.assertEqual(self.queues.callback_count(), 1)

    def test_callbacks_without_timeout_never_expire(self):
        self.queues.register_callback(timeout=0.0)
        expired = self.queues.cleanup_expired_callbacks()
        self.assertEqual(expired, 0)

    def test_cleanup_abandoned_callbacks(self):
        callback_id = self.queues.register_callback(timeout=0.001)
        time.sleep(0.01)
        self.queues.cleanup_expired_callbacks()
        # Now clean up abandoned (grace_multiplier=0 to trigger immediately)
        far_future = time.time() + 1000
        abandoned = self.queues.cleanup_abandoned_callbacks(
            current_time=far_future, grace_multiplier=0.0
        )
        self.assertEqual(abandoned, 1)

    def test_get_callback_from_expired(self):
        """Late responses should still find their callback in expired dict."""
        callback_id = self.queues.register_callback(
            on_success=lambda r: None,
            timeout=0.001,
        )
        time.sleep(0.01)
        self.queues.cleanup_expired_callbacks()
        # Callback moved to expired dict, should still be retrievable
        cb = self.queues.get_callback(callback_id)
        self.assertIsNotNone(cb)

    def test_clear(self):
        from mixar.modules.common.api.request_queue import AsyncResponse, ResponseStatus
        self.queues.register_callback()
        self.queues.put_response(
            AsyncResponse(request_id="r1", status=ResponseStatus.SUCCESS)
        )
        resp_cleared, cb_cleared = self.queues.clear()
        self.assertEqual(resp_cleared, 1)
        self.assertEqual(cb_cleared, 1)

    def test_callback_metadata(self):
        meta = {"module": "paint", "operation": "bake"}
        callback_id = self.queues.register_callback(metadata=meta)
        cb = self.queues.get_callback(callback_id)
        self.assertEqual(cb.metadata, meta)

    def test_get_request_queues_helper(self):
        from mixar.modules.common.api.request_queue import get_request_queues
        q = get_request_queues()
        self.assertIs(q, self.queues)


if __name__ == "__main__":
    unittest.main()
