# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
from types import SimpleNamespace

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.constants import FEATURE_MATGEN
from mixar.modules.paint.procedural_materials import matgen_persistence
from mixar.modules.paint.procedural_materials import matgen_queue as MQ


class _RecentList(list):
    def add(self):
        item = SimpleNamespace(material_id="", display_name="")
        self.append(item)
        return item


def test_enqueue_matgen_job_submits_job_queue(monkeypatch):
    submitted = []
    marked = []

    class FakeService:
        def enqueue(self, **kwargs):
            submitted.append(kwargs)

    class FakeQueue:
        def add_listener(self, fn):
            self.listener = fn

        def submit(self, job):
            self.job = job
            job.submit(lambda response: None, lambda error: None)
            return True

    fake_queue = FakeQueue()
    monkeypatch.setattr(MQ, "_listener_attached", False)
    monkeypatch.setattr(MQ, "get_queue", lambda feature_key: fake_queue)
    monkeypatch.setattr(MQ, "get_job_queue_service", lambda: FakeService())
    monkeypatch.setattr(MQ, "mark_enqueued", lambda feature_key: marked.append(feature_key))

    job = MQ.enqueue_matgen_job(
        prompt="oak wood",
        model="claude-opus-4-6",
        pipeline="detailed",
    )

    assert job is fake_queue.job
    assert submitted[0]["job_type"] == "mat_gen"
    assert submitted[0]["model"] == "claude-opus-4-6"
    assert submitted[0]["payload"] == {"prompt": "oak wood", "pipeline": "detailed"}
    assert marked == [FEATURE_MATGEN]


def test_matgen_job_handle_result_saves_and_registers(monkeypatch, tmp_path):
    matgen_dir = tmp_path / "matgen"
    catalog_path = tmp_path / "matgen_catalog.json"
    registered = []
    done = []
    errors = []
    wm = SimpleNamespace(
        mixar_matgen_status="generating",
        mixar_matgen_recent=_RecentList(),
        windows=[],
    )

    monkeypatch.setattr(MQ.bpy, "context", SimpleNamespace(window_manager=wm))
    monkeypatch.setattr(
        matgen_persistence,
        "_get_matgen_paths",
        lambda: (str(matgen_dir), str(catalog_path)),
    )
    monkeypatch.setattr(MQ.material_registry, "register_material", registered.append)

    job = MQ.MatGenJob(
        prompt="oak wood",
        model="claude-opus-4-6",
        pipeline="detailed",
        _result={
            "script": "BASE_COLOR = (0.2, 0.3, 0.4)",
            "archetype": "wood",
            "node_group_name": "Generated Oak",
        },
    )

    assert job.handle_result([], done.append, errors.append) is True

    assert errors == []
    assert done == ["Oak Wood"]
    assert wm.mixar_matgen_status == "done:Oak Wood"
    assert wm.mixar_matgen_recent[0].material_id == registered[0].material_id
    assert wm.mixar_matgen_recent[0].display_name == "Oak Wood"
    assert registered[0].category == "ai_generated"
    assert registered[0].node_group_name == "Generated Oak"
    with open(registered[0].script_path, encoding="utf-8") as f:
        assert "BASE_COLOR = (0.2, 0.3, 0.4, 1.0)" in f.read()
