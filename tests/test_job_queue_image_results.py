# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image-generation results must reach the board fast.

Two latency contracts:

- A completed job whose at-most-once ``job.update`` push is lost may wait
  only one watchdog tick for the batched ``job.sync`` backstop (it used to
  wait 30 s doing nothing).
- A multi-image result downloads its files CONCURRENTLY (bounded), and the
  board order follows URL order, not completion order.
"""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core import image_results as IR
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.utils import image_utils as IU


def _run_download(monkeypatch, urls, sleeps, fail_urls=()):
    """Drive download_images_to_moodboard with fakes.

    Returns (result, max_concurrent, apply_fn, wall_s) where result holds
    whatever on_done/on_error received and apply_fn is the captured
    main-thread apply that the caller must invoke.
    """
    lock = threading.Lock()
    state = {"active": 0, "max": 0}
    timers = []

    def fake_register(fn, first_interval=0.0, persistent=False):
        timers.append((fn, first_interval))

    def fake_download(url, retries=3, filename=""):
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        try:
            time.sleep(sleeps[urls.index(url)])
            if url in fail_urls:
                raise OSError("simulated transfer failure")
            return f"/tmp/{url.rsplit('/', 1)[-1]}", 10
        finally:
            with lock:
                state["active"] -= 1

    # Patch the bpy the MODULE holds: install_bpy_mock() replaces
    # sys.modules["bpy"] with a fresh mock per test file, so a module-level
    # "import bpy" here can be a DIFFERENT object than image_results'.
    monkeypatch.setattr(IR.bpy.app.timers, "register", fake_register)
    monkeypatch.setattr(IU, "download_image_to_tempfile", fake_download)
    monkeypatch.setattr(
        IU, "filename_from_url", lambda url: url.rsplit("/", 1)[-1]
    )
    monkeypatch.setattr(
        IU,
        "load_image_from_file",
        lambda path, name, keep_filename=False: SimpleNamespace(name=name),
    )
    monkeypatch.setattr(IU, "add_image_to_moodboard", lambda *a, **k: None)
    monkeypatch.setattr(IU, "cleanup_temp_image", lambda path: None)

    result = {}
    done = threading.Event()

    IR.download_images_to_moodboard(
        urls=list(urls),
        name_prefix="imagegen",
        prompt="p",
        job_id="job-img-1",
        on_done=lambda names: (result.setdefault("names", names), done.set()),
        on_error=lambda err: (result.setdefault("err", err), done.set()),
    )

    started = time.monotonic()
    deadline = started + 5.0
    while not timers and time.monotonic() < deadline:
        time.sleep(0.02)
    wall = time.monotonic() - started

    assert timers, "background download never reached the main-thread apply"
    apply_fn, interval = timers[0]
    assert interval == 0.0
    return result, state["max"], apply_fn, wall, done


def test_missed_push_backstop_waits_at_most_five_seconds():
    assert QM._SYNC_WATCHDOG_INTERVAL <= 5.0


def test_multi_image_result_downloads_concurrently(monkeypatch):
    urls = [
        "https://cdn.example/x/0.png",
        "https://cdn.example/x/1.png",
        "https://cdn.example/x/2.png",
    ]
    result, max_concurrent, apply_fn, wall, done = _run_download(
        monkeypatch, urls, [0.3, 0.3, 0.3]
    )
    # Serial transfers would need >= 0.9 s before the apply is even queued.
    assert wall < 0.8
    assert max_concurrent >= 2
    apply_fn()
    assert done.wait(2.0)
    assert result.get("names") == "0, 1, 2"


def test_board_order_follows_url_not_completion_order(monkeypatch):
    urls = [
        "https://cdn.example/x/a.png",
        "https://cdn.example/x/b.png",
        "https://cdn.example/x/c.png",
    ]
    # Completion order b, c, a; insertion order must stay a, b, c.
    result, _max, apply_fn, _wall, done = _run_download(
        monkeypatch, urls, [0.3, 0.05, 0.1]
    )
    apply_fn()
    assert done.wait(2.0)
    assert result.get("names") == "a, b, c"


def test_one_failed_transfer_does_not_sink_the_batch(monkeypatch):
    urls = [
        "https://cdn.example/x/a.png",
        "https://cdn.example/x/bad.png",
        "https://cdn.example/x/c.png",
    ]
    result, _max, apply_fn, _wall, done = _run_download(
        monkeypatch, [urls[0], urls[1], urls[2]], [0.05, 0.05, 0.05],
        fail_urls={urls[1]},
    )
    apply_fn()
    assert done.wait(2.0)
    assert result.get("names") == "a, c"
