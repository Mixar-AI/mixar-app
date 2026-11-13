# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Game Studio's surface into the app (modules/cloud_studio): the pure parts.

What a chat bubble looks like to the studio, the three-word phase, and the two path rules that
keep a request from outside inside its own folders. No Blender needed.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import mixar.modules.cloud_studio as cloud_studio
from mixar.modules.cloud_studio import shape


def _bubble(**kw):
    base = dict(bubble_id="b1", sender="AGENT", message_type="AGENT", content="", text="", ephemeral="",
                loader_visible=False, loader_texts="[]", todo_items=[], step_items=[], action_items=[],
                input_type="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_api_version_is_declared():
    assert cloud_studio.API_VERSION >= 1


def test_phase_is_three_words():
    assert shape.phase("IDLE", False) == "idle"
    assert shape.phase("busy", False) == "working"
    assert shape.phase("modifying", False) == "working"
    assert shape.phase("AWAITING_INPUT", False) == "asking"
    # The turn went idle but its run's agents are still building: not free for a new request.
    assert shape.phase("idle", True) == "working"
    assert shape.phase(None, False) == "idle"


def test_a_bubble_becomes_plain_bounded_data():
    bubble = _bubble(
        content="x" * 9000,
        ephemeral="note",
        loader_visible=True,
        loader_texts='["Planning", "Still planning"]',
        todo_items=[SimpleNamespace(text="Greybox", status="IN_PROGRESS")] * 40,
        step_items=[SimpleNamespace(label="Run script", target="Cube", status="DONE", kind="TOOL")] * 30,
        action_items=[SimpleNamespace(label="Low poly", value="low")] * 12,
        input_type="choice",
    )
    out = shape.message(bubble)
    assert out["id"] == "b1" and out["role"] == "agent" and out["kind"] == "agent"
    assert len(out["text"]) == shape.MAX_TEXT and out["text"].endswith("…")
    assert out["working"] == "Planning" and out["note"] == "note" and out["asks"] is True
    assert len(out["todos"]) == 30 and out["todos"][0] == {"text": "Greybox", "status": "in_progress"}
    assert len(out["steps"]) == 20 and out["steps"][0] == {"label": "Run script", "target": "Cube", "status": "done", "kind": "tool"}
    assert len(out["actions"]) == 8 and out["actions"][0] == {"label": "Low poly", "value": "low"}


def test_a_user_bubble_and_a_loader_that_is_not_json():
    out = shape.message(_bubble(sender="USER", text="Make a harbor", loader_visible=True, loader_texts="Thinking"))
    assert out["role"] == "user" and out["text"] == "Make a harbor" and out["working"] == "Thinking"
    assert shape.message(_bubble())["working"] == ""


def test_only_the_last_messages_are_reported():
    items = [_bubble(bubble_id=str(i)) for i in range(100)]
    assert [m["id"] for m in shape.messages(items, 3)] == ["97", "98", "99"]
    assert len(shape.messages(items)) == shape.MAX_MESSAGES


def test_a_scene_file_must_be_a_mixar_inside_the_projects_folder(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    inside = str(root / "project.mixar")
    assert shape.scene_file(inside, str(root)) == os.path.realpath(inside)
    assert shape.scene_file(str(root / "sub" / "a.mixar"), str(root)) is not None
    assert shape.scene_file(str(root / ".." / "escape.mixar"), str(root)) is None
    assert shape.scene_file("/etc/passwd", str(root)) is None
    assert shape.scene_file(str(root / "project.blend"), str(root)) is None
    assert shape.scene_file("", str(root)) is None and shape.scene_file(inside, "") is None
    # A link out of the folder is followed before it is judged.
    outside = tmp_path / "elsewhere.mixar"
    outside.write_text("x")
    link = root / "link.mixar"
    link.symlink_to(outside)
    assert shape.scene_file(str(link), str(root)) is None


def test_an_attachment_must_be_an_existing_file_in_the_bridges_folder(tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    image = folder / "mark.png"
    image.write_bytes(b"png")
    assert shape.attachable(str(image), str(folder)) == os.path.realpath(str(image))
    assert shape.attachable(str(folder / "missing.png"), str(folder)) is None
    assert shape.attachable("/etc/passwd", str(folder)) is None
    assert shape.attachable(str(folder), str(folder)) is None
    assert shape.attachable(None, str(folder)) is None
