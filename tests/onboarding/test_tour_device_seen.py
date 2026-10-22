# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour's seen flag is per device. A guest's identity is a fresh
placeholder email, so the old per-email list never matched it and every
Zen/Engine switch replayed the tour for a device that had already seen it."""

import json
import sys
from types import SimpleNamespace

import pytest

from mixar.modules.onboarding import core as onboarding
from mixar.modules.onboarding.core import persistence


@pytest.fixture
def seen_file(monkeypatch, tmp_path):
    path = tmp_path / "onboarding_seen.json"
    monkeypatch.setattr(persistence, "_seen_path", lambda: str(path))
    return path


@pytest.fixture
def scheduled(monkeypatch, seen_file):
    calls = []
    timers = SimpleNamespace(register=lambda fn, **_kw: calls.append(fn))
    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace(app=SimpleNamespace(timers=timers)))
    monkeypatch.setattr(onboarding, "_scheduled", False)
    return calls


def test_a_fresh_device_has_not_seen_the_tour(seen_file):
    assert persistence.has_device_seen_onboarding() is False


def test_marking_the_device_is_remembered(seen_file):
    persistence.mark_device_seen_onboarding()
    assert json.loads(seen_file.read_text()) == {"seen": True}
    assert persistence.has_device_seen_onboarding() is True


def test_a_legacy_per_email_list_counts_as_seen(seen_file):
    seen_file.write_text(json.dumps({"users_seen": ["ada@example.com"]}))
    assert persistence.has_device_seen_onboarding() is True


def test_an_empty_legacy_list_is_not_seen(seen_file):
    seen_file.write_text(json.dumps({"users_seen": []}))
    assert persistence.has_device_seen_onboarding() is False


def test_a_corrupt_file_is_not_seen(seen_file):
    seen_file.write_text("{not json")
    assert persistence.has_device_seen_onboarding() is False


def test_a_new_guest_on_a_seen_device_gets_no_tour(scheduled):
    onboarding.mark_seen()
    assert onboarding.maybe_show_tour("guest-new@guest.mixar.invalid") is False
    assert scheduled == []


def test_an_unseen_device_schedules_the_tour_once(scheduled):
    assert onboarding.maybe_show_tour("guest-x@guest.mixar.invalid") is True
    assert onboarding.maybe_show_tour("ada@example.com") is False
    assert len(scheduled) == 1


def test_no_session_schedules_nothing(scheduled):
    assert onboarding.maybe_show_tour("") is False
    assert scheduled == []


# -- hardening: atomic write, fail-open reads, the fire-time recheck --------

@pytest.fixture
def reported(monkeypatch):
    from mixar.modules.onboarding.core.tour import telemetry
    seen = []
    monkeypatch.setattr(telemetry, "seen_state_error",
                        lambda op, exc: seen.append((op, type(exc).__name__)))
    return seen


def test_the_write_is_atomic_and_leaves_no_temp_file(seen_file, reported):
    seen_file.write_text(json.dumps({"users_seen": []}))
    persistence.mark_device_seen_onboarding()
    assert json.loads(seen_file.read_text()) == {"seen": True}
    assert sorted(p.name for p in seen_file.parent.iterdir()) == [seen_file.name]
    assert reported == []


def test_a_failed_write_is_reported_and_cleans_its_temp_file(seen_file, reported, monkeypatch):
    from mixar.modules.common.utils import atomic_json

    def refuse(_src, _dst):
        raise PermissionError(13, "denied", str(seen_file))
    monkeypatch.setattr(atomic_json.os, "replace", refuse)
    persistence.mark_device_seen_onboarding()
    assert reported == [("write", "PermissionError")]
    assert list(seen_file.parent.iterdir()) == []
    assert persistence.has_device_seen_onboarding() is False


@pytest.mark.parametrize("content, error", [
    ("{not json", "JSONDecodeError"),
    ("[1, 2]", "ValueError"),
])
def test_an_unreadable_file_is_reported_and_fails_open(seen_file, reported, content, error):
    seen_file.write_text(content)
    assert persistence.has_device_seen_onboarding() is False
    assert reported == [("read", error)]


def test_a_corrupt_file_is_repaired_by_the_next_mark(seen_file, reported):
    seen_file.write_text("{not json")
    persistence.mark_device_seen_onboarding()
    assert json.loads(seen_file.read_text()) == {"seen": True}


@pytest.fixture
def fire_ready(monkeypatch, scheduled):
    """The scheduled timer, with the splash gone, the video bundled and the
    operator registered; ``invoked`` records each operator call."""
    import importlib
    invoked = []
    bpy_stub = sys.modules["bpy"]
    bpy_stub.ops = SimpleNamespace(mixar=SimpleNamespace(
        onboarding_tour=lambda *a, **kw: invoked.append((a, kw))))
    splash = SimpleNamespace(onboarding_can_start=lambda: True)
    monkeypatch.setitem(sys.modules, "mixar.bootstrap.splash_menu", splash)
    monkeypatch.setattr(importlib.import_module("mixar.bootstrap"), "splash_menu",
                        splash, raising=False)
    tour_pkg = importlib.import_module("mixar.modules.onboarding.core.tour")
    monkeypatch.setattr(tour_pkg, "is_available", lambda: True)
    monkeypatch.setattr(onboarding, "_operator_registered", lambda _op: True)
    return invoked


def test_the_timer_invokes_the_tour_with_its_start_source(fire_ready, scheduled):
    assert onboarding.maybe_show_tour("ada@example.com", "auto_signin") is True
    assert scheduled[0]() is None
    assert fire_ready == [(("INVOKE_DEFAULT",), {"start_source": "auto_signin"})]
    assert onboarding._scheduled is False


def test_the_timer_skips_a_device_that_saw_the_tour_meanwhile(fire_ready, scheduled):
    assert onboarding.maybe_show_tour("ada@example.com", "auto_mode") is True
    onboarding.mark_seen()  # e.g. Help → Start tour ran past its first beat
    assert scheduled[0]() is None
    assert fire_ready == []
    assert onboarding._scheduled is False
