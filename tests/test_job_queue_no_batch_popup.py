# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A drained generation batch raises no "<Feature> batch complete" popup.

Batch completion feedback is the per-feature completion toast in the
bottom-left notification lane ("Image to 3D complete" / "4 succeeded",
``core/enqueue_toast.py``) plus the per-job failure toast; the popup menu that
used to open under the cursor carried the same facts.
"""

import ast
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core import helpers as HELPERS
from mixar.modules.common.job_queue.core.job import Job, JobState


def test_drained_batch_opens_no_popup(monkeypatch):
    scene = SimpleNamespace(name="Scene", is_generating=False)
    monkeypatch.setattr(HELPERS.bpy.data, "scenes", [scene], raising=False)
    monkeypatch.setattr(HELPERS.bpy.context, "scene", scene, raising=False)
    register = MagicMock()
    popup_menu = MagicMock()
    monkeypatch.setattr(HELPERS.bpy.app.timers, "register", register, raising=False)
    monkeypatch.setattr(
        HELPERS.bpy.context, "window_manager",
        SimpleNamespace(popup_menu=popup_menu), raising=False,
    )

    jobs = [
        Job(scene_name="Scene", state=JobState.RUNNING_POLL),
        Job(scene_name="Scene", state=JobState.RUNNING_POLL),
    ]

    class QueueSnapshot:
        def snapshot(self):
            return list(jobs)

        def has_active_work(self):
            return any(j.state == JobState.RUNNING_POLL for j in jobs)

    listener = HELPERS.create_scene_flag_listener("is_generating")
    listener(QueueSnapshot())
    assert scene.is_generating is True

    jobs[0].state = JobState.SUCCESS
    jobs[1].state = JobState.FAILED
    listener(QueueSnapshot())

    assert scene.is_generating is False
    register.assert_not_called()
    popup_menu.assert_not_called()
    assert not hasattr(HELPERS, "show_batch_summary_popup")


def test_no_caller_passes_batch_popup_title():
    """The keyword is gone from ``enqueue_generation`` and
    ``create_scene_flag_listener``; a caller still passing it would raise
    ``TypeError`` at submit time."""
    offenders = []
    for path in sorted((SCRIPTS / "mixar").rglob("*.py")):
        with warnings.catch_warnings():
            # Unrelated modules carry invalid-escape string literals.
            warnings.simplefilter("ignore")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and any(
                kw.arg == "batch_popup_title" for kw in node.keywords
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []
