# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An agent/MCP image job carries the chosen model's own catalog params.

MCP bug: GPT Image 2.5 advertises quality and background (transparent) in its
catalog schema, but the direct operator path built a fixed params set, so a
transparent image could not be requested. The backend now sends them as one
JSON ``params`` property; the operator merges them into the job's params.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.moodboard.ui.operators import imagegen_ops  # noqa: E402


def test_the_params_property_is_read_as_plain_values():
    assert imagegen_ops._catalog_params('{"quality": "medium", "background": "transparent"}') == {
        "quality": "medium", "background": "transparent"}
    for raw in ("", "   ", "not json", "[1, 2]", "42"):
        assert imagegen_ops._catalog_params(raw) == {}
    assert imagegen_ops._catalog_params('{"a": {"nested": 1}, "_meta": "x", "n": 2}') == {"n": 2}


def test_the_direct_path_merges_them_into_the_job_params(monkeypatch):
    from mixar.modules.common import job_queue
    from mixar.modules.common.job_queue.ui.lists import queue_uilist
    from mixar.modules.common.utils import agent_feedback

    sent = {}
    monkeypatch.setattr(job_queue, "enqueue_generation", lambda **kw: sent.update(kw) or object())
    monkeypatch.setattr(queue_uilist, "mark_enqueued", lambda *_a: None)
    monkeypatch.setattr(agent_feedback, "clear_agent_gen_reason", lambda *_a: None)
    monkeypatch.setattr(imagegen_ops, "_get_max_refs", lambda _model: 4)
    monkeypatch.setattr(imagegen_ops, "get_imagegen_listener", lambda: None)
    op = SimpleNamespace(prompt="a red kite", model="gpt-image-2.5-flare", style="", aspect_ratio="1:1",
                         resolution="", number_of_images=1, negative_prompt="", reference_image_names="",
                         name="", params='{"quality": "medium", "background": "transparent"}',
                         report=lambda *_a: None)

    assert imagegen_ops.MIXIE_OT_imagegen_generate._execute_direct(op, SimpleNamespace()) == {"FINISHED"}
    assert sent["payload"]["params"]["background"] == "transparent"
    assert sent["payload"]["params"]["quality"] == "medium"
    assert sent["payload"]["params"]["aspect_ratio"] == "1:1"
