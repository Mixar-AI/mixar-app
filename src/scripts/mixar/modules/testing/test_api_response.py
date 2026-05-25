# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for common.api.response module.

Tests the APIResponse dataclass and its factory methods.
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


class TestAPIResponse(unittest.TestCase):
    """Tests for APIResponse dataclass."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.common.api.response import APIResponse
        cls.APIResponse = APIResponse

    def test_from_success_defaults(self):
        resp = self.APIResponse.from_success(200)
        self.assertTrue(resp.success)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data)
        self.assertEqual(resp.message, "Success")
        self.assertEqual(resp.headers, {})

    def test_from_success_with_data(self):
        data = {"items": [1, 2, 3]}
        resp = self.APIResponse.from_success(201, data=data, message="Created")
        self.assertTrue(resp.success)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data, data)
        self.assertEqual(resp.message, "Created")

    def test_from_success_with_headers(self):
        headers = {"Content-Type": "application/json"}
        resp = self.APIResponse.from_success(200, headers=headers)
        self.assertEqual(resp.headers, headers)

    def test_from_error(self):
        resp = self.APIResponse.from_error(404, "Not found")
        self.assertFalse(resp.success)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.message, "Not found")
        self.assertIsNone(resp.data)

    def test_from_error_with_data(self):
        error_body = {"detail": "Resource ID 42 not found"}
        resp = self.APIResponse.from_error(404, "Not found", data=error_body)
        self.assertEqual(resp.data, error_body)

    def test_direct_construction(self):
        resp = self.APIResponse(
            success=True,
            status_code=200,
            data="raw",
            message="OK",
            headers={"X-Custom": "value"},
            raw=b"bytes",
        )
        self.assertEqual(resp.raw, b"bytes")
        self.assertEqual(resp.headers["X-Custom"], "value")

    def test_status_codes(self):
        for code in [200, 201, 204, 400, 401, 403, 404, 422, 429, 500, 502, 503]:
            resp = self.APIResponse.from_error(code, f"Error {code}")
            self.assertEqual(resp.status_code, code)


class TestAPIExceptions(unittest.TestCase):
    """Tests for custom API exception hierarchy."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.common.api import exceptions as exc
        cls.exc = exc

    def test_http_client_error_base(self):
        err = self.exc.HTTPClientError("test error", status_code=500, response_data={"key": "val"})
        self.assertEqual(str(err), "test error")
        self.assertEqual(err.status_code, 500)
        self.assertEqual(err.response_data, {"key": "val"})

    def test_connection_error_inherits(self):
        err = self.exc.ConnectionError("connection refused")
        self.assertIsInstance(err, self.exc.HTTPClientError)

    def test_timeout_error(self):
        err = self.exc.TimeoutError("request timed out", status_code=None)
        self.assertIsNone(err.status_code)

    def test_authentication_error(self):
        err = self.exc.AuthenticationError("invalid token", status_code=401)
        self.assertEqual(err.status_code, 401)

    def test_authorization_error(self):
        err = self.exc.AuthorizationError("forbidden", status_code=403)
        self.assertEqual(err.status_code, 403)

    def test_not_found_error(self):
        err = self.exc.NotFoundError("not found", status_code=404)
        self.assertIsInstance(err, self.exc.HTTPClientError)

    def test_validation_error(self):
        err = self.exc.ValidationError("bad request", status_code=400)
        self.assertEqual(err.message, "bad request")

    def test_server_error(self):
        err = self.exc.ServerError("internal server error", status_code=500)
        self.assertEqual(err.status_code, 500)

    def test_rate_limit_error_retry_after(self):
        err = self.exc.RateLimitError("slow down", retry_after=30.0, status_code=429)
        self.assertEqual(err.retry_after, 30.0)
        self.assertEqual(err.status_code, 429)

    def test_rate_limit_error_no_retry(self):
        err = self.exc.RateLimitError("slow down")
        self.assertIsNone(err.retry_after)

    def test_all_exceptions_are_catchable_as_base(self):
        for cls_name in [
            "ConnectionError", "TimeoutError", "AuthenticationError",
            "AuthorizationError", "NotFoundError", "ValidationError",
            "ServerError", "RateLimitError",
        ]:
            cls = getattr(self.exc, cls_name)
            with self.assertRaises(self.exc.HTTPClientError):
                raise cls("test")


class TestAPIConstants(unittest.TestCase):
    """Tests for API constants."""

    def test_api_version(self):
        from mixar.modules.common.api.constants import API_VERSION
        self.assertEqual(API_VERSION, "v1")

    def test_http_methods(self):
        from mixar.modules.common.api.constants import HTTPMethod
        self.assertEqual(HTTPMethod.GET.value, "GET")
        self.assertEqual(HTTPMethod.POST.value, "POST")
        self.assertEqual(HTTPMethod.PUT.value, "PUT")
        self.assertEqual(HTTPMethod.PATCH.value, "PATCH")
        self.assertEqual(HTTPMethod.DELETE.value, "DELETE")

    def test_api_modules(self):
        from mixar.modules.common.api.constants import APIModule
        self.assertEqual(APIModule.AGENT.value, "agent")
        self.assertEqual(APIModule.AUTHENTICATION.value, "auth")
        self.assertEqual(APIModule.IMAGEGEN.value, "image-generation")

    def test_content_types(self):
        from mixar.modules.common.api.constants import (
            CONTENT_TYPE_JSON, CONTENT_TYPE_FORM, CONTENT_TYPE_MULTIPART
        )
        self.assertEqual(CONTENT_TYPE_JSON, "application/json")
        self.assertIn("form", CONTENT_TYPE_FORM)
        self.assertIn("multipart", CONTENT_TYPE_MULTIPART)

    def test_timeout_defaults(self):
        from mixar.modules.common.api.constants import (
            DEFAULT_TIMEOUT, DEFAULT_RETRY_COUNT, DEFAULT_RETRY_DELAY,
            DEFAULT_RETRY_BACKOFF, MAX_RETRY_DELAY,
        )
        self.assertGreater(DEFAULT_TIMEOUT, 0)
        self.assertGreaterEqual(DEFAULT_RETRY_COUNT, 1)
        self.assertGreater(DEFAULT_RETRY_DELAY, 0)
        self.assertGreater(DEFAULT_RETRY_BACKOFF, 1)
        self.assertGreaterEqual(MAX_RETRY_DELAY, DEFAULT_RETRY_DELAY)


if __name__ == "__main__":
    unittest.main()
