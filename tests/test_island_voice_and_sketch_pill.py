# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Island auto layout, the Voice Stop/ECG control and the Sketch pill.

Three contracts, pinned where they live:

* The composer chip row never runs under Send. The fitter is header-only
  (``agent_ui_chip_fit.hh``) and is compiled into ``tests/chip_fit_harness.cc``
  and swept across window widths, text sizes and composer states; the
  sacrifice order is monotonic — narrowing the window only ever takes away.
* While Voice records, its control reads **Stop** beside a stop square and a
  live ECG trace whose height follows the microphone level. The trace and the
  caret math are header-only too (``agent_ui_voice_motion.hh``,
  ``tests/voice_motion_harness.cc``); the level is ``core/voice_input/level.py``.
* While viewport Sketch is armed, the minimised pill grows slightly, shows the
  draft with a blinking caret, and carries a Voice button whose clicks are
  claimed natively (``mixar.bubble_pill_voice``) before the pill restores.

Native paint/interaction is pinned at source level like the rest of the
island (``bpy`` is a MagicMock here).
"""

from __future__ import annotations

import ast
import functools
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
MODULES = ROOT / "src/scripts/mixar/modules"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


BUBBLE_CC = _read(CPP / "space_agent_bubble.cc")
LAYOUT_CC = _read(CPP / "agent_ui_layout.cc")
LAYOUT_HH = _read(CPP / "agent_ui_layout.hh")
CHIP_FIT_HH = _read(CPP / "agent_ui_chip_fit.hh")
MOTION_HH = _read(CPP / "agent_ui_voice_motion.hh")
VOICE_PAINT_CC = _read(CPP / "agent_ui_voice_paint.cc")
CONTROLS_CC = _read(CPP / "agent_ui_controls_paint.cc")
DRAW_CC = _read(CPP / "agent_ui_draw.cc")
DRAW_HH = _read(CPP / "agent_ui_draw.hh")
STATE_CC = _read(CPP / "agent_ui_state.cc")
THEME_HH = _read(CPP / "agent_ui_theme.hh")
PILL_DRAFT_CC = _read(CPP / "agent_ui_pill_draft.cc")
PILL_VOICE_CC = _read(CPP / "agent_bubble_pill_voice.cc")
INTERN_HH = _read(CPP / "agent_bubble_intern.hh")
CMAKE = _read(CPP / "CMakeLists.txt")
VOICE_PY = _read(MODULES / "space_mixie_chat/core/voice.py")
VOICE_PROPS_PY = _read(MODULES / "space_mixie_chat/ui/properties/voice_props.py")
DRAG_OP_PY = _read(MODULES / "agent_bubble/ui/operators/bubble_header_drag_op.py")


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unbalanced body for {signature}")


def _define(source: str, name: str) -> float:
    match = re.search(rf"#define {name} ([0-9.]+)f?\b", source)
    assert match, name
    return float(match.group(1))


@functools.lru_cache(maxsize=None)
def _harness(name: str) -> str:
    cxx = shutil.which("c++") or shutil.which("clang++")
    assert cxx, "need c++ or clang++ to run the shipped layout/motion headers"
    with tempfile.TemporaryDirectory(prefix="mixar-island-") as td:
        binary = Path(td) / name
        subprocess.check_call(
            [cxx, "-std=c++17", "-O0", f"-I{CPP}", str(ROOT / f"tests/{name}.cc"), "-o", str(binary)],
            cwd=str(ROOT),
        )
        return subprocess.check_output([str(binary)], text=True)


def _fit_rows():
    rows = []
    for line in _harness("chip_fit_harness").splitlines():
        if not line.startswith("fit "):
            continue
        parts = line.split()
        row = {"scenario": parts[1], "size": float(parts[2]), "window": float(parts[3])}
        for token in parts[4:]:
            key, _, value = token.partition("=")
            if key in {"forms", "counts"}:
                row[key] = [int(v) for v in value.split(",")]
            elif key in {"widths", "full"}:
                row[key] = [float(v) for v in value.split(",")]
            else:
                row[key] = float(value)
        rows.append(row)
    return rows


UPLOAD, SCRIBBLE, VOICE, AUTO, MODEL, READING, CLEAR = range(7)
CORE = (SCRIBBLE, VOICE, AUTO, READING, CLEAR)


# ---------------------------------------------------------------------------
# 1. Auto layout: the chip row
# ---------------------------------------------------------------------------


def test_harness_mirrors_the_theme_metrics():
    harness = _read(ROOT / "tests/chip_fit_harness.cc")
    pairs = {
        "ISLAND_W": "AGENT_ISLAND_W",
        "SEG_X": "AGENT_SEG_X",
        "SEND_W": "AGENT_BTN_GENERATE_W",
        "CHIP_GAP": "AGENT_CHIP_GAP",
        "CHIP_ICON": "AGENT_CHIP_ICON",
        "CHIP_ICON_GAP": "AGENT_CHIP_ICON_GAP",
        "CHIP_PAD_X": "AGENT_CHIP_PAD_X",
        "SWITCH_W": "AGENT_SWITCH_W",
        "CLEAR_W": "AGENT_CHIP_CLEAR_W",
        "WAVE_W": "AGENT_CHIP_WAVE_W",
    }
    for local, theme in pairs.items():
        mirrored = re.search(rf"{local} = ([0-9.]+)f;", harness)
        assert mirrored, local
        assert float(mirrored.group(1)) == _define(THEME_HH, theme), (local, theme)


def test_layout_measures_with_the_island_font_and_places_the_fit():
    body = _function_body(LAYOUT_CC, "void agent_ui_layout_fit_controls(")
    assert "agent_chip_forms(" in body
    assert "ui::mixar_text_width(label, size)" in body
    assert "agent_chip_fit(chips, span, gap)" in body
    assert "layout.btn_generate.xmin - layout.chip_upload.xmin" in body
    assert "std::copy_n(fit.form" in body
    assert "int chip_form[AGENT_CHIP_SLOT_COUNT];" in LAYOUT_HH


def test_the_row_never_runs_under_send():
    rows = _fit_rows()
    assert len(rows) > 2000
    for row in rows:
        assert row["fits"] == 1, row
        assert row["used"] <= row["span"] + 0.5, row


def test_narrowing_only_ever_takes_away():
    """Forms (higher = less text) never go back up as the window shrinks —
    the old second model pass regrew its full label on a narrower row."""
    by_case: dict[tuple, list] = {}
    for row in _fit_rows():
        by_case.setdefault((row["scenario"], row["size"]), []).append(row)
    for case, rows in by_case.items():
        rows.sort(key=lambda r: r["window"])
        for narrow, wide in zip(rows, rows[1:]):
            for slot in CORE + (MODEL,):
                if narrow["counts"][slot] == 0:
                    continue
                assert wide["forms"][slot] <= narrow["forms"][slot], (case, slot, narrow, wide)


def test_core_chips_shed_words_only_after_the_model_chip_is_gone():
    """Upload is the remainder, so it may win "Reference" back once a long
    status word sheds — but never its full label, and never beside a model."""
    shed_rows = 0
    for row in _fit_rows():
        shed = any(row["counts"][s] and row["forms"][s] > 0 for s in CORE)
        if not shed:
            continue
        shed_rows += 1
        assert row["widths"][MODEL] == 0.0, row
        assert row["forms"][UPLOAD] >= 1, row
    assert shed_rows, "the sweep must reach the shedding regime"


def test_default_island_keeps_every_label_including_stop_and_its_trace():
    for row in _fit_rows():
        if row["window"] != 680.0 or row["size"] not in (11.0, 13.75):
            continue
        if row["scenario"] in {"idle", "capturing", "long_model", "no_voice"}:
            for slot in CORE:
                if row["counts"][slot]:
                    assert row["forms"][slot] == 0, row


def test_voice_keeps_one_width_idle_and_capturing():
    """Starting and stopping dictation never shifts Auto or the model chip."""
    rows = {(r["scenario"], r["size"], r["window"]): r for r in _fit_rows()}
    for (scenario, size, window), row in rows.items():
        if scenario != "idle":
            continue
        capturing = rows[("capturing", size, window)]
        assert math.isclose(row["full"][VOICE], capturing["full"][VOICE], abs_tol=1e-3)
        if row["forms"][VOICE] == 0 and capturing["forms"][VOICE] == 0:
            assert math.isclose(row["widths"][AUTO], capturing["widths"][AUTO], abs_tol=1e-3)


def test_shed_order_and_ladders_are_the_documented_ones():
    order = CHIP_FIT_HH[CHIP_FIT_HH.index("AGENT_CHIP_SHED_ORDER[] = {") :]
    order = order[: order.index("};")]
    assert re.findall(r"AGENT_CHIP_SLOT_(\w+)", order) == [
        "VOICE", "AUTO", "SCRIBBLE", "READING", "VOICE"]
    forms = _function_body(CHIP_FIT_HH, "inline void agent_chip_forms(")
    assert 'in.scribble_armed ? "Done" : "Sketch"' in forms
    assert 'width("Auto", m.switch_w)' in forms
    assert "width(in.voice_status, m.icon)" in forms
    assert "{{std::max(idle, capture), stop, icon_only}, 3}" in forms


def test_painters_honour_the_fitted_forms():
    row = _function_body(CONTROLS_CC, "void agent_ui_draw_chip_row(")
    assert "layout->chip_form[AGENT_CHIP_SLOT_SCRIBBLE] > 0" in row
    assert "chip_icon(layout->chip_scribble, AGENT_ICON_PEN" in row
    assert "layout->chip_form[AGENT_CHIP_SLOT_AUTO] > 0" in row
    assert "layout->chip_form[AGENT_CHIP_SLOT_VOICE]" in row
    # The reading label elides into its chip instead of running past the chevron.
    assert "ui::mixar_fit_text(\n          state->mark_intent[0]" in row


# ---------------------------------------------------------------------------
# 2. Voice: Stop + ECG
# ---------------------------------------------------------------------------


def test_capturing_is_the_recorders_listening_state():
    """C++ compares the status string; the producer must keep that literal."""
    assert "s.state = 'Listening'" in VOICE_PY
    assert 'STREQ(r_state->voice_status, "Listening")' in STATE_CC
    assert "bool voice_capturing;" in DRAW_HH
    assert '"mixie_chat_voice_level"' in STATE_CC


def test_voice_chip_reads_stop_with_a_stop_square_and_the_live_trace():
    body = _function_body(VOICE_PAINT_CC, "void agent_ui_draw_voice_chip(")
    assert 'capturing ? "Stop"' in body
    assert "agent_ui_draw_stop_glyph(icon, color)" in body
    assert "agent_ui_icon_draw(AGENT_ICON_MIC" in body
    assert "agent_ui_draw_voice_wave(wave, now, level, color)" in body
    # Frames only while the trace is drawn, only for the region showing it,
    # and never under Reduce Motion.
    assert "ui::mixar_motion_request(region, now + AGENT_VOICE_WAVE_FRAME_SECONDS)" in body
    assert "!ui::mixar_motion_reduced()" in body
    assert "chip.ymax > float(region->winrct.ymin)" in body
    row = _function_body(CONTROLS_CC, "void agent_ui_draw_chip_row(")
    assert "agent_ui_draw_voice_chip(region," in row
    assert "state->voice_capturing" in row


def test_wave_is_antialiased_at_real_width():
    body = _function_body(VOICE_PAINT_CC, "void agent_ui_draw_voice_wave(")
    assert "GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR" in body
    assert 'immUniform1i("lineSmooth", 1)' in body
    assert "GPU_line_width(" not in body
    assert "agent_voice_wave_points(now, level, ui::mixar_motion_reduced(), points)" in body


def test_voice_tooltip_names_stop_while_capturing():
    assert '"Stop dictating and insert the words (or release Option/Alt). Shift-click cancels"' in BUBBLE_CC
    assert "state->voice_capturing ?" in BUBBLE_CC


def _waves():
    rows = []
    for line in _harness("voice_motion_harness").splitlines():
        if not line.startswith("wave "):
            continue
        parts = line.split()
        row = {"now": float(parts[1]), "level": float(parts[2]), "reduced": parts[3] == "1"}
        for token in parts[4:]:
            key, _, value = token.partition("=")
            if key == "pts":
                row[key] = [tuple(float(v) for v in p.split(":")) for p in value.split(";")]
            else:
                row[key] = float(value)
        rows.append(row)
    return rows


def test_ecg_trace_spans_the_box_and_always_shows_a_sharp_peak():
    quiet = float(re.search(r"AGENT_VOICE_WAVE_QUIET = ([0-9.]+)f", MOTION_HH).group(1))
    for row in _waves():
        assert row["mono"] == 1
        assert row["min_x"] == 0.0 and row["max_x"] == 1.0
        assert row["n"] <= float(re.search(r"AGENT_VOICE_WAVE_MAX_POINTS = (\d+)", MOTION_HH).group(1))
        amp = quiet + (1.0 - quiet) * row["level"]
        # The R peak is a vertex, so it never shimmers below full height.
        assert math.isclose(row["max_y"], amp, abs_tol=1e-4), row
        assert row["min_y"] < 0.0


def test_ecg_height_follows_the_voice_and_scrolls_unless_motion_is_reduced():
    rows = _waves()
    silent = [r for r in rows if r["level"] == 0.0 and not r["reduced"]]
    loud = [r for r in rows if r["level"] == 1.0 and not r["reduced"]]
    assert max(r["max_y"] for r in loud) > 2.5 * max(r["max_y"] for r in silent)
    assert len({tuple(r["pts"]) for r in silent}) > 30, "trace must move between frames"
    frozen = [r for r in rows if r["reduced"]]
    assert len(frozen) == 2 and frozen[0]["pts"] == frozen[1]["pts"]


# ---------------------------------------------------------------------------
# 3. Voice level (Python half)
# ---------------------------------------------------------------------------


def _level():
    sys.path.insert(0, str(ROOT / "src/scripts"))
    from mixar.modules.space_mixie_chat.core.voice_input import level

    return level


def _pcm(*samples):
    return struct.pack("<" + "h" * len(samples), *samples)


def test_pcm_peak_reads_little_endian_16_bit_and_ignores_a_torn_byte():
    level = _level()
    assert level.pcm16_peak(b"") == 0.0
    assert level.pcm16_peak(_pcm(0, 16384, -8192)) == pytest.approx(0.5)
    assert level.pcm16_peak(_pcm(-32768)) == 1.0
    assert level.pcm16_peak(_pcm(0, 1000) + b"\x7f") == pytest.approx(1000 / 32768)


def test_level_maps_speech_range_and_breathes():
    level = _level()
    assert level.peak_to_level(0.0) == 0.0
    assert level.peak_to_level(10 ** (level.LEVEL_FLOOR_DB / 20) * 0.5) == 0.0
    assert level.peak_to_level(1.0) == 1.0
    assert 0.0 < level.peak_to_level(0.05) < 1.0
    rising = level.smooth(0.0, 1.0)
    falling = level.smooth(1.0, 0.0)
    assert rising > 1.0 - falling, "rise faster than fall"
    assert level.should_write(0.5, 0.5 + level.LEVEL_WRITE_EPSILON)
    assert not level.should_write(0.5, 0.505)
    assert level.should_write(0.01, 0.0)


def test_recorder_publishes_the_level_and_clears_it_when_not_recording():
    tree = ast.parse(VOICE_PY)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    tick = ast.get_source_segment(VOICE_PY, funcs["_tick"])
    assert "s.transport.feed(data)\n                _publish_level(s, data)" in tick
    publish = ast.get_source_segment(VOICE_PY, funcs["_publish_level"])
    assert "except Exception" in publish, "a level failure must never end dictation"
    status = ast.get_source_segment(VOICE_PY, funcs["_status"])
    assert "if text != 'Listening'" in status
    assert "wm.mixie_chat_voice_level = 0.0" in status
    assert "'mixie_chat_voice_level'," in VOICE_PROPS_PY
    assert "WindowManager.mixie_chat_voice_level = FloatProperty(" in VOICE_PROPS_PY
    assert "options={'SKIP_SAVE', 'HIDDEN'}" in VOICE_PROPS_PY


# ---------------------------------------------------------------------------
# 4. The Sketch pill
# ---------------------------------------------------------------------------


def test_sketch_pill_is_slightly_larger_and_still_elongated():
    w = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_WIDTH_SKETCH")
    h = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_HEIGHT_SKETCH")
    r = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_CORNER_RADIUS_SKETCH")
    base_w = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_WIDTH_LARGE")
    base_h = _define(BUBBLE_CC, "AGENT_BUBBLE_PILL_HEIGHT_LARGE")
    assert 1.0 < w / base_w <= 1.25 and 1.0 < h / base_h <= 1.25
    assert w / h > 4.0, "the elongated painter runs on aspect > 4"
    assert r == h / 2


def test_every_resting_seat_uses_the_current_rest_size():
    for sig in ("static void pill_seat_on_host()", "static void pill_remember_user_seat()",
                "static void minimise_anim_finish(void *user_data)"):
        body = _function_body(BUBBLE_CC, sig)
        assert "PILL_WIDTH_LARGE" not in body and "PILL_HEIGHT_LARGE" not in body, sig
    seat = _function_body(BUBBLE_CC, "static void pill_seat_on_host()")
    assert "g_pill_user_offset_x + pill_rest_dx()" in seat
    remember = _function_body(BUBBLE_CC, "static void pill_remember_user_seat()")
    assert "ox - pill_rest_dx()" in remember and "oy - pill_rest_dy()" in remember
    drag = _function_body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_window_begin_drag_exec(")
    assert "g_pill_user_offset_x = ox - pill_rest_dx();" in drag
    finish = _function_body(BUBBLE_CC, "static void minimise_anim_finish(void *user_data)")
    assert "g_pill_rest_sketch = G_MAIN && pill_sketch_wanted(" in finish
    assert "pill_rest_width(), pill_rest_height()" in finish
    band = _function_body(BUBBLE_CC, "int ED_agent_bubble_pill_band_px(")
    assert "pill_rest_height()" in band


def test_heartbeat_grows_and_shrinks_the_resting_pill_on_the_sketch_edge():
    tick = _function_body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_hover_tick_exec(")
    edge = tick[tick.index("const bool sketch = pill_sketch_wanted(") :]
    assert "if (sketch != g_pill_rest_sketch)" in edge
    assert "pill_set_size(C, pill_rest_width(), pill_rest_height(), pill_rest_radius());" in edge
    assert "pill_seat_on_host();" in edge
    assert "!g_bubble_minimise_pending" in tick
    restore = _function_body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_restore_exec(")
    assert "g_pill_rest_sketch = false;" in restore
    closed = _function_body(BUBBLE_CC, "void ED_agent_bubble_windows_closed()")
    assert "g_pill_rest_sketch = false;" in closed


def test_sketch_pill_paints_draft_caret_and_voice_button():
    elongated = _function_body(DRAW_CC, "void agent_ui_draw_status_pill(")
    assert "agent_ui_draw_pill_draft(*state, text_x, chip.xmin - 12.0f * u, h, text_size, u);" in elongated
    draft = _function_body(PILL_DRAFT_CC, "void agent_ui_draw_pill_draft(")
    assert "agent_caret_visible(now, caret_epoch, ui::mixar_motion_reduced())" in draft
    assert "caret_epoch = now;" in draft, "typing keeps the caret solid"
    assert "draw_voice_button(state, voice_rect)" in draft
    assert "agent_ui_draw_voice_wave(wave, now, state.voice_level, border)" in draft
    button = _function_body(PILL_DRAFT_CC, "void draw_voice_button(")
    assert "agent_ui_draw_stop_glyph(glyph, text)" in button
    assert "AGENT_ICON_MIC" in button


def test_sketch_pill_wakes_only_for_the_caret_edge_or_the_trace():
    frame = _function_body(PILL_DRAFT_CC, "double agent_ui_pill_draft_next_frame()")
    assert "agent_caret_next_change(now, caret_epoch, reduced)" in frame
    assert "AGENT_VOICE_WAVE_FRAME_SECONDS" in frame
    assert "std::numeric_limits<double>::infinity()" in frame
    draw = _function_body(BUBBLE_CC, "void agent_bubble_header_region_draw(")
    assert "std::min(agent_ui_cat_motion_next_frame(region),\n                                   agent_ui_pill_draft_next_frame())" in draw


def test_caret_blinks_like_a_text_field():
    rows = [line.split() for line in _harness("voice_motion_harness").splitlines()
            if line.startswith("caret ")]
    live = [(float(r[1]) - float(r[2]), r[4] == "visible=1", r[5]) for r in rows if r[3] == "0"]
    for dt, visible, _ in live:
        if dt <= 0.5:
            assert visible, dt
        elif 0.56 <= dt <= 1.05:
            assert not visible, dt
        elif 1.07 <= dt <= 1.58:
            assert visible, dt
    for _, _, nxt in live:
        assert 0.0 < float(nxt.split("=")[1]) <= 0.7
    reduced = [r for r in rows if r[3] == "1"]
    assert reduced and all(r[4] == "visible=1" and r[5] == "next=inf" for r in reduced)


def test_pill_voice_hit_test_and_qa_share_the_painted_disc():
    hit = _function_body(PILL_DRAFT_CC, "bool agent_ui_pill_voice_hit(")
    assert "dx * dx + dy * dy <= r * r" in hit
    targets = _function_body(PILL_DRAFT_CC, "void draft_targets(")
    assert 'voice.surface = "pill_voice";' in targets
    assert "BLI_rcti_rctf_copy_round(&voice.rect_win, &voice_rect);" in targets


def test_pill_voice_operator_claims_only_hits_and_returns_the_keyboard():
    invoke = _function_body(PILL_VOICE_CC, "static wmOperatorStatus pill_voice_invoke(")
    assert "agent_ui_pill_voice_hit(event->xy[0], event->xy[1])" in invoke
    assert invoke.index("return OPERATOR_CANCELLED;") < invoke.index('"MIXIE_CHAT_OT_voice_toggle"')
    assert "wm::OpCallContext::InvokeDefault, nullptr, event);" in invoke, "Shift-click cancels"
    assert "agent_bubble_return_key_to_host();" in invoke
    assert "ED_agent_bubble_is_resting_pill(C)" in PILL_VOICE_CC
    assert "WM_operatortype_append(MIXAR_OT_bubble_pill_voice);" in BUBBLE_CC
    assert "void MIXAR_OT_bubble_pill_voice(wmOperatorType *ot);" in INTERN_HH
    key = _function_body(BUBBLE_CC, "void agent_bubble_return_key_to_host()")
    assert "Mixar_WindowMakeKey(g_host_ghostwin);" in key


def test_pill_click_asks_the_voice_button_first():
    tree = ast.parse(DRAG_OP_PY)
    claimed = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_pill_voice_claimed")
    src = ast.get_source_segment(DRAG_OP_PY, claimed)
    assert "bpy.ops.mixar.bubble_pill_voice('INVOKE_DEFAULT') == {'FINISHED'}" in src
    assert "except Exception" in src
    op = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    click = next(n for n in op.body if isinstance(n, ast.FunctionDef) and n.name == "_pill_click")
    body = ast.get_source_segment(DRAG_OP_PY, click)
    assert body.index("_pill_voice_claimed()") < body.index("bpy.ops.mixar.bubble_minimise()")


def test_new_sources_are_built():
    for name in ("agent_bubble_pill_voice.cc", "agent_ui_voice_paint.cc", "agent_ui_chip_fit.hh",
                 "agent_ui_voice_motion.hh", "agent_ui_voice_paint.hh"):
        assert f"  {name}\n" in CMAKE, name
