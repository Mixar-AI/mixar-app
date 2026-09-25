# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Onboarding waits for the splash to actually close.

An idle splash stops redrawing, so draw-staleness read it as dismissed and
the tour started behind it. ``onboarding_can_start`` now trusts the native
``WindowManager.mixar_splash_open`` flag while the popup is alive.
"""

import time
from types import SimpleNamespace

import pytest

from mixar.bootstrap import splash_menu


@pytest.fixture
def gate(monkeypatch):
    def configure(*, splash_open, drawn_ago=None, mode_chosen=False, loaded_ago=60.0):
        now = time.monotonic()
        wm = SimpleNamespace() if splash_open is None else SimpleNamespace(
            mixar_splash_open=splash_open)
        monkeypatch.setattr(splash_menu.bpy, "context", SimpleNamespace(
            window_manager=wm,
            preferences=SimpleNamespace(view=SimpleNamespace(show_splash=True)),
        ), raising=False)
        monkeypatch.setattr(splash_menu, "_splash_last_drawn_ts",
                            0.0 if drawn_ago is None else now - drawn_ago)
        monkeypatch.setattr(splash_menu, "_splash_mode_chosen", mode_chosen)
        monkeypatch.setattr(splash_menu, "_module_load_ts", now - loaded_ago)
        return splash_menu.onboarding_can_start()
    return configure


def test_idle_open_splash_blocks_the_tour(gate):
    # Last drawn a minute ago — the old staleness check would have fired.
    assert gate(splash_open=True, drawn_ago=60.0) is False


def test_mode_pick_does_not_override_a_live_splash(gate):
    assert gate(splash_open=True, drawn_ago=0.1, mode_chosen=True) is False


def test_closed_splash_starts_immediately(gate):
    assert gate(splash_open=False, drawn_ago=0.1) is True


def test_never_shown_splash_waits_for_startup_grace(gate):
    assert gate(splash_open=False, loaded_ago=0.5) is False
    assert gate(splash_open=False, loaded_ago=60.0) is True


def test_builds_without_native_flag_fall_back_to_staleness(gate):
    assert gate(splash_open=None, drawn_ago=0.1) is False
    assert gate(splash_open=None, drawn_ago=60.0) is True
