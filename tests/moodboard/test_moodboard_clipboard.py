# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which copy a paste reads: this process's, another instance's, or the OS's.

`moodboard_clipboard` arbitrates between the in-process snapshot and the shared
on-disk buffer; the paste operator then lets a NEWER picture on the OS
clipboard outrank both. Both decisions are pinned here, with the buffer and
snapshot modules replaced by recording fakes.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.moodboard.core import moodboard_clipboard as mc

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


@pytest.fixture
def fakes(monkeypatch):
    """Replace the buffer + snapshot seams and reset the session state."""
    state = {
        "manifest": None,
        "written": [],
        "imported": [],
        "materialized": [],
        "payload": {"version": 1, "media": [{"image_name": "photo.png"}], "textboxes": [], "nodes": []},
        "images": {"photo.png": object()},
    }

    def write_buffer(payload, names, *, system_image_size=None):
        state["written"].append((payload, list(names), system_image_size))
        state["manifest"] = {
            "buffer_id": f"buf{len(state['written'])}", "token": mc.moodboard_copybuffer.PROCESS_TOKEN,
            "written_at": mc.time.time(), "payload": payload, "system_image_size": system_image_size,
        }
        return state["manifest"]["buffer_id"]

    def import_buffer_images(manifest):
        state["imported"].append(manifest["buffer_id"])
        # Appended under a fresh name, as Blender does on a collision.
        return {"photo.png": SimpleNamespace(name="photo.png.001")}

    def materialize(scene, payload, resolver, anchor=None):
        state["materialized"].append((payload, resolver, anchor))
        return 1

    monkeypatch.setattr(mc.moodboard_copybuffer, "write_buffer", write_buffer)
    monkeypatch.setattr(mc.moodboard_copybuffer, "read_manifest", lambda: state["manifest"])
    monkeypatch.setattr(mc.moodboard_copybuffer, "import_buffer_images", import_buffer_images)
    monkeypatch.setattr(mc.clipboard_snapshot, "build_snapshot", lambda scene: state["payload"])
    monkeypatch.setattr(mc.clipboard_snapshot, "materialize_snapshot", materialize)
    monkeypatch.setattr(mc.node_duplicate, "default_image_resolver", lambda name: state["images"].get(name))
    monkeypatch.setattr(mc, "_export_still_to_system_clipboard", lambda image, scene: (1000, 500))
    monkeypatch.setattr(mc, "_first_copied_still", lambda scene: object())
    monkeypatch.setattr(mc, "_SESSION", {"payload": None, "buffer_id": None, "copied_at": 0.0, "system_image_size": None})
    monkeypatch.setattr(mc, "_IMPORTED", {"buffer_id": None, "images": {}})
    return state


def test_nothing_copied_means_nothing_to_paste(fakes):
    assert mc.clipboard_source() is None
    assert mc.has_clipboard() is False
    assert mc.paste_clipboard(object()) == 0
    assert mc.clipboard_exported_size() is None


def test_copy_writes_the_buffer_and_pastes_from_the_session(fakes):
    assert mc.copy_selected(object()) == 1
    payload, names, size = fakes["written"][0]
    assert names == ["photo.png"]
    assert size == (1000, 500)

    assert mc.clipboard_source() == "session"
    assert mc.clipboard_exported_size() == (1000, 500)
    assert mc.paste_clipboard(object(), anchor=(1.0, 2.0)) == 1
    pasted_payload, resolver, anchor = fakes["materialized"][0]
    assert pasted_payload is payload
    assert resolver is mc.node_duplicate.default_image_resolver
    assert anchor == (1.0, 2.0)
    # Our own buffer is never re-imported.
    assert fakes["imported"] == []


def test_a_newer_copy_from_another_instance_wins_and_is_appended(fakes):
    mc.copy_selected(object())
    foreign_payload = {"version": 1, "media": [{"image_name": "theirs.png"}], "textboxes": [], "nodes": []}
    fakes["manifest"] = {
        "buffer_id": "theirs", "token": "other-process", "written_at": mc.time.time() + 5.0,
        "payload": foreign_payload, "system_image_size": [640, 480],
    }

    assert mc.clipboard_source() == "buffer"
    assert mc.clipboard_exported_size() == (640, 480)
    assert mc.paste_clipboard(object()) == 1
    assert fakes["imported"] == ["theirs"]
    pasted_payload, resolver, _ = fakes["materialized"][0]
    assert pasted_payload is foreign_payload
    assert resolver is not mc.node_duplicate.default_image_resolver

    # A second paste of the same buffer reuses the appended datablocks rather
    # than appending `.001`, `.002` ... every time -- unless one was deleted.
    appended = mc._IMPORTED["images"]["photo.png"]
    fakes["images"][appended.name] = appended
    mc.paste_clipboard(object())
    assert fakes["imported"] == ["theirs"]
    del fakes["images"][appended.name]
    mc.paste_clipboard(object())
    assert fakes["imported"] == ["theirs", "theirs"]


def test_an_older_foreign_buffer_loses_to_a_fresh_session_copy(fakes):
    """A failed buffer write must not make an old manifest win over the copy
    the user just made in this window."""
    fakes["manifest"] = {
        "buffer_id": "old", "token": "other-process", "written_at": mc.time.time() - 60.0,
        "payload": {"version": 1}, "system_image_size": None,
    }
    original = mc.moodboard_copybuffer.write_buffer
    mc.moodboard_copybuffer.write_buffer = lambda *a, **k: None
    try:
        assert mc.copy_selected(object()) == 1
    finally:
        mc.moodboard_copybuffer.write_buffer = original
    assert mc._SESSION["buffer_id"] is None
    assert mc.clipboard_source() == "session"


def test_a_session_copy_whose_images_are_all_gone_falls_through(fakes):
    mc.copy_selected(object())
    fakes["manifest"] = None
    fakes["images"].clear()
    assert mc.clipboard_source() is None
    # Text boxes and nodes need no datablock, so such a copy stays valid.
    fakes["payload"]["textboxes"] = [{"text": "hi"}]
    mc.copy_selected(object())
    fakes["manifest"] = None
    assert mc.clipboard_source() == "session"


def test_copy_of_nothing_leaves_the_previous_clipboard_alone(fakes, monkeypatch):
    mc.copy_selected(object())
    monkeypatch.setattr(mc.clipboard_snapshot, "build_snapshot",
                        lambda scene: {"version": 1, "media": [], "textboxes": [], "nodes": []})
    assert mc.copy_selected(object()) == 0
    assert len(fakes["written"]) == 1
    assert mc.clipboard_source() == "session"


# --------------------------------------------------------------------------- #
# The paste operator's arbitration with the OS clipboard
# --------------------------------------------------------------------------- #


def test_a_newer_picture_on_the_os_clipboard_outranks_the_moodboard_clipboard():
    """The copy put its first still on the OS clipboard and recorded its size;
    a different picture there was copied later in another application and is
    what the user means. With nothing recorded the moodboard clipboard wins,
    as Blender's own copy buffer always does."""
    source = (MOODBOARD / "ui/operators/image_ops.py").read_text(encoding="utf-8")
    execute = source.split("class MIXIE_OT_moodboard_paste_image")[1]
    assert "clipboard_exported_size()" in execute
    assert "_grab_external_clipboard()" in execute
    assert "external_is_newer = clip_img is not None and not _is_our_export(clip_img, exported)" in execute
    assert "if not external_is_newer:" in execute
    assert execute.index("paste_clipboard(scene, anchor=anchor)") < execute.index("if clip_img is None:")

    from mixar.modules.moodboard.ui.operators import image_ops

    class _Pic:
        def __init__(self, size):
            self.size = size

    assert image_ops._is_our_export(_Pic((1000, 500)), (1000, 500)) is True
    assert image_ops._is_our_export(_Pic((640, 480)), (1000, 500)) is False
    assert image_ops._is_our_export(["C:/photo.png"], (1000, 500)) is False
    assert image_ops._is_our_export(_Pic((1000, 500)), None) is False


def test_the_copy_operator_is_one_call_and_admits_nodes():
    source = (MOODBOARD / "ui/operators/clipboard_ops.py").read_text(encoding="utf-8")
    assert "copy_selected(context.scene)" in source
    assert "selected_action_nodes(scene)" in source
    # The OS export moved INTO copy_selected so its size is recorded with the
    # copy; the operator must not export a second time.
    assert "copy_blender_image_to_system_clipboard" not in source
    clipboard = (MOODBOARD / "core/moodboard_clipboard.py").read_text(encoding="utf-8")
    assert "copy_blender_image_to_system_clipboard(image, scene)" in clipboard


def test_the_keymap_and_menus_route_through_the_one_pair_of_operators():
    keymap = (MOODBOARD / "ui/keymap.py").read_text(encoding="utf-8")
    menus = (MOODBOARD / "ui/moodboard_menus.py").read_text(encoding="utf-8")
    assert keymap.count("'mixie.moodboard_copy_image'") == 1
    assert keymap.count("'mixie.moodboard_paste_image'") == 1
    assert '"mixie.moodboard_copy_image"' in menus
    assert '"mixie.moodboard_paste_image"' in menus
