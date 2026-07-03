# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure thinking live->finalized lifecycle (no bpy)."""
import importlib.util
import os

# Load thinking_lifecycle.py directly by path so the test needs no package
# import machinery / bpy. Mirrors test_steps_format.py.
_HERE = os.path.dirname(__file__)
_PATH = os.path.join(
    _HERE, "..", "space_mixie_chat", "core", "thinking_lifecycle.py"
)
_spec = importlib.util.spec_from_file_location("thinking_lifecycle", _PATH)
thinking_lifecycle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(thinking_lifecycle)
apply_ephemeral_to_bubble = thinking_lifecycle.apply_ephemeral_to_bubble


class _FakeBubble:
    """Duck-typed message PropertyGroup for the fields the lifecycle touches."""

    def __init__(self):
        self.ephemeral = ""
        self.thinking_text = ""
        self.thinking_active = False
        self.thinking_start_time = 0.0
        self.thinking_duration_ms = 0


def test_set_starts_thinking_and_records_start_time():
    bubble = _FakeBubble()
    finalized = apply_ephemeral_to_bubble(bubble, {"set": "pondering..."}, now=100.0)
    assert finalized is False
    assert bubble.ephemeral == "pondering..."
    assert bubble.thinking_active is True
    assert bubble.thinking_start_time == 100.0


def test_append_starts_once_and_accumulates_text():
    bubble = _FakeBubble()
    apply_ephemeral_to_bubble(bubble, {"append": "step one\n"}, now=50.0)
    apply_ephemeral_to_bubble(bubble, {"append": "step two"}, now=51.0)
    assert bubble.ephemeral == "step one\nstep two"
    assert bubble.thinking_active is True
    # Start time must be from the FIRST append, not overwritten by the second.
    assert bubble.thinking_start_time == 50.0


def test_clear_finalizes_snapshot_and_duration():
    bubble = _FakeBubble()
    apply_ephemeral_to_bubble(bubble, {"set": "deep reasoning"}, now=10.0)
    finalized = apply_ephemeral_to_bubble(bubble, {"clear": True}, now=16.5)
    assert finalized is True
    assert bubble.ephemeral == ""
    assert bubble.thinking_text == "deep reasoning"
    assert bubble.thinking_active is False
    assert bubble.thinking_duration_ms == 6500


def test_clear_without_live_thinking_just_clears():
    bubble = _FakeBubble()
    finalized = apply_ephemeral_to_bubble(bubble, {"clear": True}, now=5.0)
    assert finalized is False
    assert bubble.ephemeral == ""
    assert bubble.thinking_text == ""
    assert bubble.thinking_duration_ms == 0


def test_set_empty_does_not_start_thinking():
    bubble = _FakeBubble()
    apply_ephemeral_to_bubble(bubble, {"set": ""}, now=1.0)
    assert bubble.thinking_active is False
    assert bubble.thinking_start_time == 0.0


def test_second_phase_appends_text_and_accumulates_duration():
    bubble = _FakeBubble()
    apply_ephemeral_to_bubble(bubble, {"set": "phase one"}, now=0.0)
    apply_ephemeral_to_bubble(bubble, {"clear": True}, now=2.0)
    apply_ephemeral_to_bubble(bubble, {"set": "phase two"}, now=10.0)
    finalized = apply_ephemeral_to_bubble(bubble, {"clear": True}, now=13.0)
    assert finalized is True
    assert bubble.thinking_text == "phase one\n\nphase two"
    assert bubble.thinking_duration_ms == 5000
    assert bubble.thinking_active is False
