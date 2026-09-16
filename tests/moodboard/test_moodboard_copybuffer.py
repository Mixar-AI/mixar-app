# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The on-disk moodboard copy buffer -- the cross-instance half of copy/paste.

Runs against the suite's `bpy` mock with `bpy.data.images`, `bpy.app.tempdir`
and `bpy.data.libraries` replaced per test, so the file protocol (where the
files live, what goes into the partial .blend, what the manifest carries, how
appended datablocks map back to recorded names) is pinned without Blender.
"""

import json
import os
from types import SimpleNamespace

import pytest

from mixar.modules.moodboard.core import moodboard_copybuffer as cb


class _Image:
    def __init__(self, name, *, source='FILE', packed=True, dirty=False, filepath=""):
        self.name = name
        self.source = source
        self.packed_file = object() if packed else None
        self.is_dirty = dirty
        self.filepath = filepath
        self.frame_duration = 1
        self.packed = 0

    def pack(self):
        self.packed += 1
        self.packed_file = object()


@pytest.fixture
def blender(monkeypatch, tmp_path):
    """A fake bpy: session tempdir under tmp_path, a dict image library, and a
    recording `libraries.write` / a scripted `libraries.load`.

    Patched through the MODULE's own `bpy` reference: other suites swap
    `sys.modules['bpy']`, so a fresh `import bpy` here can be a different mock
    from the one the module bound at import time."""
    bpy = cb.bpy

    session = tmp_path / "blender_abc123"
    session.mkdir()
    monkeypatch.setattr(bpy.app, "tempdir", str(session) + os.sep, raising=False)
    monkeypatch.setattr(bpy.path, "abspath", lambda p: p, raising=False)

    library = {}
    monkeypatch.setattr(bpy.data, "images", library, raising=False)

    writes = []

    def write(path, datablocks, **kwargs):
        writes.append((path, set(datablocks), kwargs))
        with open(path, "wb") as handle:
            handle.write(b"BLENDER")

    libraries = SimpleNamespace(write=write, load=None)
    monkeypatch.setattr(bpy.data, "libraries", libraries, raising=False)
    return SimpleNamespace(tmp=tmp_path, images=library, writes=writes, libraries=libraries)


def test_the_buffer_lives_in_the_shared_temp_base_not_the_session_dir(blender):
    """`bpy.app.tempdir` is per process; its PARENT is the directory Blender's
    own copybuffer.blend uses, and the only place two instances meet."""
    assert cb.buffer_directory() == str(blender.tmp)
    assert cb.blend_path() == str(blender.tmp / "mixar_moodboard_copybuffer.blend")
    assert cb.manifest_path() == str(blender.tmp / "mixar_moodboard_copybuffer.json")


def test_write_buffer_writes_the_images_absolute_then_the_manifest(blender):
    still = _Image("photo.png")
    clip = _Image("clip.mp4", source='MOVIE', packed=False, filepath="//clips/clip.mp4")
    blender.images.update({"photo.png": still, "clip.mp4": clip})
    payload = {"version": 1, "media": [{"image_name": "photo.png"}], "nodes": [], "textboxes": []}

    buffer_id = cb.write_buffer(payload, ["photo.png", "clip.mp4", "missing.png"], system_image_size=(1000, 500))

    assert buffer_id
    path, datablocks, kwargs = blender.writes[0]
    assert path == cb.blend_path()
    assert datablocks == {still, clip}
    # A movie referenced relative to the SOURCE .blend must still resolve from
    # another file in another directory.
    assert kwargs == {"path_remap": 'ABSOLUTE', "fake_user": False, "compress": False}

    manifest = json.loads(open(cb.manifest_path(), encoding="utf-8").read())
    assert manifest["version"] == cb.MANIFEST_VERSION
    assert manifest["buffer_id"] == buffer_id
    assert manifest["token"] == cb.PROCESS_TOKEN
    assert manifest["pid"] == os.getpid()
    assert manifest["blend"] == "mixar_moodboard_copybuffer.blend"
    assert manifest["image_names"] == ["photo.png", "clip.mp4"]
    assert manifest["system_image_size"] == [1000, 500]
    assert manifest["payload"] == payload
    assert not [p for p in os.listdir(blender.tmp) if p.endswith(".tmp")]


def test_movies_are_never_packed_but_pixel_only_stills_are(blender):
    """A generated still whose pixels live only in memory would be written as
    an empty reference; a movie cannot be packed at all."""
    packed = _Image("packed.png")
    dirty = _Image("edited.png", dirty=True)
    on_disk_only = _Image("ondisk.png", packed=False, filepath=str(blender.tmp / "x.png"))
    open(on_disk_only.filepath, "wb").close()
    memory_only = _Image("generated.png", packed=False)
    clip = _Image("clip.mp4", source='MOVIE', packed=False)

    cb.prepare_images_for_write([packed, dirty, on_disk_only, memory_only, clip, None])

    assert packed.packed == 0
    assert dirty.packed == 1
    assert on_disk_only.packed == 0
    assert memory_only.packed == 1
    assert clip.packed == 0


def test_a_copy_without_images_writes_no_blend(blender):
    payload = {"version": 1, "media": [], "nodes": [], "textboxes": [{"text": "hi"}]}
    assert cb.write_buffer(payload, [])
    assert blender.writes == []
    assert cb.read_manifest()["blend"] == ""


def test_a_failed_blend_write_leaves_no_manifest_claiming_it(blender):
    blender.images["photo.png"] = _Image("photo.png")

    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    blender.libraries.write = boom
    assert cb.write_buffer({"version": 1}, ["photo.png"]) is None
    assert cb.read_manifest() is None


def test_read_manifest_rejects_garbage_and_other_versions(blender):
    assert cb.read_manifest() is None
    open(cb.manifest_path(), "w").write("not json")
    assert cb.read_manifest() is None
    json.dump({"version": 99, "buffer_id": "x", "payload": {}}, open(cb.manifest_path(), "w"))
    assert cb.read_manifest() is None
    json.dump({"version": 1, "buffer_id": "", "payload": {}}, open(cb.manifest_path(), "w"))
    assert cb.read_manifest() is None
    json.dump({"version": 1, "buffer_id": "x", "payload": {"version": 1}}, open(cb.manifest_path(), "w"))
    assert cb.read_manifest()["buffer_id"] == "x"


def test_is_own_recognises_this_process_only():
    assert cb.is_own({"token": cb.PROCESS_TOKEN}) is True
    assert cb.is_own({"token": "someone-else"}) is False
    assert cb.is_own(None) is False


class _Loader:
    """Scripted `bpy.data.libraries.load`: `data_from.images` lists what the
    .blend holds; the appended datablocks come back in request order, renamed
    where the name is taken -- exactly as Blender does it."""

    def __init__(self, present, rename=()):
        self.present = present
        self.rename = set(rename)
        self.requested = None

    def __call__(self, path, link=False):
        assert link is False
        loader = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.data_from = SimpleNamespace(images=list(loader.present))
                self_inner.data_to = SimpleNamespace(images=[])
                return self_inner.data_from, self_inner.data_to

            def __exit__(self_inner, *_exc):
                loader.requested = list(self_inner.data_to.images)
                self_inner.data_to.images = [
                    _Image(name + ".001" if name in loader.rename else name)
                    for name in loader.requested
                ]
                return False

        return _Ctx()


def test_import_maps_recorded_names_onto_appended_possibly_renamed_datablocks(blender):
    loader = _Loader(present=["photo.png", "clip.mp4"], rename={"photo.png"})
    blender.libraries.load = loader
    open(cb.blend_path(), "wb").write(b"BLENDER")
    manifest = {"blend": "mixar_moodboard_copybuffer.blend",
                "image_names": ["photo.png", "clip.mp4", "vanished.png"]}

    mapping = cb.import_buffer_images(manifest)

    # Only names the .blend actually carries are requested...
    assert loader.requested == ["photo.png", "clip.mp4"]
    # ...and the RECORDED name maps to the datablock however it was renamed.
    assert mapping["photo.png"].name == "photo.png.001"
    assert mapping["clip.mp4"].name == "clip.mp4"
    assert "vanished.png" not in mapping


def test_import_is_empty_without_a_blend_or_when_the_file_is_gone(blender):
    blender.libraries.load = _Loader(present=["photo.png"])
    assert cb.import_buffer_images({"blend": "", "image_names": ["photo.png"]}) == {}
    assert cb.import_buffer_images({"blend": "mixar_moodboard_copybuffer.blend", "image_names": []}) == {}
    # Manifest present, .blend removed by the OS: no crash, nothing appended.
    assert cb.import_buffer_images({"blend": "mixar_moodboard_copybuffer.blend", "image_names": ["photo.png"]}) == {}


def test_manifest_write_is_atomic(blender, monkeypatch):
    """A reader in another process must never see a half-written manifest:
    the JSON goes to a sibling temp name and is renamed into place."""
    replaced = []
    real_replace = os.replace

    def replace(src, dst):
        replaced.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(cb.os, "replace", replace)
    assert cb.write_buffer({"version": 1, "media": [], "nodes": [], "textboxes": []}, [])
    (src, dst), = replaced
    assert dst == cb.manifest_path()
    assert src.startswith(dst) and src.endswith(".tmp")
