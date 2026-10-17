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
