# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Behavioral tests for mid-turn SSE loss → attach/replay recovery.

Drives SSEStreamHandler._stream_loop directly (no threads) against a fake
httpx module, simulating a network drop mid-stream and verifying the
handler re-attaches via /agent/chat/attach, deduplicates the replayed
overlap by seq, and finalizes the turn exactly once.
"""

import json
import unittest
from unittest import mock

from mixar.modules.space_mixie_chat.core import sse_handler as sh


def _data(payload: dict) -> str:
    return "data: " + json.dumps(payload)


class _FakeResponse:
    def __init__(self, status_code=200, lines=None, raise_after=None):
        self.status_code = status_code
        self._lines = list(lines or [])
        self._raise_after = raise_after
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b""

    def iter_lines(self):
        yield from self._lines
        if self._raise_after is not None:
            raise self._raise_after


class _FakeClient:
    """Pops the next scripted response for the URL being requested."""

    script = {}  # url-suffix -> list of _FakeResponse (class-level, per test)
    requests = []

    def __init__(self, timeout=None):
        pass

    def stream(self, method, url, json=None, headers=None):
        _FakeClient.requests.append((url, json))
        for suffix, responses in _FakeClient.script.items():
            if url.endswith(suffix):
                return responses.pop(0)
        raise AssertionError(f"Unexpected URL {url}")

    def close(self):
        pass


class _FakeTimeout:
    def __init__(self, **kwargs):
        pass


class _FakeHttpx:
    Client = _FakeClient
    Timeout = _FakeTimeout

    class ConnectError(Exception):
        pass

    class TimeoutException(Exception):
        pass


class SSEReconnectResumeTest(unittest.TestCase):
    def setUp(self):
        _FakeClient.script = {}
        _FakeClient.requests = []
        self.events = []
        self.errors = []
        self.completes = []
        self.handler = sh.SSEStreamHandler(
            host="http://x",
            on_event=self.events.append,
            on_error=self.errors.append,
            on_complete=lambda: self.completes.append(True),
        )
        patches = [
            mock.patch.object(sh, "httpx", _FakeHttpx),
            mock.patch.object(sh, "ATTACH_RETRY_DELAYS", (0.0,)),
            mock.patch.object(sh, "ATTACH_RETRY_MAX_SECONDS", 5.0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run_chat_stream(self):
        self.handler._session_id = "sess"
        self.handler._last_seq = -1
        self.handler._resume_unavailable = False
        self.handler._running.set()
        try:
            self.handler._stream_loop(
                message="hi",
                instance_id="inst",
                session_id="sess",
                plan_required=False,
                execution_required=True,
                approval_required=False,
                auth_token="tok",
            )
        finally:
            self.handler._running.clear()

    def test_mid_stream_loss_recovers_via_attach_with_seq_dedup(self):
        _FakeClient.script = {
            "/agent/chat": [
                _FakeResponse(
                    lines=[_data({"bubble_id": "b", "seq": 0, "content": {"append": "He"}}),
                           _data({"bubble_id": "b", "seq": 1, "content": {"append": "llo"}})],
                    raise_after=ConnectionError("network dropped"),
                ),
            ],
            "/agent/chat/attach": [
                _FakeResponse(
                    lines=[
                        # Replay overlaps what the live stream delivered...
                        _data({"bubble_id": "b", "seq": 0, "content": {"append": "He"}}),
                        _data({"bubble_id": "b", "seq": 1, "content": {"append": "llo"}}),
                        # ...then continues with what was missed.
                        _data({"bubble_id": "b", "seq": 2, "content": {"append": " world"}}),
                        "data: [DONE]",
                    ],
                ),
            ],
        }

        self._run_chat_stream()

        seqs = [e.data["seq"] for e in self.events]
        self.assertEqual(seqs, [0, 1, 2], "replayed overlap must be deduped")
        self.assertEqual(len(self.completes), 1)
        self.assertEqual(self.errors, [])
        # attach was called with the last seq seen on the live stream
        attach_calls = [j for (u, j) in _FakeClient.requests if u.endswith("/attach")]
        self.assertEqual(attach_calls, [{"session_id": "sess", "after_seq": 1}])

    def test_attach_retries_through_connect_errors(self):
        def _raising_stream(method, url, json=None, headers=None):
            raise _FakeHttpx.ConnectError("still down")

        _FakeClient.script = {
            "/agent/chat": [
                _FakeResponse(lines=[_data({"bubble_id": "b", "seq": 0})],
                              raise_after=ConnectionError("network dropped")),
            ],
            "/agent/chat/attach": [
                mock.MagicMock(  # first attach attempt: network still down
                    __enter__=mock.MagicMock(side_effect=_FakeHttpx.ConnectError("down")),
                    __exit__=mock.MagicMock(return_value=False),
                ),
                _FakeResponse(lines=[_data({"bubble_id": "b", "seq": 1}), "data: [DONE]"]),
            ],
        }

        self._run_chat_stream()

        self.assertEqual([e.data["seq"] for e in self.events], [0, 1])
        self.assertEqual(len(self.completes), 1)
        self.assertEqual(self.errors, [])

    def test_resume_unavailable_fails_the_turn_without_completing(self):
        _FakeClient.script = {
            "/agent/chat": [
                _FakeResponse(lines=[_data({"bubble_id": "b", "seq": 0})],
                              raise_after=ConnectionError("network dropped")),
            ],
            "/agent/chat/attach": [
                _FakeResponse(lines=[_data({"type": "resume_unavailable"}),
                                     "data: [DONE]"]),
            ],
        }

        self._run_chat_stream()

        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.completes, [],
                         "an unrecoverable turn must not complete as success")

    def test_user_stop_during_stream_does_not_attach(self):
        class _StopMidStream(_FakeResponse):
            def __init__(self, handler, **kw):
                super().__init__(**kw)
                self._handler = handler

            def iter_lines(self):
                yield _data({"bubble_id": "b", "seq": 0})
                self._handler._user_aborted = True
                self._handler._running.clear()
                yield _data({"bubble_id": "b", "seq": 1})

        _FakeClient.script = {
            "/agent/chat": [_StopMidStream(self.handler)],
            "/agent/chat/attach": [],
        }

        self._run_chat_stream()

        attach_calls = [u for (u, _) in _FakeClient.requests if u.endswith("/attach")]
        self.assertEqual(attach_calls, [])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
