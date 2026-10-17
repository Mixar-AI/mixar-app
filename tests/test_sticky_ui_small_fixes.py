# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pins for three small main-thread fixes that had no test.

See docs/development/sticky-ui-performance.md (private) for the measurements.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_metal_pool_sweep_runs_once_per_second():
    hh = (ROOT / "src/source/blender/gpu/metal/mtl_memory.hh").read_text()
    mm = (ROOT / "src/source/blender/gpu/metal/mtl_memory.mm").read_text()
    assert "time_t last_pool_sweep_time_ = 0;" in hh
    body = mm[mm.index("update_memory_pools"):]
    assert "const bool do_sweep = (time_now != last_pool_sweep_time_);" in body
    assert "last_pool_sweep_time_ = time_now;" in body


def test_bubble_streaming_tick_tags_only_bubble_areas():
    src = (ROOT / "src/scripts/mixar/bootstrap/agent_bubble_module.py").read_text()
    tree = ast.parse(src)
    tick = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_streaming_redraw_tick")
    compared = {c.value for n in ast.walk(tick) if isinstance(n, ast.Compare)
                for c in n.comparators if isinstance(c, ast.Constant)}
    assert "AGENT_BUBBLE" in compared
    assert "VIEW_3D" not in compared      # viewport redraws belong to the halo and the agent panel


def test_viewport_click_calls_python_only_with_a_toast_visible():
    cc = (ROOT / "src/source/blender/editors/space_view3d/view3d_toast_click.cc").read_text()
    for op in ("toast_click", "toast_hover", "toast_scroll"):
        call = f'toast_call_mouse_op(C, event, "notification.{op}")'
        line = next(l for l in cc.splitlines() if call in l)
        assert "toast_any_visible(C) &&" in line or "toast_any_visible(C) &&" in cc[cc.index(call) - 80:cc.index(call)]
