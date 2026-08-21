# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the generation-library qualifying filter + drain logic.

bpy is stubbed by the root conftest; the module's heavy deps (job_queue,
moodboard exporter) are imported lazily inside functions, so importing the
module and exercising the pure logic works outside Blender.
"""

import sys
import types
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.asset_search.core import generation_library as gl


def _job(job_type="", service="", state="SUCCESS"):
    return types.SimpleNamespace(job_type=job_type, service=service, state=state)


def test_qualifying_accepts_image_to_3d_and_model_3d():
    assert gl._is_qualifying(_job(job_type="image_to_3d"))
    assert gl._is_qualifying(_job(job_type="model_3d"))


def test_qualifying_falls_back_to_service_field():
    # Bespoke jobs may carry the type on `service` rather than `job_type`.
    assert gl._is_qualifying(_job(job_type="", service="model_3d"))


def test_qualifying_rejects_other_generation_types():
    for t in ("retopology", "hunyuan_rapid", "hunyuan_uv", "hunyuan_part",
              "scene_gen", "image_gen", ""):
        assert not gl._is_qualifying(_job(job_type=t)), t


def test_drain_check_true_when_no_active_qualifying_jobs(monkeypatch):
    # A qualifying job in a terminal state, and a non-qualifying job still
    # running, must both count as "drained" for our purposes.
    class FakeQueue:
        def __init__(self, jobs):
            self._jobs = jobs

        def snapshot(self):
            return list(self._jobs)

    done = _job(job_type="model_3d", state="SUCCESS")
    other_running = _job(job_type="retopology", state="RUNNING_POLL")
    monkeypatch.setattr(
        "mixar.modules.common.job_queue.core.queue_manager.all_queues",
        lambda: [FakeQueue([done, other_running])],
    )
    assert gl._all_qualifying_queues_idle() is True


def test_drain_check_false_while_qualifying_job_active(monkeypatch):
    class FakeQueue:
        def __init__(self, jobs):
            self._jobs = jobs

        def snapshot(self):
            return list(self._jobs)

    running = _job(job_type="image_to_3d", state="RUNNING_DOWNLOAD")
    monkeypatch.setattr(
        "mixar.modules.common.job_queue.core.queue_manager.all_queues",
        lambda: [FakeQueue([running])],
    )
    assert gl._all_qualifying_queues_idle() is False
