# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto mode on the Agent island: the composer's sliding switch.

The backend's `auto_mode` is a per-turn flag on `agent.chat` (nothing is
persisted server-side), so the client owns the sticky state
(`scene.mixie_chat_auto_mode`) and must stamp it on EVERY send while it is
on. The island chip that flips it is native C++ (a GPU/window-manager
surface with no importable Python half), so it is pinned at source level in
the style of the other island tests; the Python send path is exercised
directly where `bpy` being a MagicMock does not make the test vacuous.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
DRAW_CC = (CPP / "agent_ui_controls_paint.cc").read_text(encoding="utf-8")
STATE_CC = (CPP / "agent_ui_state.cc").read_text(encoding="utf-8")
LAYOUT_CC = (CPP / "agent_ui_layout.cc").read_text(encoding="utf-8")
LAYOUT_HH = (CPP / "agent_ui_layout.hh").read_text(encoding="utf-8")
CHIP_FIT_HH = (CPP / "agent_ui_chip_fit.hh").read_text(encoding="utf-8")
DRAW_HH = (CPP / "agent_ui_draw.hh").read_text(encoding="utf-8")
MOTION_HH = (CPP / "agent_ui_motion.hh").read_text(encoding="utf-8")
THEME_HH = (CPP / "agent_ui_theme.hh").read_text(encoding="utf-8")

CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
PROPS_PY = (CHAT / "ui/properties/chat_props.py").read_text(encoding="utf-8")
SPECIAL_OPS_PY = (CHAT / "ui/operators/chat_special_ops.py").read_text(encoding="utf-8")
CHAT_OPS_PY = (CHAT / "ui/operators/chat_ops.py").read_text(encoding="utf-8")
COMPOSER_SEND_PY = (CHAT / "core/composer_send.py").read_text(encoding="utf-8")
TRANSPORT_PY = (CHAT / "core/turn_transport.py").read_text(encoding="utf-8")


def _function_body(source: str, signature_start: str) -> str:
    start = source.index(signature_start)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unterminated function: {signature_start}")


# ---------------------------------------------------------------------------
# The wire: `auto_mode: true` only when on, on every chat send, never on input.
# ---------------------------------------------------------------------------

def _payload(**kw):
    from mixar.modules.space_mixie_chat.core.chat_payloads import build_chat_payload
    return build_chat_payload(message="make a chair", instance_id="i", session_id="s",
                              plan_required=False, execution_required=True,
                              approval_required=False, **kw)


def test_payload_carries_the_flag_only_when_on():
    assert _payload(auto_mode=True)["auto_mode"] is True
    # Omitting the field IS false on the backend; never send a literal false.
    assert "auto_mode" not in _payload(auto_mode=False)
    assert "auto_mode" not in _payload()


def test_start_stream_forwards_the_flag_by_keyword():
    start = next(n for n in ast.walk(ast.parse(TRANSPORT_PY))
                 if isinstance(n, ast.FunctionDef) and n.name == "start_stream")
    args = {a.arg: d for a, d in zip(start.args.args[-len(start.args.defaults):],
                                      start.args.defaults)}
    assert isinstance(args["auto_mode"], ast.Constant) and args["auto_mode"].value is False
    call = next(n for n in ast.walk(start) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "build_chat_payload")
    keywords = {k.arg: k.value for k in call.keywords}
    assert isinstance(keywords["auto_mode"], ast.Name)
    assert keywords["auto_mode"].id == "auto_mode"


def test_input_answers_never_carry_the_flag():
    start_input = next(n for n in ast.walk(ast.parse(TRANSPORT_PY))
                       if isinstance(n, ast.FunctionDef) and n.name == "start_input_stream")
    assert "auto_mode" not in ast.dump(start_input)


def test_composer_send_reads_the_scene_property_on_the_shared_turn_path():
    send = next(n for n in ast.walk(ast.parse(COMPOSER_SEND_PY))
                if isinstance(n, ast.FunctionDef) and n.name == "send_user_message")
    stream_calls = [n for n in ast.walk(send) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == "start_stream"]
    assert len(stream_calls) == 1, "one path for a fresh turn and an interjection"
    keywords = {k.arg for k in stream_calls[0].keywords}
    assert "auto_mode" in keywords
    assert "getattr(scene, 'mixie_chat_auto_mode', False)" in COMPOSER_SEND_PY
    input_calls = [n for n in ast.walk(send) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "start_input_stream"]
    assert input_calls and all("auto_mode" not in {k.arg for k in c.keywords}
                               for c in input_calls)


def test_send_telemetry_records_the_mode_content_free():
    assert '"auto_mode": bool(getattr(scene, "mixie_chat_auto_mode", False))' in CHAT_OPS_PY


# ---------------------------------------------------------------------------
# The sticky state and the toggle that flips it.
# ---------------------------------------------------------------------------

def test_scene_property_is_registered_and_unregistered():
    register = PROPS_PY[PROPS_PY.index("def register():"):PROPS_PY.index("def unregister():")]
    unregister = PROPS_PY[PROPS_PY.index("def unregister():"):]
    block = register[register.index("bpy.types.Scene.mixie_chat_auto_mode = BoolProperty("):]
    block = block[: block.index(")")]
    assert "default=False" in block
    # Sticky like Plan Mode: saved with the scene, never SKIP_SAVE.
    assert "SKIP_SAVE" not in block
    assert "'mixie_chat_auto_mode'" in unregister


def test_toggle_operator_flips_the_property_and_redraws_every_surface():
    assert 'bl_idname = "mixie_chat.toggle_auto_mode"' in SPECIAL_OPS_PY
    body = SPECIAL_OPS_PY[SPECIAL_OPS_PY.index("class MIXIE_CHAT_OT_toggle_auto_mode("):]
    body = body[: body.index("\nclass ")]
    assert "scene.mixie_chat_auto_mode = not scene.mixie_chat_auto_mode" in body
    # The island is its own window: context.screen alone misses it.
    assert "redraw_chat_areas()" in body
    classes = SPECIAL_OPS_PY[SPECIAL_OPS_PY.index("classes = ("):]
    assert "MIXIE_CHAT_OT_toggle_auto_mode," in classes


# ---------------------------------------------------------------------------
# The island chip: read-only state, laid out right of Voice, a native button.
# ---------------------------------------------------------------------------

def test_state_reader_mirrors_the_one_property():
    assert re.search(r"\bbool auto_mode;", DRAW_HH)
    gather = _function_body(STATE_CC, "void agent_ui_state_gather(")
    assert 'r_state->auto_mode = read_bool_prop(&scene_ptr, "mixie_chat_auto_mode");' in gather


def test_layout_places_auto_right_of_voice_and_closes_the_gap_without_it():
    assert "rctf chip_auto;" in LAYOUT_HH
    assert "#define AGENT_CHIP_AUTO_W" in THEME_HH
    fit = _function_body(LAYOUT_CC, "void agent_ui_layout_fit_controls(")
    assert fit.index("place(layout.chip_voice") < fit.index("place(layout.chip_auto")
    assert "in.voice_available = state.voice_available;" in fit
    assert "if (w <= 0) { rect = {}; return; }" in fit
    assert "AGENT_SWITCH_W * u" in fit
    # Measurement lives in the pure fitter (tests/test_island_voice_and_sketch_pill.py
    # sweeps it): no Voice chip, no width, so Auto closes the gap.
    forms = _function_body(CHIP_FIT_HH, "inline void agent_chip_forms(")
    assert "if (in.voice_available) {" in forms
    assert 'width("Auto", m.switch_w)' in forms
    assert 'agent_ui_layout_fit_controls(*r_layout, *r_state)' in BUBBLE_CC


def test_chip_row_paints_a_sliding_switch_on_the_shared_motion():
    enum = MOTION_HH[MOTION_HH.index("enum class AgentIslandControl") :]
    enum = enum[: enum.index("};")]
    order = re.findall(r"^\s*(\w+),", enum, re.M)
    assert order.index("Auto") == order.index("Voice") + 1
    assert order[-1] == "Count"
    body = _function_body(DRAW_CC, "void agent_ui_draw_chip_row(")
    assert "AgentIslandControl::Auto, layout->chip_auto, state->auto_mode" in body
    for macro in ("AGENT_SWITCH_W", "AGENT_SWITCH_H", "AGENT_SWITCH_INSET"):
        assert f"#define {macro}" in THEME_HH
        assert macro in body
    # The thumb slides with the control's selected motion — no jump.
    assert "* feedback.selected;" in body
    assert '"Auto"' in body


def test_chip_is_a_native_button_over_the_toggle_operator():
    controls = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_bottom(")
    assert "layout->chip_auto" in controls
    assert '"mixie_chat.toggle_auto_mode"' in controls
    assert "state->auto_mode ?" in controls
