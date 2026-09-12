# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixie the cat on the minimised Agent pill.

Pose is the shipped `mixie_cat_eval_pose` (header-only, compiled into a
tiny harness — not reimplemented here). Idle is a close–hold–open blink
and a gaze that leaves centre then returns; working is the same face
with a squint, not a bounce clip. The Mixar mark is gone from the
elongated pill; the compact pill clears the cat QA target.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
HARNESS_SRC = ROOT / "tests/pill_cat_pose_harness.cc"

DRAW_CC = (CPP / "agent_ui_draw.cc").read_text(encoding="utf-8")
CAT_CC = (CPP / "agent_ui_pill_cat.cc").read_text(encoding="utf-8")
CAT_HH = (CPP / "agent_ui_pill_cat.hh").read_text(encoding="utf-8")
POSE_HH = (CPP / "agent_ui_pill_cat_pose.hh").read_text(encoding="utf-8")
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
CMAKE = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")


def _pill_draw() -> str:
    start = DRAW_CC.index("void agent_ui_draw_status_pill")
    end = DRAW_CC.index("void agent_ui_draw_island", start)
    return DRAW_CC[start:end]


def _elongated() -> str:
    body = _pill_draw()
    return body[body.index("if (w > h * 4.0f)") :]


def _parse_pose_line(line: str) -> dict[str, float]:
    out: dict[str, float] = {}
    parts = line.split()
    out["label"] = parts[0]
    for token in parts[1:]:
        key, _, val = token.partition("=")
        out[key] = float(val)
    return out


@functools.lru_cache(maxsize=1)
def pose_harness_output() -> str:
    """Compile and run the shipped pose header. Same function the painter calls."""
    cxx = shutil.which("c++") or shutil.which("clang++")
    assert cxx, "need c++ or clang++ to sample mixie_cat_eval_pose"
    with tempfile.TemporaryDirectory(prefix="mixie-pose-") as td:
        binary = Path(td) / "pose_harness"
        subprocess.check_call(
            [
                cxx,
                "-std=c++17",
                "-O0",
                f"-I{CPP}",
                str(HARNESS_SRC),
                "-o",
                str(binary),
            ],
            cwd=str(ROOT),
        )
        return subprocess.check_output([str(binary)], text=True)


def pose_samples() -> dict[str, dict[str, float]]:
    rows = {}
    for line in pose_harness_output().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parsed = _parse_pose_line(line)
        rows[parsed["label"]] = parsed
    return rows


def test_painter_calls_the_shipped_sampler():
    assert '#include "agent_ui_pill_cat_pose.hh"' in CAT_CC
    assert "mixie_cat_eval_pose(now, working)" in CAT_CC
    assert "Pose eval_pose" not in CAT_CC


def test_elongated_pill_draws_the_cat_not_the_mixar_mark():
    elongated = _elongated()
    assert "agent_ui_draw_pill_cat(&chip, cat_pose, state->cat_activity)" in elongated
    assert "ICON_MIXAR_ICON" not in elongated


def test_compact_pill_clears_stale_cat_target():
    body = _pill_draw()
    assert body.index("agent_ui_draw_pill_cat") < body.index("agent_ui_pill_cat_clear();")


def test_blink_is_close_hold_open_not_a_triangle_dip():
    samples = pose_samples()
    hold_a = samples["idle_hold_a"]["openness"]
    hold_b = samples["idle_hold_b"]["openness"]
    idle_open = samples["idle_open"]["openness"]
    assert hold_a < 0.15
    assert hold_b < 0.15
    assert abs(hold_a - hold_b) < 0.02
    assert idle_open > 0.9
    assert idle_open - hold_a > 0.7


def test_idle_gaze_leaves_centre_and_returns():
    samples = pose_samples()
    assert abs(samples["idle_home"]["look_x"]) < 0.02
    assert abs(samples["idle_home"]["look_y"]) < 0.02
    assert abs(samples["idle_glance"]["look_x"]) > 0.12
    assert abs(samples["idle_open"]["look_x"]) < 0.02


def test_working_keeps_blinking_and_looking_around_without_bouncing():
    samples = pose_samples()
    idle = samples["idle_open"]
    work = samples["working_open"]
    assert work["openness"] < idle["openness"] - 0.2
    assert abs(work["bounce"]) < 0.012
    assert abs(idle["bounce"]) < 0.012
    assert abs(samples["working_glance_clock"]["look_x"]) > 0.25
    assert abs(samples["working_glance_clock"]["look_y"]) > 0.15
    hold = samples["working_hold"]["openness"]
    assert hold < 0.15
    assert work["openness"] - hold > 0.15


def test_cat_paint_stays_inside_the_chip():
    import re

    start = CAT_CC.index("void agent_ui_draw_pill_cat")
    body = CAT_CC[start : CAT_CC.index("\n}\n", start)]
    outward = re.findall(
        r"^\s*\w+\.(?:xmin|ymin)\s*-=|^\s*\w+\.(?:xmax|ymax)\s*\+=",
        body,
        re.MULTILINE,
    )
    assert outward == [], outward


def test_qa_target_reads_the_painted_chip():
    assert 't.surface = "pill_cat"' in CAT_CC
    assert "agent_ui_pill_cat_last_rect" in CAT_CC
    assert "agent_ui_pill_cat_qa_register();" in BUBBLE_CC
    assert "Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, pill_cat_qa_targets)" in CAT_CC


def test_cmake_compiles_the_cat():
    assert "agent_ui_pill_cat.cc" in CMAKE
    assert "agent_ui_pill_cat.hh" in CMAKE
    assert "agent_ui_pill_cat_pose.hh" in CMAKE


def test_header_documents_the_clip_contract():
    assert "Every vertex stays inside that rect" in CAT_HH
    assert "test_agent_bubble_pill_paint.py" in CAT_HH
    assert "mixie_cat_eval_pose" in POSE_HH
