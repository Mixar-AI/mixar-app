# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A background thread that cannot start never raises out of a timer.

Crash signature 7532fab1 (4.4.2, Windows): ``RuntimeError: can't start new
thread`` from ``chat_generate_options_cache._periodic_revalidate``. Raised from
a ``bpy.app.timers`` callback, the error also unregisters the timer, so the
options stopped refreshing for the rest of the session. The generation catalog
cache has the same timer; the BYOK models cache would have stayed "loading"
forever and never refreshed again.
"""

import threading
from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy

bpy.types.Panel.bl_rna = SimpleNamespace(
    properties={"bl_space_type": SimpleNamespace(enum_items=[])}
)

from mixar.bootstrap import chat_generate_options_cache as CHAT_CACHE
from mixar.bootstrap import generation_catalog_cache as CATALOG_CACHE
from mixar.modules.byok.core import models_cache
from mixar.modules.common.utils import threads


class _NoThreads:
    """``threading.Thread`` on a process that has no thread left to give."""

    started = 0

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        type(self).started += 1
        raise RuntimeError("can't start new thread")


@pytest.fixture
def no_threads(monkeypatch):
    _NoThreads.started = 0
    monkeypatch.setattr(threading, "Thread", _NoThreads)
    return _NoThreads


def test_start_daemon_thread_reports_a_thread_that_could_not_start(no_threads):
    assert threads.start_daemon_thread(lambda: None, name="QAThread") is False
    assert no_threads.started == 1


def test_start_daemon_thread_starts_a_daemon_thread():
    ran = threading.Event()
    assert threads.start_daemon_thread(ran.set, name="QAThread") is True
    assert ran.wait(5)


@pytest.mark.parametrize("cache", [CHAT_CACHE, CATALOG_CACHE], ids=["chat_options", "catalog"])
def test_periodic_revalidate_keeps_its_timer_when_no_thread_starts(cache, no_threads):
    with cache._lock:
        cache._shutdown_requested = False
        cache._is_loading = False
    # Returning the interval keeps the timer registered; raising would drop it.
    assert cache._periodic_revalidate() == cache._REVALIDATE_INTERVAL_S
    assert cache._periodic_revalidate() == cache._REVALIDATE_INTERVAL_S
    assert no_threads.started == 2  # tried again on the next tick


@pytest.mark.parametrize("cache", [CHAT_CACHE, CATALOG_CACHE], ids=["chat_options", "catalog"])
def test_startup_fetch_does_not_raise_when_no_thread_starts(cache, no_threads):
    assert cache._start_background_fetch() is None
    assert no_threads.started == 1


def test_byok_refresh_stays_retryable_when_no_thread_starts(no_threads):
    models_cache.reset_lifecycle()
    models_cache.refresh()
    models_cache.refresh()
    # Each refresh tried: the first failure did not leave the cache "loading".
    assert no_threads.started == 2
    with models_cache._lock:
        assert models_cache._is_loading is False
