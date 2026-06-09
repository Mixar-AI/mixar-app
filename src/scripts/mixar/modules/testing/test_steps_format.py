# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure steps-summary formatter (no bpy required)."""
import importlib.util
import os

# Load steps_format.py directly by path so the test needs no package import
# machinery / bpy. Mirrors how other pure-logic tests isolate a single module.
_HERE = os.path.dirname(__file__)
_PATH = os.path.join(
    _HERE, "..", "space_mixie_chat", "core", "steps_format.py"
)
_spec = importlib.util.spec_from_file_location("steps_format", _PATH)
steps_format = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(steps_format)
format_steps_summary = steps_format.format_steps_summary


def test_empty_returns_empty_string():
    assert format_steps_summary([]) == ""


def test_single_read():
    assert format_steps_summary(["READ"]) == "Read 1 file"


def test_read_and_command():
    # One file read, one command run.
    assert format_steps_summary(["READ", "COMMAND"]) == "Read 1 file · ran 1 command"


def test_pluralization_and_grouping():
    # Two reads, two commands -> pluralized, grouped, kind order preserved.
    summary = format_steps_summary(["READ", "COMMAND", "READ", "COMMAND"])
    assert summary == "Read 2 files · ran 2 commands"


def test_all_kinds_order():
    summary = format_steps_summary(["READ", "WRITE", "COMMAND", "SEARCH", "TOOL"])
    assert summary == (
        "Read 1 file · wrote 1 file · ran 1 command · "
        "ran 1 search · used 1 tool"
    )


def test_unknown_kind_ignored():
    assert format_steps_summary(["READ", "NOPE"]) == "Read 1 file"


# --- normalize_step_item (pure, no bpy) ----------------------------------

def test_normalize_maps_kind_and_status_uppercase():
    out = steps_format.normalize_step_item(
        {"id": "s1", "kind": "read", "label": "Read", "target": "a.py",
         "detail": "x", "status": "done"})
    assert out == {"item_id": "s1", "kind": "READ", "label": "Read",
                   "target": "a.py", "detail": "x", "status": "DONE"}


def test_normalize_defaults_invalid_kind_to_tool_and_status_to_done():
    out = steps_format.normalize_step_item(
        {"id": "", "kind": "bogus", "status": "weird"})
    assert out["kind"] == "TOOL"
    assert out["status"] == "DONE"


def test_normalize_handles_missing_and_none_fields():
    out = steps_format.normalize_step_item({"kind": "command"})
    assert out["item_id"] == ""
    assert out["label"] == ""
    assert out["target"] == ""
    assert out["detail"] == ""
    assert out["kind"] == "COMMAND"


def test_normalize_valid_non_default_status_preserved():
    out = steps_format.normalize_step_item({"kind": "read", "status": "running"})
    assert out["status"] == "RUNNING"


# --- apply_steps_to_bubble (duck-typed bubble, no bpy) -------------------

class _FakeStep:
    """Bare object with freely-settable attributes (like a PropertyGroup item)."""
    pass


class _FakeColl(list):
    def add(self):
        item = _FakeStep()
        self.append(item)
        return item
    # list.clear() already matches Blender collection .clear()


class _FakeBubble:
    def __init__(self):
        self.step_items = _FakeColl()
        self.steps_summary = ""


def test_apply_steps_replaces_items_and_computes_summary():
    bubble = _FakeBubble()
    bubble.step_items.add()  # pre-existing item that must be cleared

    steps_format.apply_steps_to_bubble(bubble, {
        "summary": "",  # empty -> compute from kinds
        "items": [
            {"id": "s1", "kind": "read", "label": "Read", "target": "a.py",
             "detail": "", "status": "done"},
            {"id": "s2", "kind": "command", "label": "Ran", "target": "pytest",
             "detail": "3 passed", "status": "done"},
        ],
    })

    assert len(bubble.step_items) == 2
    assert bubble.step_items[0].item_id == "s1"
    assert bubble.step_items[0].kind == "READ"
    assert bubble.step_items[1].kind == "COMMAND"
    assert bubble.step_items[1].detail == "3 passed"
    assert bubble.steps_summary == "Read 1 file · ran 1 command"


def test_apply_steps_uses_explicit_summary_when_given():
    bubble = _FakeBubble()
    steps_format.apply_steps_to_bubble(bubble, {
        "summary": "Custom summary",
        "items": [{"id": "s1", "kind": "tool", "label": "X", "status": "running"}],
    })
    assert bubble.steps_summary == "Custom summary"
    assert bubble.step_items[0].kind == "TOOL"
    assert bubble.step_items[0].status == "RUNNING"
