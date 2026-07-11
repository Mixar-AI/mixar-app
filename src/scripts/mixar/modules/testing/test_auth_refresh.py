# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-Python regression tests for refresh-token rotation retries."""

import json
import inspect
import os
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# auth.py imports keyring on non-Windows, and importing the add-on package also
# expects Blender modules. Keep this test runnable in a regular Python process.
for _name in (
    "bpy",
    "bpy.types",
    "bpy.props",
    "bpy.utils",
    "bpy.app",
    "bpy.app.timers",
    "bpy.context",
    "bpy.data",
    "bpy.ops",
    "bpy.ops.mixar",
    "keyring",
):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.auth.core import auth
from mixar.modules.auth.core import sso


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class TestRefreshIdempotency(unittest.TestCase):
    def setUp(self):
        self.credentials = {
            "access": "old-access",
            "refresh": "old-refresh",
        }
        self.calls = []
        self.persisted_attempt = None
        self._originals = {
            "get_access_token": auth.get_access_token,
            "get_refresh_token": auth.get_refresh_token,
            "store_access_token": auth.store_access_token,
            "store_refresh_token": auth.store_refresh_token,
            "delete_access_token": auth.delete_access_token,
            "delete_refresh_token": auth.delete_refresh_token,
            "get_server_url": auth.get_server_url,
            "requests_post": auth.requests.post,
            "uuid4": auth.uuid.uuid4,
            "load_attempt": auth._load_persisted_refresh_attempt,
            "persist_attempt": auth._persist_refresh_attempt,
            "delete_attempt": auth._delete_persisted_refresh_attempt,
            "last_refresh": auth._last_refresh,
            "pending_refresh": auth._pending_refresh,
        }

        auth.get_access_token = lambda: self.credentials["access"]
        auth.get_refresh_token = lambda: self.credentials["refresh"]
        auth.store_access_token = self._store_access
        auth.store_refresh_token = self._store_refresh
        auth.delete_access_token = self._delete_access
        auth.delete_refresh_token = self._delete_refresh
        auth.get_server_url = lambda: "https://api.example.test"

        key_counter = iter(range(1, 100))
        auth.uuid.uuid4 = lambda: f"attempt-{next(key_counter)}"
        auth._load_persisted_refresh_attempt = self._load_attempt
        auth._persist_refresh_attempt = self._persist_attempt
        auth._delete_persisted_refresh_attempt = self._delete_attempt
        auth._last_refresh = None
        auth._pending_refresh = None
        self.addCleanup(self._restore)

    def _restore(self):
        auth.get_access_token = self._originals["get_access_token"]
        auth.get_refresh_token = self._originals["get_refresh_token"]
        auth.store_access_token = self._originals["store_access_token"]
        auth.store_refresh_token = self._originals["store_refresh_token"]
        auth.delete_access_token = self._originals["delete_access_token"]
        auth.delete_refresh_token = self._originals["delete_refresh_token"]
        auth.get_server_url = self._originals["get_server_url"]
        auth.requests.post = self._originals["requests_post"]
        auth.uuid.uuid4 = self._originals["uuid4"]
        auth._load_persisted_refresh_attempt = self._originals["load_attempt"]
        auth._persist_refresh_attempt = self._originals["persist_attempt"]
        auth._delete_persisted_refresh_attempt = self._originals["delete_attempt"]
        auth._last_refresh = self._originals["last_refresh"]
        auth._pending_refresh = self._originals["pending_refresh"]

    def _store_access(self, token):
        self.credentials["access"] = token
        return True

    def _store_refresh(self, token):
        self.credentials["refresh"] = token
        return True

    def _delete_access(self):
        self.credentials["access"] = ""
        return True

    def _delete_refresh(self):
        self.credentials["refresh"] = ""
        return True

    def _load_attempt(self):
        attempt = dict(self.persisted_attempt) if self.persisted_attempt else None
        return True, attempt

    def _persist_attempt(self, attempt):
        self.persisted_attempt = {
            "refresh_token_digest": attempt["refresh_token_digest"],
            "idempotency_key": attempt["idempotency_key"],
        }
        return True

    def _delete_attempt(self):
        self.persisted_attempt = None
        return True

    @staticmethod
    def _success(access="new-access", refresh="new-refresh"):
        return _Response(
            200,
            {"access_token": access, "refresh_token": refresh},
        )

    def _expire_cached_result(self):
        completed_at, credentials, result, window = auth._last_refresh
        auth._last_refresh = (
            completed_at - window - 1.0,
            credentials,
            result,
            window,
        )

    def test_concurrent_success_is_one_process_wide_request(self):
        barrier = threading.Barrier(8)
        call_lock = threading.Lock()

        def post(url, **kwargs):
            with call_lock:
                self.calls.append((url, kwargs))
            # Keep the leader inside the refresh lock long enough for the other
            # callers to queue behind the same logical attempt.
            time.sleep(0.05)
            return self._success()

        auth.requests.post = post
        results = []
        results_lock = threading.Lock()

        def worker():
            barrier.wait()
            result = auth.refresh_access_token()
            with results_lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result["token"] == "new-access" for result in results))
        self.assertEqual(
            self.credentials,
            {"access": "new-access", "refresh": "new-refresh"},
        )

    def test_timeout_then_process_restart_reuses_original_token_and_key(self):
        outcomes = [auth.requests.exceptions.Timeout(), self._success()]

        def post(url, **kwargs):
            self.calls.append((url, kwargs))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        auth.requests.post = post

        first = auth.refresh_access_token()
        coalesced = auth.refresh_access_token()
        self.assertFalse(first["success"])
        self.assertTrue(first["retryable"])
        self.assertIs(first, coalesced)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("old-refresh", json.dumps(self.persisted_attempt))

        # Simulate a new Python process: volatile cache/attempt state is gone,
        # while OS safe storage and the normal refresh credential survive.
        auth._last_refresh = None
        auth._pending_refresh = None
        retried = auth.refresh_access_token()

        self.assertTrue(retried["success"])
        self.assertEqual(len(self.calls), 2)
        first_kwargs = self.calls[0][1]
        retry_kwargs = self.calls[1][1]
        self.assertEqual(json.loads(first_kwargs["data"]), {"refresh_token": "old-refresh"})
        self.assertEqual(first_kwargs["data"], retry_kwargs["data"])
        self.assertEqual(
            first_kwargs["headers"]["Idempotency-Key"],
            retry_kwargs["headers"]["Idempotency-Key"],
        )
        self.assertIsNone(auth._pending_refresh)
        self.assertIsNone(self.persisted_attempt)

    def test_429_retry_keeps_the_same_logical_attempt(self):
        responses = [
            _Response(429, {"detail": {"message": "Try later"}}),
            self._success(),
        ]

        def post(url, **kwargs):
            self.calls.append((url, kwargs))
            return responses.pop(0)

        auth.requests.post = post
        limited = auth.refresh_access_token()
        self.assertFalse(limited["success"])
        self.assertTrue(limited["retryable"])
        auth._last_refresh = None
        auth._pending_refresh = None
        self.assertTrue(auth.refresh_access_token()["success"])

        self.assertEqual(
            self.calls[0][1]["headers"]["Idempotency-Key"],
            self.calls[1][1]["headers"]["Idempotency-Key"],
        )
        self.assertEqual(self.calls[0][1]["data"], self.calls[1][1]["data"])

    def test_persistence_failure_prevents_network_request(self):
        auth._persist_refresh_attempt = lambda attempt: False
        auth.requests.post = lambda *args, **kwargs: self.fail(
            "refresh must not be sent without a durable attempt marker"
        )

        result = auth.refresh_access_token()

        self.assertFalse(result["success"])
        self.assertIn("safely persist", result["message"])
        self.assertIsNone(auth._pending_refresh)

    def test_marker_deletion_failure_is_fail_safe_after_success(self):
        auth.requests.post = lambda *args, **kwargs: self._success()
        auth._delete_persisted_refresh_attempt = lambda: False

        self.assertTrue(auth.refresh_access_token()["success"])
        self.assertIsNotNone(self.persisted_attempt)

        # A fresh process sees a marker for the old token and the newly stored
        # refresh token. If cleanup still fails it must refuse to POST.
        auth._last_refresh = None
        auth._pending_refresh = None
        auth.requests.post = lambda *args, **kwargs: self.fail(
            "a stale durable marker must be cleared before another refresh"
        )
        result = auth.refresh_access_token()
        self.assertFalse(result["success"])
        self.assertIn("safely persist", result["message"])

    def test_definitive_auth_failure_clears_attempt_for_next_login(self):
        refresh_responses = [
            _Response(401, {"detail": {"message": "Token has been revoked"}}),
            self._success("post-login-access", "post-login-refresh"),
        ]

        def post(url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/login"):
                return self._success("login-access", "login-refresh")
            return refresh_responses.pop(0)

        auth.requests.post = post

        rejected = auth.refresh_access_token()
        self.assertFalse(rejected["success"])
        self.assertFalse(rejected["retryable"])
        first_key = self.calls[0][1]["headers"]["Idempotency-Key"]
        self.assertIsNone(auth._pending_refresh)
        self.assertEqual(self.credentials, {"access": "", "refresh": ""})

        logged_in = auth.login("artist@example.test", "password")
        self.assertTrue(logged_in["success"])
        refreshed = auth.refresh_access_token()
        self.assertTrue(refreshed["success"])

        second_refresh_call = self.calls[2][1]
        self.assertEqual(
            json.loads(second_refresh_call["data"]),
            {"refresh_token": "login-refresh"},
        )
        self.assertNotEqual(
            first_key,
            second_refresh_call["headers"]["Idempotency-Key"],
        )

    def test_login_invalidates_a_cached_success(self):
        refresh_responses = [
            self._success("rotated-access", "rotated-refresh"),
            self._success("latest-access", "latest-refresh"),
        ]

        def post(url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/login"):
                return self._success("login-access", "login-refresh")
            return refresh_responses.pop(0)

        auth.requests.post = post

        self.assertTrue(auth.refresh_access_token()["success"])
        self.assertTrue(auth.login("artist@example.test", "password")["success"])
        result = auth.refresh_access_token()

        self.assertTrue(result["success"])
        refresh_calls = [call for call in self.calls if call[0].endswith("/refresh")]
        self.assertEqual(len(refresh_calls), 2)
        self.assertEqual(
            json.loads(refresh_calls[1][1]["data"]),
            {"refresh_token": "login-refresh"},
        )

    def test_login_clears_an_ambiguous_persisted_attempt(self):
        def post(url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/login"):
                return self._success("login-access", "login-refresh")
            raise auth.requests.exceptions.Timeout()

        auth.requests.post = post
        self.assertFalse(auth.refresh_access_token()["success"])
        self.assertIsNotNone(self.persisted_attempt)

        result = auth.login("artist@example.test", "password")

        self.assertTrue(result["success"])
        self.assertIsNone(self.persisted_attempt)
        self.assertIsNone(auth._pending_refresh)
        self.assertIsNone(auth._last_refresh)

    def test_logout_clears_credentials_and_pending_attempt(self):
        auth.requests.post = lambda *args, **kwargs: (_ for _ in ()).throw(
            auth.requests.exceptions.Timeout()
        )
        self.assertFalse(auth.refresh_access_token()["success"])
        self.assertIsNotNone(self.persisted_attempt)

        self.assertTrue(auth.clear_credentials())

        self.assertEqual(self.credentials, {"access": "", "refresh": ""})
        self.assertIsNone(self.persisted_attempt)
        self.assertIsNone(auth._pending_refresh)
        self.assertIsNone(auth._last_refresh)

    def test_sso_uses_the_fenced_login_pair_store(self):
        source = inspect.getsource(sso.sso_login)
        self.assertIn("store_login_token_pair(", source)
        self.assertNotIn("store_access_token(", source)

    def test_ui_logout_uses_fenced_credential_clear(self):
        source = Path(
            _scripts_dir,
            "mixar",
            "modules",
            "space_mixie_chat",
            "ui",
            "operators",
            "auth_ops.py",
        ).read_text(encoding="utf-8")
        logout_source = source[source.index("class MIXIE_CHAT_OT_logout"):]
        self.assertIn("clear_credentials()", logout_source)
        self.assertNotIn("delete_refresh_token()", logout_source)

    def test_startup_preserves_retryable_refresh_attempts(self):
        source = Path(
            _scripts_dir,
            "mixar",
            "modules",
            "space_mixie_chat",
            "ui",
            "operators",
            "auth_ops.py",
        ).read_text(encoding="utf-8")
        function_source = source[
            source.index("def _auth_check_background()"):
            source.index("\n\n_auth_check_started = False")
        ]
        retry_branch = function_source.index(
            'if refresh_result and refresh_result.get("retryable")'
        )
        credential_clear = function_source.index("clear_credentials()")
        self.assertLess(retry_branch, credential_clear)
        self.assertIn("preserving credentials for retry", function_source)

    def test_definitive_rejection_adopts_foreign_rotation_before_clearing(self):
        source = Path(
            _scripts_dir,
            "mixar",
            "modules",
            "space_mixie_chat",
            "ui",
            "operators",
            "auth_ops.py",
        ).read_text(encoding="utf-8")
        function_source = source[
            source.index("def _auth_check_background()"):
            source.index("\n\n_auth_check_started = False")
        ]
        # The pre-refresh snapshot is what makes a foreign rotation
        # detectable after a definitive rejection.
        snapshot = function_source.index(
            "stale_access_token = get_access_token()"
        )
        refresh_call = function_source.index(
            "refresh_result = refresh_access_token()"
        )
        self.assertLess(snapshot, refresh_call)

        # Credentials stored by another Blender process must be adopted
        # (or at least preserved) before clear_credentials can run.
        guard = function_source.index(
            "current_access_token != stale_access_token"
        )
        adopt = function_source.index(
            "_schedule_apply_login(user_info, refreshed=True)", guard
        )
        credential_clear = function_source.index("clear_credentials()")
        self.assertLess(guard, credential_clear)
        self.assertLess(adopt, credential_clear)

    def test_success_persists_attempt_then_refresh_then_access_then_clears(self):
        events = []

        def persist(attempt):
            events.append("persist-attempt")
            return self._persist_attempt(attempt)

        def store_refresh(token):
            events.append(f"store-refresh:{token}")
            return self._store_refresh(token)

        def store_access(token):
            events.append(f"store-access:{token}")
            return self._store_access(token)

        def clear_attempt():
            events.append("clear-attempt")
            return self._delete_attempt()

        auth._persist_refresh_attempt = persist
        auth.store_refresh_token = store_refresh
        auth.store_access_token = store_access
        auth._delete_persisted_refresh_attempt = clear_attempt
        auth.requests.post = lambda *args, **kwargs: self._success()

        self.assertTrue(auth.refresh_access_token()["success"])
        self.assertEqual(
            events,
            [
                "persist-attempt",
                "store-refresh:new-refresh",
                "store-access:new-access",
                "clear-attempt",
            ],
        )

    def test_login_waits_for_inflight_refresh_then_wins_with_complete_pair(self):
        refresh_started = threading.Event()
        release_refresh = threading.Event()

        def post(url, **kwargs):
            if url.endswith("/login"):
                return self._success("login-access", "login-refresh")
            refresh_started.set()
            self.assertTrue(release_refresh.wait(timeout=2))
            return self._success("rotated-access", "rotated-refresh")

        auth.requests.post = post
        results = {}
        refresh_thread = threading.Thread(
            target=lambda: results.setdefault("refresh", auth.refresh_access_token())
        )
        login_thread = threading.Thread(
            target=lambda: results.setdefault(
                "login",
                auth.login("artist@example.test", "password"),
            )
        )

        refresh_thread.start()
        self.assertTrue(refresh_started.wait(timeout=2))
        login_thread.start()
        time.sleep(0.02)
        release_refresh.set()
        refresh_thread.join(timeout=2)
        login_thread.join(timeout=2)

        self.assertFalse(refresh_thread.is_alive())
        self.assertFalse(login_thread.is_alive())
        self.assertTrue(results["refresh"]["success"])
        self.assertTrue(results["login"]["success"])
        self.assertEqual(
            self.credentials,
            {"access": "login-access", "refresh": "login-refresh"},
        )

    def test_pair_storage_writes_refresh_first_and_rolls_back_on_failure(self):
        writes = []

        def store_refresh(token):
            writes.append(("refresh", token))
            self.credentials["refresh"] = token
            return True

        def store_access(token):
            writes.append(("access", token))
            if token == "new-access":
                return False
            self.credentials["access"] = token
            return True

        auth.store_refresh_token = store_refresh
        auth.store_access_token = store_access

        stored, error = auth.store_login_token_pair("new-access", "new-refresh")

        self.assertFalse(stored)
        self.assertEqual(error, "Failed to store access token")
        self.assertEqual(
            writes,
            [
                ("refresh", "new-refresh"),
                ("access", "new-access"),
                ("refresh", "old-refresh"),
                ("access", "old-access"),
            ],
        )
        self.assertEqual(
            self.credentials,
            {"access": "old-access", "refresh": "old-refresh"},
        )

    def test_refresh_uses_standard_idempotency_key_header(self):
        def post(url, **kwargs):
            self.calls.append((url, kwargs))
            return self._success()

        auth.requests.post = post
        auth.refresh_access_token()

        headers = self.calls[0][1]["headers"]
        self.assertEqual(headers["Idempotency-Key"], "attempt-1")
        self.assertNotIn("X-Idempotency-Key", headers)


class TestPersistedAttemptRecovery(unittest.TestCase):
    """The real safe-storage loader must discard invalid markers, not wedge."""

    _STORAGE_KEY = ("MixarSafeStorage", "RefreshAttempt")
    _VALID_DIGEST = "a" * 64
    _VALID_UUID4 = "2f4d4a9e-9d3b-4c5e-8a2f-1b3c4d5e6f70"
    _VALID_UUID1 = "aaaaaaaa-aaaa-1aaa-8aaa-aaaaaaaaaaaa"

    def setUp(self):
        self.storage = {}
        for patcher in (
            patch.object(auth, "_is_windows", False),
            patch.object(auth.keyring, "get_password", side_effect=self._get),
            patch.object(auth.keyring, "set_password", side_effect=self._set),
            patch.object(
                auth.keyring, "delete_password", side_effect=self._del
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _get(self, service, username):
        return self.storage.get((service, username))

    def _set(self, service, username, value):
        self.storage[(service, username)] = value

    def _del(self, service, username):
        del self.storage[(service, username)]

    def _seed_marker(self, raw):
        self.storage[self._STORAGE_KEY] = raw

    def _marker(self):
        return self.storage.get(self._STORAGE_KEY)

    def test_valid_marker_is_returned_intact(self):
        marker = {
            "refresh_token_digest": self._VALID_DIGEST,
            "idempotency_key": self._VALID_UUID4,
        }
        self._seed_marker(json.dumps(marker))

        available, attempt = auth._load_persisted_refresh_attempt()

        self.assertTrue(available)
        self.assertEqual(attempt, marker)
        self.assertIsNotNone(self._marker())

    def test_invalid_marker_is_discarded_and_reported_absent(self):
        invalid_markers = [
            "{not json",
            json.dumps(["not", "a", "dict"]),
            json.dumps({"idempotency_key": self._VALID_UUID4}),
            json.dumps(
                {
                    "refresh_token_digest": "not-hex",
                    "idempotency_key": self._VALID_UUID4,
                }
            ),
            json.dumps(
                {
                    "refresh_token_digest": self._VALID_DIGEST,
                    "idempotency_key": "not-a-uuid",
                }
            ),
            json.dumps(
                {
                    "refresh_token_digest": self._VALID_DIGEST,
                    "idempotency_key": self._VALID_UUID1,
                }
            ),
        ]
        for raw in invalid_markers:
            with self.subTest(raw=raw):
                self._seed_marker(raw)

                available, attempt = auth._load_persisted_refresh_attempt()

                self.assertTrue(available)
                self.assertIsNone(attempt)
                self.assertIsNone(self._marker())

    def test_unreadable_storage_fails_closed_and_keeps_marker(self):
        self._seed_marker("{not json")

        with patch.object(
            auth.keyring, "get_password", side_effect=RuntimeError("locked")
        ):
            available, attempt = auth._load_persisted_refresh_attempt()

        self.assertFalse(available)
        self.assertIsNone(attempt)
        self.assertIsNotNone(self._marker())

    def test_undeletable_invalid_marker_fails_closed(self):
        self._seed_marker("{not json")

        with patch.object(
            auth, "_delete_persisted_refresh_attempt", return_value=False
        ):
            available, attempt = auth._load_persisted_refresh_attempt()

        self.assertFalse(available)
        self.assertIsNone(attempt)
        self.assertIsNotNone(self._marker())

    def test_corrupt_marker_no_longer_wedges_refresh(self):
        credentials = {"access": "old-access", "refresh": "old-refresh"}
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response(
                200,
                {"access_token": "new-access", "refresh_token": "new-refresh"},
            )

        def store_access(token):
            credentials["access"] = token
            return True

        def store_refresh(token):
            credentials["refresh"] = token
            return True

        for patcher in (
            patch.object(
                auth, "get_access_token", lambda: credentials["access"]
            ),
            patch.object(
                auth, "get_refresh_token", lambda: credentials["refresh"]
            ),
            patch.object(auth, "store_access_token", store_access),
            patch.object(auth, "store_refresh_token", store_refresh),
            patch.object(
                auth, "get_server_url", lambda: "https://api.example.test"
            ),
            patch.object(auth.requests, "post", side_effect=post),
            patch.object(auth, "_last_refresh", None),
            patch.object(auth, "_pending_refresh", None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        self._seed_marker("{not json")

        result = auth.refresh_access_token()

        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 1)
        sent_key = calls[0][1]["headers"]["Idempotency-Key"]
        self.assertEqual(uuid.UUID(sent_key).version, 4)
        self.assertIsNone(self._marker())
        self.assertEqual(
            credentials,
            {"access": "new-access", "refresh": "new-refresh"},
        )


if __name__ == "__main__":
    unittest.main()
