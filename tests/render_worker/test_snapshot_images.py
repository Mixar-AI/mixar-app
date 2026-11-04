# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dirty images in a worker snapshot: byte images travel as uint8 and come
back bit-exact, old float32 manifests still load, and a preview snapshot is
reused while every dirty image holds the pixels it was written with."""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from mixar.modules.common.render_worker import snapshot, worker_jobs


class _Pixels:
    def __init__(self, data):
        self.data = np.asarray(data, dtype=np.float32)

    def foreach_get(self, buffer):
        buffer[:] = self.data

    def foreach_set(self, buffer):
        self.data = np.array(buffer, dtype=np.float32)


def _image(name, data, *, is_float=False, size=(4, 2), channels=4):
    return SimpleNamespace(name=name, size=size, channels=channels, is_float=is_float,
                           pixels=_Pixels(data), colorspace_settings=SimpleNamespace(name="sRGB"),
                           alpha_mode="STRAIGHT", type="IMAGE", source="FILE", is_dirty=True,
                           has_data=True, update=lambda: None)


def _byte_pixels(seed=0, count=32):
    # What Blender's pixels API returns for a byte image: n * (1.0f / 255.0f).
    return np.random.default_rng(seed).integers(0, 256, count).astype(np.float32) * np.float32(1.0 / 255.0)


def _restore(monkeypatch, folder, manifest, targets):
    path = os.path.join(folder, "images.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    fake = MagicMock(name="bpy")
    fake.data.images.get = lambda name: targets.get(name)
    monkeypatch.setattr(worker_jobs, "bpy", fake)
    return worker_jobs.restore_images(path)


def test_a_byte_image_travels_as_uint8_and_comes_back_exact(tmp_path, monkeypatch):
    painted = _image("painted", _byte_pixels())
    hdr = _image("hdr", np.linspace(-1.0, 4.0, 32), is_float=True)
    manifest, keys = snapshot._write_images([painted, hdr], str(tmp_path))
    assert [m["dtype"] for m in manifest] == ["uint8", "float32"]
    assert os.path.getsize(tmp_path / manifest[0]["file"]) == 32  # a byte per channel
    assert os.path.getsize(tmp_path / manifest[1]["file"]) == 32 * 4
    assert len(keys) == 2
    targets = {"painted": _image("painted", np.zeros(32)),
               "hdr": _image("hdr", np.zeros(32), is_float=True)}
    assert _restore(monkeypatch, str(tmp_path), manifest, targets) == 2
    assert np.array_equal(targets["painted"].pixels.data, painted.pixels.data)
    assert np.array_equal(targets["hdr"].pixels.data, hdr.pixels.data)


def test_byte_pixels_outside_0_1_are_clipped(tmp_path):
    image = _image("odd", np.array([-0.2, 1.7] + [0.5] * 30))
    manifest, _ = snapshot._write_images([image], str(tmp_path))
    raw = np.fromfile(tmp_path / manifest[0]["file"], dtype=np.uint8)
    assert raw[0] == 0 and raw[1] == 255 and raw[2] == 128


def test_a_manifest_written_before_dtype_still_loads_as_float32(tmp_path, monkeypatch):
    data = np.linspace(0.0, 1.0, 32).astype(np.float32)
    data.tofile(tmp_path / "image_0000.f32")
    manifest = [{"name": "old", "file": "image_0000.f32", "width": 4, "height": 2, "channels": 4,
                 "float": False, "colorspace": "sRGB", "alpha_mode": "STRAIGHT"}]
    targets = {"old": _image("old", np.zeros(32))}
    assert _restore(monkeypatch, str(tmp_path), manifest, targets) == 1
    assert np.array_equal(targets["old"].pixels.data, data)


# --------------------------------------------------------------------------
# Reuse while dirty images are unchanged
# --------------------------------------------------------------------------

@pytest.fixture
def reuse(monkeypatch, tmp_path):
    images = [_image("painted", _byte_pixels(1))]
    fake = MagicMock(name="bpy")
    fake.data.images = images
    monkeypatch.setattr(snapshot, "bpy", fake)
    monkeypatch.setattr(snapshot, "_cached", {})
    monkeypatch.setattr(snapshot, "_users", {})
    writes = []

    def write(purpose):
        folder = tmp_path / ("snapshots/w%d" % len(writes))
        folder.mkdir(parents=True)
        (folder / "s.blend").write_bytes(b"blend")
        _manifest, keys = snapshot._write_images(snapshot.dirty_images(), str(folder))
        record = {"folder": str(folder), "path": str(folder / "s.blend"), "images": "",
                  "image_count": len(keys), "image_keys": keys, "bytes": 5, "save_s": 1.0,
                  "images_s": 1.0}
        writes.append(record)
        return record

    monkeypatch.setattr(snapshot, "write", write)
    return SimpleNamespace(images=images, writes=writes)


def test_unchanged_dirty_images_reuse_the_snapshot(reuse):
    first = snapshot.write_or_reuse("preview", lambda: ("same",))
    again = snapshot.write_or_reuse("preview", lambda: ("same",))
    assert first["reused"] is False and again["reused"] is True
    assert again["save_s"] == 0.0 and len(reuse.writes) == 1


def test_a_changed_pixel_writes_a_new_snapshot(reuse):
    snapshot.write_or_reuse("preview", lambda: ("same",))
    data = reuse.images[0].pixels.data.copy()
    data[5] = 1.0 - data[5]
    reuse.images[0].pixels.data = data
    assert snapshot.write_or_reuse("preview", lambda: ("same",))["reused"] is False
    assert len(reuse.writes) == 2


def test_a_newly_dirty_image_writes_a_new_snapshot(reuse):
    snapshot.write_or_reuse("preview", lambda: ("same",))
    reuse.images.append(_image("generated", _byte_pixels(2)))
    assert snapshot.write_or_reuse("preview", lambda: ("same",))["reused"] is False


def test_a_scene_change_writes_without_reading_pixels(reuse, monkeypatch):
    snapshot.write_or_reuse("preview", lambda: ("before",))
    read = []
    monkeypatch.setattr(snapshot, "image_keys", lambda images: read.append(images) or [])
    assert snapshot.write_or_reuse("preview", lambda: ("after",))["reused"] is False
    assert not read, "a fingerprint mismatch needs no key"
