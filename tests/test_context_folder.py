# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Context folders: the path-free manifest, the grant-gated RPC, the reader
bounds and the attach/detach contract (``modules/context_folder``)."""

import base64
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mixar.modules.context_folder import constants
from mixar.modules.context_folder.core import attach, grants, indexer, manifest, paths, reader, rpc
from mixar.modules.context_folder.core.errors import ContextFolderError
from mixar.modules.context_folder.core.registry import FolderRegistry, set_registry_for_tests

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"


class _Folders(list):
    def add(self):
        item = SimpleNamespace(folder_id="", name="")
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


def _scene(session_id="session-1"):
    return SimpleNamespace(mixie_context_folders=_Folders(), mixie_session_id=session_id)


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Hero Refs"
    (root / "concept").mkdir(parents=True)
    (root / "README.md").write_text("# Hero\nA knight in green armour.\nScale: 1.8 m.\n")
    (root / "notes.txt").write_text("line one\nshield is round\nline three\n")
    (root / "concept" / "front.png").write_bytes(_png((640, 480)))
    (root / "concept" / "hero.fbx").write_bytes(b"fbx")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("secret")
    (root / ".hidden.txt").write_text("secret")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.js").write_text("x")
    return root


@pytest.fixture(autouse=True)
def _isolated(tmp_path):
    set_registry_for_tests(FolderRegistry(tmp_path / "registry" / "context_folders.json"))
    grants.clear()
    indexer.clear_cache()
    yield
    set_registry_for_tests(None)
    grants.clear()
    indexer.clear_cache()


def _png(size, color=(200, 40, 40, 255)):
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _attached(folder, session_id="session-1"):
    scene = _scene(session_id)
    result = attach.attach_folder(scene, str(folder))
    assert result["success"], result
    context = attach.folder_context_for_send(scene, session_id)
    return scene, result["folder_id"], context


# ── paths ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "/etc/passwd", "../outside.txt", "a/../../b", "C:/Windows/win.ini", "a\\b.txt",
    ".git/config", "sub/.hidden", "node_modules/x.js", "",
])
def test_relative_paths_refuse_absolute_traversal_and_hidden(value):
    with pytest.raises(ContextFolderError):
        paths.normalize_relative_path(value)


def test_relative_paths_normalize_to_one_posix_form():
    assert paths.normalize_relative_path("a//b/") == "a/b"
    assert paths.normalize_relative_path("/", allow_empty=True) == ""


def test_a_symlink_cannot_escape_the_root(folder, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    os.symlink(outside, folder / "link.txt")
    with pytest.raises(ContextFolderError) as error:
        paths.existing_file(folder, "link.txt")
    assert error.value.code == "path_escape"


# ── index + manifest ─────────────────────────────────────────────────────

def test_index_skips_hidden_ignored_and_linked_entries(folder, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", folder / "linked_dir")
    listed = {entry["path"] for entry in indexer.index_folder(folder).files}
    assert listed == {"README.md", "notes.txt", "blob.bin", "concept/front.png", "concept/hero.fbx"}


def test_index_reports_truncation_at_the_cap(folder, monkeypatch):
    monkeypatch.setattr(indexer, "MAX_INDEXED_FILES", 2)
    index = indexer.index_folder(folder, fresh=True)
    assert len(index.files) == 2 and index.truncated


def test_manifest_is_path_free_and_quotes_the_readme(folder):
    _, folder_id, context = _attached(folder)
    wire = json.dumps(context)
    assert str(folder) not in wire and str(folder.parent) not in wire
    assert context["version"] == constants.PROTOCOL_VERSION
    entry = context["folders"][0]
    assert entry["folder_id"] == folder_id and entry["name"] == "Hero Refs" and entry["available"]
    assert entry["kinds"] == {"text": 2, "image": 1, "model": 1, "other": 1}
    assert {f["path"] for f in entry["files"]} >= {"README.md", "concept/front.png"}
    assert entry["notes"][0]["path"] == "README.md"
    assert "knight in green armour" in entry["notes"][0]["excerpt"]


def test_duplicate_folder_names_get_distinct_labels():
    assert manifest.unique_labels(["refs", "refs", "a/b", ""]) == ["refs", "refs (2)", "a_b", "folder"]


def test_a_missing_folder_is_reported_unavailable(folder, tmp_path):
    scene, folder_id, _ = _attached(folder)
    folder.rename(tmp_path / "moved")
    entry = attach.folder_context_for_send(scene, "session-1")["folders"][0]
    assert entry == {"folder_id": folder_id, "name": "Hero Refs", "available": False}


# ── attach / detach / grants ─────────────────────────────────────────────

def test_attach_is_idempotent_and_bounded(folder, tmp_path, monkeypatch):
    scene = _scene()
    first = attach.attach_folder(scene, str(folder))
    again = attach.attach_folder(scene, str(folder))
    assert first["folder_id"] == again["folder_id"] and again["already"]
    assert len(scene.mixie_context_folders) == 1
    monkeypatch.setattr(attach, "MAX_FOLDERS", 1)
    other = tmp_path / "other"
    other.mkdir()
    refused = attach.attach_folder(scene, str(other))
    assert not refused["success"] and refused["error_args"] == {"count": 1}


def test_attach_refuses_a_drive_root_and_a_file(folder):
    assert not attach.attach_folder(_scene(), os.path.abspath(os.sep))["success"]
    assert not attach.attach_folder(_scene(), str(folder / "notes.txt"))["success"]


def test_rpc_serves_only_folders_granted_to_the_session(folder):
    scene, folder_id, _ = _attached(folder)
    ok = rpc.dispatch(constants.RPC_LIST, {"session_id": "session-1", "folder_id": folder_id})
    assert ok["success"] and ok["total"] == 5
    other = rpc.dispatch(constants.RPC_LIST, {"session_id": "session-2", "folder_id": folder_id})
    assert other["error"]["code"] == "folder_not_attached"
    assert attach.detach_folder(scene, folder_id)
    revoked = rpc.dispatch(constants.RPC_READ, {"session_id": "session-1", "folder_id": folder_id,
                                                "path": "README.md"})
    assert revoked["error"]["code"] == "folder_not_attached"


def test_rpc_errors_never_carry_the_root(folder):
    _, folder_id, _ = _attached(folder)
    for params in ({"path": "missing.txt"}, {"path": "../x"}, {"path": "blob.bin"}, {"path": "concept/hero.fbx"}):
        result = rpc.dispatch(constants.RPC_READ, {"session_id": "session-1", "folder_id": folder_id, **params})
        assert not result["success"] and str(folder) not in json.dumps(result), result
    assert rpc.dispatch("context_folder.delete", {})["error"]["code"] == "unknown_method"


# ── reader ───────────────────────────────────────────────────────────────

def test_read_returns_numbered_line_ranges(folder):
    result = reader.read_text(folder, "notes.txt", start_line=2, end_line=3)
    assert result["text"].splitlines() == ["    2  shield is round", "    3  line three"]
    assert (result["start_line"], result["end_line"], result["total_lines"]) == (2, 3, 3)
    empty = folder / "empty.md"
    empty.write_text("")
    assert reader.read_text(folder, "empty.md")["total_lines"] == 0


def test_read_is_bounded_and_reports_truncation(folder, monkeypatch):
    monkeypatch.setattr(reader, "MAX_READ_CHARS", 20)
    result = reader.read_text(folder, "notes.txt")
    assert result["truncated"] and result["end_line"] < 3


def test_search_matches_names_and_content(folder):
    result = reader.search(folder, "SHIELD")
    assert result["matches"] == [{"path": "notes.txt", "line": 2, "text": "shield is round"}]
    assert [m["path"] for m in reader.search(folder, "front")["name_matches"]] == ["concept/front.png"]
    with pytest.raises(ContextFolderError):
        reader.search(folder, "")


def test_list_filters_by_kind_and_subfolder(folder):
    result = reader.list_files(folder, subfolder="concept", kind="image")
    assert [f["path"] for f in result["files"]] == ["concept/front.png"]
    with pytest.raises(ContextFolderError):
        reader.list_files(folder, kind="spreadsheet")


def test_image_preview_is_a_downscaled_jpeg(folder):
    result = reader.preview_image(folder, "concept/front.png", max_dim=256)
    image = Image.open(io.BytesIO(base64.b64decode(result["image_base64"])))
    assert image.format == "JPEG" and max(image.size) == 256
    assert (result["width"], result["height"]) == (640, 480)
    with pytest.raises(ContextFolderError):
        reader.preview_image(folder, "notes.txt")


# ── wiring (source level: the transport needs a live socket) ─────────────

def test_send_stamps_folder_context_and_the_socket_routes_the_rpc():
    transport = (CHAT / "core/turn_transport.py").read_text()
    assert "folders.folder_context_for_send(scene, payload['session_id'])" in transport
    dispatch = (CHAT / "core/socket_dispatch.py").read_text()
    assert "method.startswith(CONTEXT_FOLDER_RPC_PREFIX)" in dispatch
    handshake = (CHAT / "core/socket_connection.py").read_text()
    assert "CONTEXT_FOLDER_CAPABILITY," in handshake


def test_the_island_paperclip_opens_the_attach_menu_and_draws_folder_chips():
    bubble = ROOT / "src/source/blender/editors/space_agent_bubble"
    assert '"mixie_chat.attach"' in (bubble / "space_agent_bubble.cc").read_text()
    items = (bubble / "agent_bubble_reference_items.cc").read_text()
    assert '"mixie_context_folders"' in items and '"FOLDER"' in items
    draw = (bubble / "agent_bubble_references.cc").read_text()
    assert '"mixie_chat.remove_context_folder"' in draw and 'RNA_string_set(props, "folder_id"' in draw


# ── importer (bpy stubbed) ───────────────────────────────────────────────

def _fake_agent_import(monkeypatch):
    """The real module imports the auth/keyring chain; the importer only needs
    its importer map and shared entry point."""
    import sys

    fake = SimpleNamespace(_IMPORTERS={".fbx": ("import_scene", "fbx"), ".obj": ("wm", "obj_import")},
                           import_model_path=None)
    monkeypatch.setitem(sys.modules, "mixar.modules.space_mixie_chat.core.agent_import", fake)
    return fake


def test_import_requires_the_grant_and_an_importable_kind(folder):
    from mixar.modules.context_folder.core import importer

    _, folder_id, _ = _attached(folder)
    refused = importer.import_folder_file("session-2", folder_id, "concept/front.png")
    assert refused["error"]["code"] == "folder_not_attached"
    text = importer.import_folder_file("session-1", folder_id, "notes.txt")
    assert text["error"]["code"] == "not_importable"


def test_import_loads_an_image_and_runs_the_shared_model_importer(folder, monkeypatch):
    import sys

    from mixar.modules.context_folder.core import importer

    agent_import = _fake_agent_import(monkeypatch)
    _, folder_id, _ = _attached(folder)
    image = SimpleNamespace(name="front.png", size=(640, 480))
    loaded = []
    fake_bpy = SimpleNamespace(data=SimpleNamespace(images=SimpleNamespace(
        load=lambda path, check_existing: loaded.append(path) or image)))
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    result = importer.import_folder_file("session-1", folder_id, "concept/front.png")
    assert result == {"success": True, "image_name": "front.png", "width": 640, "height": 480,
                      "path": "concept/front.png"}
    assert loaded == [str(folder / "concept" / "front.png")]

    calls = []
    monkeypatch.setattr(agent_import, "import_model_path", lambda path, importers: calls.append(
        (path, importers)) or {"success": True, "imported_object_names": ["Hero"], "object_count": 1,
                               "file_basename": "hero.fbx"})
    model = importer.import_folder_file("session-1", folder_id, "concept/hero.fbx")
    assert model == {"success": True, "imported_object_names": ["Hero"], "object_count": 1,
                     "path": "concept/hero.fbx"}
    assert calls[0][0].endswith("hero.fbx") and ".stl" in calls[0][1] and ".fbx" in calls[0][1]


def test_a_failed_import_never_returns_the_root(folder, monkeypatch):
    from mixar.modules.context_folder.core import importer

    agent_import = _fake_agent_import(monkeypatch)
    _, folder_id, _ = _attached(folder)
    monkeypatch.setattr(agent_import, "import_model_path", lambda path, importers: {
        "success": False, "error": f"Cannot read {path}"})
    result = importer.import_folder_file("session-1", folder_id, "concept/hero.fbx")
    assert result["error"]["code"] == "import_failed" and str(folder) not in result["error"]["message"]
