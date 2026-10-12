# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Context FILES: single attached files published as one synthetic "Attached
files" folder (``modules/context_folder/core/{files,file_set,registry}``)."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mixar.modules.context_folder import constants
from mixar.modules.context_folder.core import attach, files, grants, indexer, manifest, paths, rpc, video
from mixar.modules.context_folder.core.errors import ContextFolderError
from mixar.modules.context_folder.core.file_set import FileSet, local_roots
from mixar.modules.context_folder.core.registry import FolderRegistry, set_registry_for_tests
from test_context_folder import _Folders, _scene
from test_context_folder_video import _fake_decoder

ROOT = Path(__file__).resolve().parents[1]
BUBBLE = ROOT / "src/source/blender/editors/space_agent_bubble"


@pytest.fixture
def registry(tmp_path):
    registry = FolderRegistry(tmp_path / "registry" / "context_folders.json")
    set_registry_for_tests(registry)
    grants.clear()
    indexer.clear_cache()
    yield registry
    set_registry_for_tests(None)
    grants.clear()
    indexer.clear_cache()


@pytest.fixture
def workdir(tmp_path):
    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    (work / "notes.txt").write_text("line one\nshield is round\nline three\n")
    (work / "clip.mp4").write_bytes(b"not really mp4 bytes")
    (work / "sub" / "clip.mp4").write_bytes(b"another clip")
    (work / "document.pdf").write_bytes(b"%PDF-1.4")
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 200, 30)).save(buffer, format="PNG")
    (work / "still.png").write_bytes(buffer.getvalue())
    Image.new("P", (16, 16)).save(work / "anim.gif", format="GIF")
    (work / ".secret.txt").write_text("hidden")
    return work


def _attach(scene, path):
    result = files.attach_file(scene, str(path))
    assert result["success"], result
    return result


# ── registry: files persist beside folders ───────────────────────────────

def test_file_entries_persist_and_reload_beside_folders(registry, workdir):
    folder_id = registry.register(workdir)
    file_id = registry.register_file(workdir / "clip.mp4")
    assert registry.register_file(workdir / "sub" / ".." / "clip.mp4") == file_id
    on_disk = json.loads(registry.path.read_text())
    assert on_disk["folders"][folder_id]["root"] == str(workdir.resolve())
    assert on_disk["files"][file_id]["file"] == str((workdir / "clip.mp4").resolve())
    reloaded = FolderRegistry(registry.path)
    assert reloaded.resolve(folder_id) == workdir.resolve()
    assert reloaded.resolve_file(file_id) == (workdir / "clip.mp4").resolve()
    with pytest.raises(ContextFolderError) as unknown:
        reloaded.resolve_file("nope")
    assert unknown.value.code == "file_unknown"
    (workdir / "clip.mp4").unlink()
    with pytest.raises(ContextFolderError) as gone:
        reloaded.resolve_file(file_id)
    assert gone.value.code == "file_unavailable"
    with pytest.raises(ContextFolderError):
        registry.register_file(workdir)  # a directory is not a file


def test_the_old_folders_only_file_shape_still_loads(registry, workdir):
    registry.path.parent.mkdir(parents=True)
    registry.path.write_text(json.dumps({"folders": {"old": {"root": str(workdir)}}, "future_key": 1}))
    assert registry.resolve("old") == workdir.resolve()
    assert registry.register_file(workdir / "notes.txt")  # adds "files" without losing "folders"
    assert json.loads(registry.path.read_text())["folders"]["old"]["root"] == str(workdir)


# ── FileSet through the resolver, indexer and reader ─────────────────────

def test_a_published_set_resolves_indexes_and_serves_only_its_members(registry, workdir):
    clip = registry.register_file(workdir / "clip.mp4")
    notes = registry.register_file(workdir / "notes.txt")
    registry.publish_file_set("set-1", [("clip.mp4", clip), ("notes.txt", notes), ("ghost.txt", "unknown-id")])
    root = registry.resolve("set-1")
    assert isinstance(root, FileSet) and registry.available("set-1")
    assert set(root.files) == {"clip.mp4", "notes.txt"}
    index = indexer.index_folder(root)
    assert {(e["path"], e["kind"]) for e in index.files} == {("clip.mp4", "video"), ("notes.txt", "text")}
    assert not index.truncated and index.total_bytes == 20 + len("line one\nshield is round\nline three\n")
    assert paths.existing_file(root, "notes.txt") == (workdir / "notes.txt").resolve()
    for bad in ("still.png", "sub/clip.mp4"):
        with pytest.raises(ContextFolderError) as error:
            paths.existing_file(root, bad)
        assert error.value.code == "not_found"
    with pytest.raises(ContextFolderError) as traversal:
        paths.existing_file(root, "../clip.mp4")
    assert traversal.value.code == "invalid_path"
    assert local_roots(root) == [str(workdir.resolve())]


def test_a_vanished_member_is_omitted_and_the_set_stays_available(registry, workdir):
    clip = registry.register_file(workdir / "clip.mp4")
    notes = registry.register_file(workdir / "notes.txt")
    registry.publish_file_set("set-1", [("clip.mp4", clip), ("notes.txt", notes)])
    (workdir / "clip.mp4").unlink()
    root = registry.resolve("set-1")
    assert list(root.files) == ["notes.txt"]
    assert [e["path"] for e in indexer.index_folder(root).files] == ["notes.txt"]
    registry.publish_file_set("empty", [])
    assert indexer.index_folder(registry.resolve("empty")).files == []
    assert manifest.describe_folder("empty", "x")["available"] is True


# ── attach_file ──────────────────────────────────────────────────────────

def test_attach_is_idempotent_refuses_hidden_and_directories_and_names_uniquely(registry, workdir):
    scene = _scene()
    first = _attach(scene, workdir / "clip.mp4")
    assert (first["name"], first["kind"], first["already"]) == ("clip.mp4", "video", False)
    assert scene.mixie_context_files_id
    again = files.attach_file(scene, str(workdir / "sub" / ".." / "clip.mp4"))
    assert again["already"] and again["file_id"] == first["file_id"] and len(scene.mixie_context_files) == 1
    second = _attach(scene, workdir / "sub" / "clip.mp4")
    assert second["name"] == "clip (2).mp4" and second["file_id"] != first["file_id"]
    hidden = files.attach_file(scene, str(workdir / ".secret.txt"))
    assert not hidden["success"] and hidden["error"] == "Hidden files are not shared"
    folder = files.attach_file(scene, str(workdir))
    assert not folder["success"] and folder["error"] == "Choose a file to attach"
    assert not files.attach_file(scene, "")["success"]
    assert len(scene.mixie_context_files) == 2


def test_attach_is_capped(registry, workdir, monkeypatch):
    monkeypatch.setattr(files, "MAX_CONTEXT_FILES", 1)
    scene = _scene()
    _attach(scene, workdir / "clip.mp4")
    refused = files.attach_file(scene, str(workdir / "notes.txt"))
    assert not refused["success"] and refused["error_args"] == {"count": 1}
    assert files.attach_file(scene, str(workdir / "clip.mp4"))["already"]  # a re-attach is never refused


# ── manifest + grant ─────────────────────────────────────────────────────

def test_manifest_appends_attached_files_last_path_free_and_grants_the_set(registry, workdir):
    scene = _scene()
    assert attach.attach_folder(scene, str(workdir / "sub"))["success"]
    _attach(scene, workdir / "clip.mp4")
    _attach(scene, workdir / "notes.txt")
    context = attach.folder_context_for_send(scene, "session-1")
    wire = json.dumps(context)
    assert str(workdir) not in wire
    assert [f["name"] for f in context["folders"]] == ["sub", constants.ATTACHED_FILES_LABEL]
    entry = context["folders"][-1]
    assert entry["folder_id"] == scene.mixie_context_files_id and entry["available"]
    assert entry["kinds"] == {"video": 1, "text": 1}
    assert {f["path"] for f in entry["files"]} == {"clip.mp4", "notes.txt"}
    assert entry["notes"][0]["path"] == "notes.txt" and "shield" in entry["notes"][0]["excerpt"]
    assert grants.granted("session-1") == {context["folders"][0]["folder_id"], scene.mixie_context_files_id}


def test_a_user_folder_named_attached_files_yields_the_plain_label_to_the_set(registry, workdir, tmp_path):
    clash = tmp_path / constants.ATTACHED_FILES_LABEL
    clash.mkdir()
    scene = _scene()
    assert attach.attach_folder(scene, str(clash))["success"]
    _attach(scene, workdir / "clip.mp4")
    names = [f["name"] for f in manifest.build_folder_context(scene)["folders"]]
    assert names == [f"{constants.ATTACHED_FILES_LABEL} (2)", constants.ATTACHED_FILES_LABEL]


def test_no_files_means_no_synthetic_folder_and_no_set_grant(registry, workdir):
    scene = _scene()
    assert attach.attach_folder(scene, str(workdir))["success"]
    context = attach.folder_context_for_send(scene, "session-1")
    assert len(context["folders"]) == 1 and len(grants.granted("session-1")) == 1
    _attach(scene, workdir / "clip.mp4")
    assert files.detach_file(scene, scene.mixie_context_files[0].file_id)
    assert len(manifest.build_folder_context(scene)["folders"]) == 1


# ── RPCs on the set ──────────────────────────────────────────────────────

@pytest.fixture
def attached(registry, workdir):
    scene = _scene()
    for name in ("notes.txt", "clip.mp4", "anim.gif", "still.png", "document.pdf"):
        _attach(scene, workdir / name)
    attach.folder_context_for_send(scene, "session-1")
    calls = []
    video.set_decoder_for_tests(_fake_decoder(calls))
    yield scene, scene.mixie_context_files_id
    video.reset_decoder_for_tests()


def _call(method, set_id, **params):
    return rpc.dispatch(method, {"session_id": "session-1", "folder_id": set_id, **params})


def test_rpcs_read_view_and_sample_attached_files(attached, workdir):
    scene, set_id = attached
    listed = _call(constants.RPC_LIST, set_id)
    assert listed["success"] and listed["total"] == 5 and not listed["index_truncated"]
    assert _call(constants.RPC_LIST, set_id, subfolder="sub")["files"] == []  # a set has no subfolders
    read = _call(constants.RPC_READ, set_id, path="notes.txt", start_line=2, end_line=2)
    assert read["text"] == "    2  shield is round"
    assert _call(constants.RPC_SEARCH, set_id, query="shield")["matches"][0]["path"] == "notes.txt"
    sampled = _call(constants.RPC_VIEW_VIDEO, set_id, path="clip.mp4", count=2)
    assert sampled["success"] and [f["frame_index"] for f in sampled["frames"]] == [0, 239]
    for name in ("anim.gif", "still.png"):
        viewed = _call(constants.RPC_VIEW_IMAGE, set_id, path=name)
        assert viewed["success"] and viewed["mime"] == "image/jpeg", viewed
    assert _call(constants.RPC_READ, set_id, path="document.pdf")["error"]["code"] == "not_text"
    assert _call(constants.RPC_READ, set_id, path="sub/clip.mp4")["error"]["code"] == "not_found"
    assert str(workdir) not in json.dumps(_call(constants.RPC_READ, set_id, path="../notes.txt"))
    other = rpc.dispatch(constants.RPC_LIST, {"session_id": "session-2", "folder_id": set_id})
    assert other["error"]["code"] == "folder_not_attached"


def test_detach_removes_the_member_from_the_next_manifest_and_reads(attached):
    scene, set_id = attached
    clip = next(item.file_id for item in scene.mixie_context_files if item.name == "clip.mp4")
    assert files.detach_file(scene, clip) and not files.detach_file(scene, clip)
    entry = manifest.build_folder_context(scene)["folders"][-1]
    assert "clip.mp4" not in {f["path"] for f in entry["files"]}
    # The grant is untouched (same set id); the member itself is simply gone.
    assert _call(constants.RPC_VIEW_VIDEO, set_id, path="clip.mp4")["error"]["code"] == "not_found"
    assert _call(constants.RPC_READ, set_id, path="notes.txt")["success"]


def test_detaching_the_last_file_leaves_nothing_readable(attached, registry, workdir):
    scene, set_id = attached
    for item in list(scene.mixie_context_files):
        assert files.detach_file(scene, item.file_id)
    assert scene.mixie_context_files_id == set_id  # the id outlives its members
    # The empty membership is published too: a stale set must never keep
    # serving a detached file, whatever grant a session still holds.
    assert indexer.index_folder(registry.resolve(set_id)).files == []
    for method, params in ((constants.RPC_READ, {"path": "notes.txt"}),
                           (constants.RPC_VIEW_VIDEO, {"path": "clip.mp4"}),
                           (constants.RPC_VIEW_IMAGE, {"path": "still.png"})):
        assert _call(method, set_id, **params)["error"]["code"] == "not_found", method
    assert _call(constants.RPC_LIST, set_id)["files"] == []
    assert len(manifest.build_folder_context(scene)["folders"]) == 0
    # A later attach publishes the new membership under the SAME id.
    _attach(scene, workdir / "notes.txt")
    attach.folder_context_for_send(scene, "session-1")
    assert _call(constants.RPC_READ, set_id, path="notes.txt")["success"]
    assert _call(constants.RPC_READ, set_id, path="clip.mp4")["error"]["code"] == "not_found"


# ── wiring (source level) ────────────────────────────────────────────────

def test_the_island_draws_file_chips_and_every_entry_routes_files():
    items = (BUBBLE / "agent_bubble_reference_items.cc").read_text()
    assert '"mixie_context_files"' in items and '"CONTEXT_FILE"' in items
    draw = (BUBBLE / "agent_bubble_references.cc").read_text()
    assert '"mixie_chat.remove_context_file"' in draw and 'RNA_string_set(props, "file_id"' in draw
    assert '"reference_file"' in draw and 'IFACE_("Video context")' in draw
    assert '"mixie_context_files"' in (BUBBLE / "space_agent_bubble.cc").read_text()
    menu = (ROOT / "src/scripts/mixar/modules/context_folder/ui/menus/attach_menu.py").read_text()
    assert 'iface_("Files")' in menu
    dragdrop = (ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_dragdrop.cc").read_text()
    poll = dragdrop[dragdrop.index("static bool mixie_chat_image_drop_poll("):]
    assert "FILE_TYPE_MOVIE" not in poll[:poll.index("\n}\n")]
    ops = (ROOT / "src/scripts/mixar/modules/context_folder/ui/operators/context_folder_ops.py").read_text()
    assert 'bl_idname = "mixie_chat.remove_context_file"' in ops
    picker = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/image_ops.py").read_text()
    assert 'filter_glob: StringProperty(default=""' in picker and "attach_file(scene, filepath)" in picker
    sync = (ROOT / "src/scripts/mixar/modules/moodboard/core/chat_sync.py").read_text()
    assert "sync_selected_videos(scene)" in sync
