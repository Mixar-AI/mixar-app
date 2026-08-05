# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contracts for non-overlapping Scene Segment status polling."""

from pathlib import Path

from mixar.modules.moodboard.core.scene_segment_poll_guard import (
    SceneSegmentPollGuard,
)


ROOT = Path(__file__).resolve().parents[2]
MANAGER_PATH = (
    ROOT / "src/scripts/mixar/modules/moodboard/core/scene_segment_manager.py"
)


def test_poll_guard_allows_only_one_lease_per_image():
    guard = SceneSegmentPollGuard()

    first_lease = guard.acquire("character.png")

    assert first_lease is not None
    assert guard.acquire("character.png") is None
    assert guard.acquire("other.png") is not None
    assert guard.release("character.png", first_lease) is True
    assert guard.acquire("character.png") is not None


def test_stale_lease_cannot_release_replacement_poll():
    guard = SceneSegmentPollGuard()
    stale_lease = guard.acquire("character.png")
    guard.clear("character.png")
    replacement_lease = guard.acquire("character.png")

    assert guard.release("character.png", stale_lease) is False
    assert guard.acquire("character.png") is None
    assert guard.release("character.png", replacement_lease) is True


def test_scene_segment_manager_holds_lease_until_main_thread_processing():
    source = MANAGER_PATH.read_text(encoding="utf-8")

    assert "lease = self._poll_guard.acquire(image_name)" in source
    assert (
        "finally:\n                        self._poll_guard.release(image_name, lease)"
        in source
    )
    assert "self._poll_guard.clear(image.name)" in source
    assert "self._poll_guard.clear()" in source
