# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scheduling and interruption contracts that cannot be seen in a settled frame."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.common.notifications import store, toast_timer
from mixar.modules.common.notifications.constants import ANIMATION_INTERVAL, NotificationType


@pytest.mark.parametrize(
    ("remaining_ms", "expected"),
    [(1500.0, 0.2), (250.0, 0.05), (180.0, ANIMATION_INTERVAL), (1.0, ANIMATION_INTERVAL)],
)
def test_expiry_pump_wakes_at_fade_boundary_and_then_at_display_cadence(
    monkeypatch, remaining_ms, expected
):
    notification = SimpleNamespace(is_sticky=False, remaining_ms=remaining_ms)
    fake_store = SimpleNamespace(expire_old=lambda: 1, get_visible=lambda: [notification])
    monkeypatch.setattr(store, "get_notification_store", lambda: fake_store)
    monkeypatch.setattr(toast_timer, "_tag_redraw_view3d", lambda: None)
    assert toast_timer._toast_tick() == pytest.approx(expected)


def test_sticky_toast_keeps_low_rate_housekeeping(monkeypatch):
    notification = SimpleNamespace(is_sticky=True)
    fake_store = SimpleNamespace(expire_old=lambda: 1, get_visible=lambda: [notification])
    monkeypatch.setattr(store, "get_notification_store", lambda: fake_store)
    monkeypatch.setattr(toast_timer, "_tag_redraw_view3d", lambda: None)
    assert toast_timer._toast_tick() == 1.0


def test_fade_is_monotonic_and_finishes_at_expiry(monkeypatch):
    notification = store.NotificationItem(
        id="fade", type=NotificationType.INFO, title="Notice", body="", ttl_ms=1000,
        created_at=0.0,
    )
    opacity = []
    for timestamp in [0.0, 0.8, 0.85, 0.9, 0.95, 1.0, 1.2]:
        monkeypatch.setattr(store.time, "time", lambda: timestamp)
        opacity.append(notification.opacity)
    assert opacity[:2] == [1.0, 1.0]
    assert opacity[-2:] == [0.0, 0.0]
    assert all(a >= b for a, b in zip(opacity, opacity[1:]))
    assert len(set(opacity)) >= 5


def test_stale_native_collapse_cannot_hide_a_restored_window():
    root = Path(__file__).resolve().parents[1]
    native = (root / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc").read_text()
    start = native.index("static void minimise_anim_finish")
    finish = native[start:native.index("\n#endif", start)]
    assert finish.index("g_bubble_motion_generation") < finish.index("g_pill_ghostwin")
    assert "!g_bubble_minimised" in finish
    restore = native[native.index("static wmOperatorStatus mixar_bubble_restore_exec"):]
    restore = restore[:restore.index("void MIXAR_OT_bubble_restore")]
    assert restore.index("++g_bubble_motion_generation") < restore.index("Mixar_WindowOrderFront")
    closed = native[native.index("void ED_agent_bubble_windows_closed"):]
    closed = closed[:closed.index("void ED_agent_bubble_window_freed")]
    assert "++g_bubble_motion_generation" in closed
