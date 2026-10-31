# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Uncaught Python exceptions: chained hooks, dedupe, rate limit, scrubbing."""

import sys
import threading

import pytest

from mixar.modules.common.crash_reports.constants import MAX_EXCEPTIONS_PER_SESSION
from mixar.modules.common.crash_reports.core import excepthook

STATIC = {"platform": "windows", "os_version": "Windows 11"}


class FakeReporter:
    def __init__(self, fail=False):
        self.queued = []
        self.fail = fail

    def current(self):
        return {"app_version": "4.3.7", "blender_version": "5.2.0", "agent_run_id": "run-1"}

    def enqueue_exception(self, payload):
        if self.fail:
            raise RuntimeError("disk full")
        self.queued.append(payload)


@pytest.fixture
def reporter():
    excepthook.reset_for_tests()
    fake = FakeReporter()
    excepthook.install(fake, STATIC)
    yield fake
    excepthook.reset_for_tests()


def _raise(message="boom at /Users/jdoe/x.py for jdoe@example.com"):
    try:
        raise KeyError(message)
    except KeyError:
        return sys.exc_info()


def test_report_is_scrubbed_and_shaped(reporter):
    assert excepthook.report_exception(*_raise(), source="excepthook")
    payload = reporter.queued[0]
    assert payload["kind"] == "python" and payload["crash_type"] == "KeyError"
    assert "/Users/" not in payload["message"] and "@example.com" not in payload["message"]
    assert payload["python_frames"][0]["function"] == "_raise"
    assert payload["context"]["agent_run_id"] == "run-1"
    assert payload["context"]["context_source"] == "live"
    assert payload["platform"] == "windows" and payload["app_version"] == "4.3.7"


def test_same_exception_is_reported_once_per_session(reporter):
    for _ in range(3):
        excepthook.report_exception(*_raise(), source="excepthook")
    assert len(reporter.queued) == 1


def test_reports_are_capped_per_session(reporter):
    for index in range(MAX_EXCEPTIONS_PER_SESSION + 5):
        exec(f"def f{index}():\n    raise ValueError('x')", globals())
        try:
            globals()[f"f{index}"]()
        except ValueError:
            excepthook.report_exception(*sys.exc_info(), source="excepthook")
    assert len(reporter.queued) == MAX_EXCEPTIONS_PER_SESSION


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_interrupts_are_not_reported(reporter, exc):
    try:
        raise exc()
    except BaseException:
        assert not excepthook.report_exception(*sys.exc_info(), source="excepthook")


def test_hooks_chain_to_the_previous_ones(monkeypatch):
    excepthook.reset_for_tests()
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: seen.append(("sys", args[0])))
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(("thread", args.exc_type)))
    fake = FakeReporter()
    excepthook.install(fake, STATIC)
    try:
        sys.excepthook(*_raise())
        thread = threading.Thread(target=lambda: (_ for _ in ()).throw(ValueError("in thread")))
        thread.start()
        thread.join()
    finally:
        excepthook.reset_for_tests()
    assert ("sys", KeyError) in seen and ("thread", ValueError) in seen
    assert [p["source"] for p in fake.queued] == ["excepthook", "threading_excepthook"]


def test_a_failing_reporter_never_raises_from_the_hook():
    excepthook.reset_for_tests()
    excepthook.install(FakeReporter(fail=True), STATIC)
    try:
        assert excepthook.report_exception(*_raise(), source="excepthook") is False
    finally:
        excepthook.reset_for_tests()


def test_without_a_reporter_nothing_happens():
    excepthook.reset_for_tests()
    assert excepthook.report_exception(*_raise(), source="operator") is False
