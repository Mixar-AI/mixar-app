# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dirty-image pixels are written off the main thread.

Per 4K image, measured in the app: the pixel read is ~4 ms, the byte -> uint8
conversion ~48 ms and the file write ~75 ms. Every scene edit made the next
agent render redo all of it on the main thread (three 4K paint images: 0.25 s
per render). Now only the read runs there; a background thread converts and
writes, hard-linking images unchanged since the previous snapshot, and the
supervisor dispatches the job once :func:`snapshot.ready` says the files exist.
"""

import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from mixar.modules.common.render_worker import snapshot, supervisor

from test_snapshot_images import _byte_pixels, _image
from test_supervisor import _job, _wait, sup  # noqa: F401 (fixture re-export)


@pytest.fixture
def doc(monkeypatch, tmp_path):
    images = [_image("painted", _byte_pixels(1)),
              _image("hdr", np.linspace(0.0, 2.0, 32), is_float=True)]
    fake = MagicMock(name="bpy")
    fake.data.images = images

    def save_as_mainfile(filepath, **_kwargs):
        with open(filepath, "wb") as handle:
            handle.write(b"BLENDER")
        return {"FINISHED"}

    fake.ops.wm.save_as_mainfile = save_as_mainfile
    monkeypatch.setattr(snapshot, "bpy", fake)
    monkeypatch.setattr(supervisor, "root_dir", lambda: str(tmp_path))
    for name, value in (("_cached", {}), ("_users", {}), ("_retired", []), ("_writers", [])):
        monkeypatch.setattr(snapshot, name, value)
    return SimpleNamespace(images=images)


def _gate(monkeypatch):
    """Hold the background writer (never the calling thread) until released."""
    release = threading.Event()
    real = snapshot._store_one

    def held(*args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            release.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(snapshot, "_store_one", held)
    return release


def _settle(record):
    deadline = time.monotonic() + 5
    while not snapshot.ready(record):
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_the_main_thread_returns_before_the_pixels_are_written(doc, monkeypatch):
    release = _gate(monkeypatch)
    record = snapshot.write("preview", background=True)
    assert os.path.isfile(record["path"]), "the .blend is saved on the calling thread"
    assert snapshot.ready(record) is False
    assert not os.path.exists(record["images"]), "no pixel file written on the main thread"
    release.set()
    _settle(record)
    manifest = json.loads(open(record["images"]).read())
    assert [m["dtype"] for m in manifest] == ["uint8", "float32"]
    assert os.path.getsize(os.path.join(record["folder"], manifest[0]["file"])) == 32
    assert len(record["image_keys"]) == 2


def test_an_unchanged_image_is_hard_linked_from_the_previous_snapshot(doc):
    first = snapshot.write_or_reuse("preview", lambda: ("a",), background=True)
    _settle(first)
    painted_inode = os.stat(first["image_files"]["painted"][1]).st_ino
    data = doc.images[1].pixels.data.copy()
    data[3] += 1.0
    doc.images[1].pixels.data = data  # the HDR changed, the paint did not
    second = snapshot.write_or_reuse("preview", lambda: ("b",), background=True)
    _settle(second)
    old, new = first["image_files"], second["image_files"]
    assert os.stat(new["painted"][1]).st_ino == painted_inode, "linked, not rewritten"
    assert new["hdr"][0] != old["hdr"][0]
    assert np.array_equal(np.fromfile(new["hdr"][1], dtype=np.float32), data)


def test_a_replaced_snapshot_outlives_a_writer_that_may_link_from_it(doc, monkeypatch):
    first = snapshot.write_or_reuse("preview", lambda: ("a",), background=True)
    _settle(first)
    release = _gate(monkeypatch)
    second = snapshot.write_or_reuse("preview", lambda: ("b",), background=True)
    assert os.path.isdir(first["folder"]), "removed while the new writer could link from it"
    release.set()
    _settle(second)
    assert not os.path.isdir(first["folder"])
    assert os.path.isdir(second["folder"])


def test_a_failed_writer_makes_ready_raise(doc, monkeypatch):
    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(snapshot, "_store_one", broken)
    record = snapshot.write("export", background=True)
    record["pending"].wait(5)
    with pytest.raises(RuntimeError):
        snapshot.ready(record)


def test_a_job_waits_for_its_snapshot_while_the_worker_boots(sup, tmp_path):
    gate = {"ready": False}
    job_id = sup.submit("preview", _job(tmp_path, "a"), timeout_s=10, ready=lambda: gate["ready"])
    assert "preview" in sup.workers(), "the worker boots while the files are written"
    time.sleep(0.3)
    sup.maintain()
    assert sup.poll(job_id)["state"] == "queued"
    gate["ready"] = True
    assert _wait(sup, job_id)["state"] == "done"


def test_a_snapshot_that_failed_falls_back_like_a_worker_that_never_started(sup, tmp_path):
    def broken():
        raise RuntimeError("snapshot_failed")

    job_id = sup.submit("preview", _job(tmp_path, "a"), timeout_s=10, ready=broken)
    state = sup.poll(job_id)
    assert state["state"] == "failed" and state["error"] == "worker_unavailable"
    nxt = sup.submit("preview", _job(tmp_path, "b"), timeout_s=10)
    assert _wait(sup, nxt)["state"] == "done", "the queue is not wedged"


def test_staged_pixel_copies_never_exceed_the_budget(doc, monkeypatch):
    # Each fake image is 4x2 RGBA float32 = 128 bytes; a 200-byte budget stages
    # one, and the other is read, written and freed on the calling thread.
    monkeypatch.setattr(snapshot, "STAGE_BUDGET_BYTES", 200)
    release = _gate(monkeypatch)
    record = snapshot.write("preview", background=True)
    assert record["staged_bytes"] == 128
    assert os.path.isfile(os.path.join(record["folder"], "image_0001.f32")), \
        "the image over the budget is written before write() returns"
    assert not os.path.exists(os.path.join(record["folder"], "image_0000.u8"))
    release.set()
    _settle(record)
    manifest = json.loads(open(record["images"]).read())
    assert [m["name"] for m in manifest] == ["painted", "hdr"], "original order kept"
    assert [k[0] for k in record["image_keys"]] == ["painted", "hdr"]
    assert snapshot.image_keys(snapshot.dirty_images()) == record["image_keys"]
