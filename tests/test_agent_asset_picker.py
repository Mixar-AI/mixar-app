# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The agent's asset picker: a pending library question takes over the Agent tab.

When the agent's asset-library search finds several close matches it pauses
with a ``choice`` question whose buttons carry asset identity. While it is
pending the island shows ONLY those picks — the top five — as a Library-style
grid instead of the transcript, and the transcript comes back once it is
answered. The rule is derived, never stored; Python
(``space_mixie_chat/core/asset_picker.py``) and C++
(``space_mixie_chat/mixie_chat_asset_picker.cc``) implement it side by side,
so these tests pin both, plus the Library painters the pane re-uses and the
production layout resolver compiled on its own.
"""

import importlib.util
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "src/scripts/mixar/modules"
EDITORS = ROOT / "src/source/blender/editors"
BUBBLE = EDITORS / "space_agent_bubble"
CHAT = EDITORS / "space_mixie_chat"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through it
    spec.loader.exec_module(module)
    return module


picker = _load("asset_picker_under_test", MODULES / "space_mixie_chat/core/asset_picker.py")


# ── fakes ────────────────────────────────────────────────────────────────


class Action:
    def __init__(self, label, value=None, style="DEFAULT", asset_name="", library="",
                 asset_type="", image="", score=-1.0):
        self.label, self.value, self.style = label, value if value is not None else label, style
        self.asset_name, self.library, self.asset_type = asset_name, library, asset_type
        self.image, self.score = image, score


def asset(i, **kw):
    return Action(f"Chair {i}", asset_name=f"Chair {i}", library="Mine", asset_type="Object",
                  image=f"MIXAR_ASSETCHOICE_{i}", score=round(0.9 - i * 0.01, 4), **kw)


def question_actions(n=5):
    return [asset(i) for i in range(n)] + [
        Action("Model from scratch"), Action("Cancel", "abort", style="DANGER")]


class Bubble:
    def __init__(self, sender="AGENT", input_type="choice", actions=(), content="Which chair?",
                 bubble_id="b1"):
        self.sender, self.input_type, self.content = sender, input_type, content
        self.action_items, self.bubble_id, self.text = list(actions), bubble_id, ""


class Scene:
    def __init__(self, messages, state="AWAITING_INPUT"):
        self.mixie_chat_messages, self.mixie_chat_state = list(messages), state


# ── the rule ─────────────────────────────────────────────────────────────


def test_a_pending_asset_question_is_the_live_picker():
    live = picker.live_asset_picker(Scene([Bubble(actions=question_actions(7))]))
    assert live is not None and live.bubble_id == "b1" and live.question == "Which chair?"
    # The top five only, best first, with their identity and score.
    assert [p.asset_name for p in live.picks] == [f"Chair {i}" for i in range(5)]
    assert live.picks[0].score == 0.9 and live.picks[0].image == "MIXAR_ASSETCHOICE_0"
    assert live.scratch_value == "Model from scratch" and live.cancel_value == "abort"


@pytest.mark.parametrize("scene", [
    Scene([Bubble(actions=question_actions())], state="BUSY"),              # answered / resuming
    Scene([Bubble(actions=question_actions())], state="IDLE"),
    Scene([Bubble(actions=[Action("Yes"), Action("No")])]),                 # a plain choice
    Scene([Bubble(input_type="text", actions=question_actions())]),         # not a choice
    Scene([Bubble(actions=[])]),                                            # items cleared by a click
    Scene([Bubble(actions=question_actions()),                              # superseded by a newer question
           Bubble(input_type="confirm", bubble_id="b2", actions=[Action("Yes")])]),
    Scene([Bubble(sender="USER", actions=question_actions())]),
    Scene([]),
])
def test_anything_else_is_not_a_picker(scene):
    assert picker.live_asset_picker(scene) is None


def test_an_older_answered_question_does_not_hide_a_newer_picker():
    scene = Scene([Bubble(input_type="text", bubble_id="old"),
                   Bubble(sender="USER", input_type=""),
                   Bubble(actions=question_actions(), bubble_id="new")])
    assert picker.live_asset_picker(scene).bubble_id == "new"


def test_cap_keeps_plain_buttons_and_the_first_five_assets():
    actions = [{"label": f"A{i}", "asset_name": f"A{i}"} for i in range(8)]
    actions += [{"label": "Model from scratch"}, {"label": "Cancel", "value": "abort"}]
    kept = picker.cap_asset_actions(actions)
    assert [a["label"] for a in kept] == ["A0", "A1", "A2", "A3", "A4", "Model from scratch", "Cancel"]


def test_present_selects_the_best_match_and_brings_the_agent_tab_forward(monkeypatch):
    wm = types.SimpleNamespace(mixie_chat_asset_pick_selected="stale", mixar_bubble_tab="GENERATIONS",
                               mixar_mark_armed=False, mixie_chat_voice_listening=False)
    monkeypatch.setitem(sys.modules, "bpy", types.SimpleNamespace(
        context=types.SimpleNamespace(window_manager=wm)))
    picker.present(Bubble(actions=question_actions()))
    assert wm.mixie_chat_asset_pick_selected == "" and wm.mixar_bubble_tab == "AGENT"

    # Sketch / Voice lock the tab strip: the picker never breaks that lock.
    wm.mixar_bubble_tab, wm.mixie_chat_voice_listening = "QUEUE", True
    picker.present(Bubble(actions=question_actions()))
    assert wm.mixar_bubble_tab == "QUEUE"
    # A plain choice changes nothing.
    wm.mixie_chat_voice_listening = False
    picker.present(Bubble(actions=[Action("Yes"), Action("No")]))
    assert wm.mixar_bubble_tab == "QUEUE"


# ── slot processor: score, top-five cap, present() ──────────────────────


def test_the_actions_slot_caps_asset_questions_and_stores_scores():
    src = _read(MODULES / "space_mixie_chat/core/slot_processor.py")
    body = src[src.index("def _apply_actions_slot"):src.index("def _apply_images_slot")]
    assert 'getattr(bubble, "input_type", "") == "choice"' in body
    assert "asset_picker.cap_asset_actions(actions)" in body
    assert 'action_data.get("score")' in body and "action.score" in body
    assert "asset_picker.present(bubble)" in body
    # Buttons still never own the AWAITING_INPUT transition.
    assert "set_state" not in body


def test_undo_keeps_the_picker_identity():
    src = _read(MODULES / "space_mixie_chat/core/undo_guard.py")
    for key in ("asset_name", "library", "blend_file", "asset_type", "score", "image"):
        assert f"'{key}': action.{key}" in src, key
    assert "setattr(action, key, action_data[key])" in src


def test_action_item_carries_a_score():
    src = _read(MODULES / "space_mixie_chat/ui/properties/chat_slot_types.py")
    block = src[src.index("class MixieChatActionItem"):src.index("class MixieChatImageItem")]
    score = block[block.index("score: FloatProperty("):]
    assert "default=-1.0" in score[:score.index("\n    )")]


# ── one contract, two languages ──────────────────────────────────────────


def test_python_and_cpp_agree_on_the_limits_and_the_selection_property():
    header = _read(EDITORS / "include/ED_mixie_chat_asset_picker.hh")
    layout = _read(BUBBLE / "agent_ui_asset_picker_layout.hh")
    props = _read(MODULES / "agent_bubble/ui/properties/asset_picker_props.py")
    assert f"#define MIXIE_ASSET_PICKER_MAX {picker.MAX_ASSET_PICKS}" in header
    assert f"constexpr int PICK_MAX = {picker.MAX_ASSET_PICKS};" in layout
    assert picker.MAX_ASSET_PICKS == 5
    assert f'#define MIXIE_ASSET_PICKER_SELECTED_PROP "{picker.SELECTED_PROP}"' in header
    assert f'PROP_NAME = "{picker.SELECTED_PROP}"' in props
    assert f"WindowManager.{picker.SELECTED_PROP} = StringProperty(" in props
    assert "'SKIP_SAVE'" in props


def test_cpp_reader_derives_the_same_rule():
    src = _read(CHAT / "mixie_chat_asset_picker.cc")
    gather = src[src.index("bool mixie_chat_asset_picker_gather"):]
    assert 'enum_is(&scene_ptr, "mixie_chat_state", "AWAITING_INPUT")' in gather
    assert "for (int i = length - 1; i >= 0; i--)" in gather           # newest first
    assert 'enum_is(&message, "sender", "AGENT")' in gather
    assert 'STREQ(input_type, "choice")' in gather
    assert 'read_string(item, "asset_name"' in src
    assert "picker->count >= MIXIE_ASSET_PICKER_MAX" in src             # the top five
    assert 'enum_is(item, "style", "DANGER") || STREQ(value, "abort")' in src
    assert 'read_string(item, "score"' not in src and 'read_float(item, "score", -1.0f)' in src
    # The user's own modal surfaces are never replaced.
    shown = src[src.index("bool mixie_chat_asset_picker_shown"):]
    for reader in ("rules", "history", "ink"):
        assert f"mixie_chat_{reader}_read_visible(wm)" in shown


def test_chat_dispatch_stands_down_while_the_picker_shows():
    src = _read(CHAT / "mixie_chat_main_region.cc")
    live = src[src.index("static bool mixie_chat_dispatch_is_live"):src.index("int mixie_chat_ui_handler")]
    assert "return !mixie_chat_asset_picker_shown(C, nullptr);" in live
    assert 'if (!STREQ(ident, "AGENT"))' in live
    assert "mixie_chat_asset_picker.cc" in _read(CHAT / "CMakeLists.txt")


def test_island_draws_the_picker_instead_of_the_transcript():
    src = _read(BUBBLE / "space_agent_bubble.cc")
    draw = src[src.index("static void agent_bubble_island_region_draw"):]
    branch = draw.index("mixie_chat_asset_picker_shown(C, &picker)")
    transcript = draw.index("mixie_chat_main_region_draw(C, region);")
    assert branch < transcript, "the picker must be decided before the transcript draws"
    block = draw[branch:transcript]
    # Drawn like a pane tab: stale message rects dropped, island painted, then the pane.
    assert "agent_bubble_clear_chat_layout_cache(C);" in block
    # The TRANSCRIPT slice, never the whole panel: the composer strip and chip
    # row live in the TOOLS region below, and a foot-anchored "Use This Asset"
    # laid out against the panel's bottom fell into that band and was unseen.
    assert "rctf picker_region = layout.transcript;" in block
    assert "= layout.panel;" not in block
    assert "agent_ui_asset_picker_draw(C, region, picker_region, u, picker);" in block
    assert "return;" in block
    assert "agent_ui_asset_picker_qa_register();" in src


def test_an_empty_send_answers_with_the_selected_pick():
    """Send (or Enter) on an empty composer while the picker is up accepts the
    highlighted tile — it used to warn "Cannot send empty message"."""
    src = _read(MODULES / "space_mixie_chat/ui/operators/chat_ops.py")
    accept = src.index("asset_picker.live_asset_picker(scene)")
    assert accept < src.index('"Cannot send empty message"')
    body = src[accept:src.index('"Cannot send empty message"')]
    assert "asset_picker.SELECTED_PROP" in body and "live.picks[0]" in body
    assert "bpy.ops.mixie_chat.select_slot_action(" in body
    assert "bubble_id=live.bubble_id, action_value=pick.value" in body


def test_long_names_get_a_second_caption_line_broken_at_a_separator():
    grid = _read(BUBBLE / "agent_ui_asset_picker.cc")
    layout = _read(BUBBLE / "agent_ui_asset_picker_layout.hh")
    assert "int name_lines;" in layout and "1.35f * float(name_lines)" in layout
    # The painter measures every name against the tile and re-resolves.
    assert "in.name_lines = name_lines;" in grid
    assert "agent_ui_asset_pick_wrap(pick.asset_name, text_w, font_cap, name_a, name_b);" in grid
    # "minotaur_sword_001" breaks after a separator, not only at a space.
    wrap = grid[grid.index("void agent_ui_asset_pick_wrap"):grid.index("void agent_ui_asset_pick_answer_button")]
    assert "c == '_' || c == '-' || c == '.' || c == '/'" in wrap


def test_the_pane_is_painted_with_the_librarys_own_pieces():
    grid = _read(BUBBLE / "agent_ui_asset_picker.cc")
    detail = _read(BUBBLE / "agent_ui_asset_picker_detail.cc")
    layout = _read(BUBBLE / "agent_ui_asset_picker_layout.hh")
    assert "agent_ui_generations_input(panel, u)" in grid                    # same frame inputs
    assert "agent_ui_generations_resolve(base)" in layout                    # same resolver
    for token in ("pane_wash_paint", "pane_column_divider", "GEN_COL_TILE", "GEN_TILE_RADIUS",
                  "GEN_SEL_BORDER", "AgentAccent", "AGENT_ICON_MESH", "GenViewportClip",
                  "pane_image_thumb_draw"):
        assert token in grid, token
    for token in ("PANE_COL_GENERATE", "GEN_COL_SECONDARY", "GEN_COL_META", "GEN_DETAIL_FOOT",
                  "GEN_PREVIEW_H", "actions_stacked"):
        assert token in detail, token
    # Tiles SELECT (the Library's stock context operator); actions ANSWER the agent
    # through the operator a transcript button click runs.
    assert '"wm.context_set_string"' in grid
    assert '"window_manager." MIXIE_ASSET_PICKER_SELECTED_PROP' in grid
    assert '"mixie_chat.select_slot_action"' in grid
    assert 'RNA_string_set(op_ptr, "bubble_id", picker.bubble_id);' in grid
    assert "picker.scratch_value" in detail and "pick.value" in detail


def test_qa_targets_and_build_registration():
    qa = _read(BUBBLE / "agent_ui_asset_picker_qa.cc")
    assert '"asset_pick_tile"' in qa and '"asset_pick_action"' in qa
    assert "AGENT_ASSET_PICKER_BLOCK" in qa
    cmake = _read(BUBBLE / "CMakeLists.txt")
    for name in ("agent_ui_asset_picker.cc", "agent_ui_asset_picker_detail.cc",
                 "agent_ui_asset_picker_qa.cc", "agent_ui_asset_picker_layout.hh"):
        assert name in cmake, name


@pytest.mark.parametrize("path", [
    CHAT / "mixie_chat_asset_picker.cc",
    CHAT / "mixie_chat_asset_picker_drop.cc",
    BUBBLE / "agent_ui_asset_picker.cc",
    BUBBLE / "agent_ui_asset_picker_detail.cc",
    BUBBLE / "agent_ui_asset_picker_qa.cc",
    BUBBLE / "agent_ui_asset_picker_layout.hh",
    MODULES / "space_mixie_chat/core/asset_picker.py",
    MODULES / "space_mixie_chat/ui/operators/asset_pick_drop_ops.py",
])
def test_new_files_respect_the_500_line_rule(path):
    assert len(_read(path).splitlines()) <= 500


# ── the production layout, compiled and executed ─────────────────────────


def _cxx():
    for name in ("g++", "clang++"):
        path = shutil.which(name)
        if not path:
            continue
        probe = subprocess.run([path, "-std=c++17", "-x", "c++", "-fsyntax-only", "-"],
                               input=b"#include <algorithm>\nint main(){return 0;}\n",
                               capture_output=True)
        if probe.returncode == 0:
            return path
    return None


LAYOUT_PROGRAM = r'''#include <cstdio>
#include <cstring>
#include "agent_ui_asset_picker_layout.hh"
using namespace blender;

static int fails = 0;
#define CHECK(cond) do { if (!(cond)) { \
  std::fprintf(stderr, "fail %d: %s (w=%g h=%g font=%g n=%d)\n", __LINE__, #cond, W, H, F, N); \
  fails++; } } while (0)

static float text_px(const char *s, float font) { return font * 0.52f * float(std::strlen(s)); }
static bool overlap(const GenBox &a, const GenBox &b) {
  return a.xmin < b.xmax - 0.5f && b.xmin < a.xmax - 0.5f &&
         a.ymin < b.ymax - 0.5f && b.ymin < a.ymax - 0.5f;
}

static PickFrame layout(float W, float H, float F, int N, int lines, int names = 1) {
  const float u = W / 1310.0f;
  PickResolveInput in{};
  GenResolveInput &b = in.base;
  b.panel_xmin = 0; b.panel_xmax = W; b.panel_ymin = 0; b.panel_ymax = H; b.u = u;
  b.font_chip = F; b.font_cap = F * 0.9f; b.font_title = F * 1.4f; b.font_meta = F * 0.85f;
  b.font_desc = F * 0.95f; b.font_action = F * 0.85f; b.font_lib = F * 0.9f;
  b.rail_w_design = 198 * u; b.rail_h_design = 47 * u; b.tile_design = 146 * u;
  b.preview_design = 316 * u; b.sort_w_design = 56 * u; b.foot_design = 28 * u;
  b.cap_gap_design = 10 * u; b.row_gap_design = 20 * u; b.lib_row_design = 38 * u; b.max_cols = 4;
  in.cancel_label = text_px(PICK_CANCEL_LABEL, F);
  in.action_primary = text_px(PICK_ACTION_PRIMARY, b.font_action);
  in.action_secondary = text_px(PICK_ACTION_SECONDARY, b.font_action);
  in.count = N;
  in.question_lines = lines;
  in.name_lines = names;
  return agent_ui_asset_picker_resolve(in);
}

int main() {
  float W = 1310, H = 360, F = 18; int N = 5;
  /* The island's default size: all five picks on ONE row of full Library tiles. */
  {
    PickFrame f = layout(W, H, F, N, 1);
    CHECK(f.cols == 5 && f.rows == 1);
    CHECK(f.tile > 145.9f * (W / 1310.0f));
    CHECK(!f.gen.actions_stacked);
  }
  for (W = 420; W <= 1700; W += 80) {
    for (H = 260; H <= 620; H += 60) {
      for (float font : {12.0f, 18.0f, 26.0f}) {
        F = font;
        for (N = 1; N <= 7; N++) {
          for (int lines = 1; lines <= 2; lines++) {
           for (int names = 1; names <= 2; names++) {
            PickFrame f = layout(W, H, F, N, lines, names);
            /* A second name line grows the caption by exactly one line pitch. */
            CHECK(f.caption >= f.gen.cap_gap + (1.1f + 1.35f * float(names)) * F * 0.9f - 0.5f);
            if (names == 2) {
              CHECK(f.caption - layout(W, H, F, N, lines, 1).caption > 1.3f * F * 0.9f);
            }
            const int n = N < PICK_MAX ? N : PICK_MAX;
            CHECK(f.count == n && f.cols >= 1 && f.cols <= n);
            CHECK(f.rows == (n + f.cols - 1) / f.cols);
            /* The grid stays left of the detail column; the header above the grid. */
            CHECK(f.view.xmax <= f.gen.detail_div_x + 0.5f);
            CHECK(f.view.xmin >= 0.0f && f.gen.detail_x + f.gen.detail_w <= W + 0.5f);
            CHECK(f.question.ymin >= f.view.ymax - 0.5f);
            if (f.cancel.xmax > f.cancel.xmin) {
              CHECK(!overlap(f.question, f.cancel));
              CHECK(f.cancel.xmax <= f.view.xmax + 0.5f);
            }
            for (int i = 0; i < f.count; i++) {
              const GenBox &t = f.tiles[i];
              CHECK(t.xmin >= f.view.xmin - 0.5f && t.xmax <= f.view.xmax + 0.5f);
              CHECK(t.ymax <= f.view.ymax + 0.5f);
              CHECK(t.xmax - t.xmin > 0.5f && (t.ymax - t.ymin) - (t.xmax - t.xmin) < 0.01f);
              for (int j = i + 1; j < f.count; j++) {
                CHECK(!overlap(t, f.tiles[j]));
              }
            }
            /* Whenever the tile is above its floor, every caption fits the panel. */
            const GenBox &last = f.tiles[f.count - 1];
            if (f.tile > pick_tile_floor(f.gen.u) + 0.5f) {
              CHECK(last.ymin - f.caption >= f.view.ymin - 0.5f);
            }
            /* Never larger than the Library's own tile cap. */
            CHECK(f.tile <= std::max(146.0f * (W / 1310.0f), gen_min_tile(F * 0.9f, W / 1310.0f)) + 0.5f);
           }
          }
        }
      }
    }
  }
  return fails ? 1 : 0;
}
'''


def test_picker_layout_fits_at_every_size(tmp_path):
    compiler = _cxx()
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source = tmp_path / "picker_layout.cc"
    source.write_text(LAYOUT_PROGRAM)
    binary = tmp_path / "picker_layout"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Werror", "-I", str(BUBBLE), str(source),
                    "-o", str(binary)], check=True)
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[:4000]


# ── drag a tile into the viewport, like a Library tile ───────────────────


def test_a_pick_carries_its_blend_file_for_a_viewport_drop():
    a = Action("Chair 0", asset_name="Chair 0", library="Mine", asset_type="Object")
    a.blend_file = "props/chair.blend"
    live = picker.live_asset_picker(Scene([Bubble(actions=[a, Action("Model from scratch")])]))
    assert live.picks[0].blend_file == "props/chair.blend"
    assert picker.drop_reply(live.picks[0]).startswith("I placed 'Chair 0' from my library (Mine)")
    assert "do not append it again" in picker.drop_reply(live.picks[0])


def test_ground_point_is_where_the_drop_ray_meets_the_floor():
    assert picker.ground_point((0.0, 0.0, 10.0), (0.0, 0.0, -1.0)) == (0.0, 0.0, 0.0)
    x, y, z = picker.ground_point((1.0, 2.0, 4.0), (0.5, 0.0, -1.0))
    assert (round(x, 6), round(y, 6), z) == (3.0, 2.0, 0.0)
    assert picker.ground_point((0.0, 0.0, 10.0), (1.0, 0.0, 0.0)) is None      # parallel
    assert picker.ground_point((0.0, 0.0, 10.0), (0.0, 0.0, 1.0)) is None      # looking up
    assert picker.ground_point((0.0, 0.0, -2.0), (0.0, 0.0, -1.0)) is None     # floor behind


def test_tiles_start_a_name_drag_with_their_preview():
    grid = _read(BUBBLE / "agent_ui_asset_picker.cc")
    header = _read(EDITORS / "include/ED_mixie_chat_asset_picker.hh")
    assert '#define MIXIE_ASSET_PICK_DRAG_PREFIX "Use library asset: "' in header
    tiles = grid[grid.index("ui::Block *block = ui::block_begin"):grid.index("agent_ui_asset_picker_detail(C, block, panel, frame, picker);")]
    # A PreviewTile (drag-start lives in its event path), the Library's select operator
    # attached afterwards, then the name drag owned by the drag and the preview riding it.
    assert "ui::ButtonType::PreviewTile" in tiles and "ButtonType::But," not in tiles
    assert 'WM_operatortype_find("wm.context_set_string", true)' in tiles
    assert "MIXIE_ASSET_PICK_DRAG_PREFIX) + pick.value" in tiles
    assert "ui::BUT_DRAGPOIN_FREE | ui::BUT_DRAG_FULL_BUT" in tiles
    assert "but->imb = ibuf;" in tiles and "BKE_image_release_ibuf(image, ibuf, lock);" in tiles
    assert '"../interface/interface_intern.hh"' in grid


def test_the_viewport_drop_places_the_pick_and_answers():
    drop = _read(CHAT / "mixie_chat_asset_picker_drop.cc")
    assert "drag->type != WM_DRAG_NAME" in drop and "MIXIE_ASSET_PICK_DRAG_PREFIX" in drop
    assert "ED_operator_region_view3d_active" in drop
    assert 'WM_dropboxmap_find("Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW)' in drop
    assert '"MIXIE_CHAT_OT_place_asset_pick"' in drop
    assert 'RNA_int_set(&props, "mouse_x", event->xy[0] - region->winrct.xmin);' in drop
    # Registered at startup beside the reference-image drop, and built.
    assert "WM_operatortype_append(MIXIE_CHAT_OT_drop_asset_pick);" in _read(CHAT / "mixie_chat_ops.cc")
    assert "mixie_chat_asset_pick_dropboxes();" in _read(CHAT / "mixie_chat_dragdrop.cc")
    assert "mixie_chat_asset_picker_drop.cc" in _read(CHAT / "CMakeLists.txt")
    # The Python half: append at the drop point, then the typed reply.
    ops = _read(MODULES / "space_mixie_chat/ui/operators/asset_pick_drop_ops.py")
    assert 'bl_idname = "mixie_chat.place_asset_pick"' in ops
    assert "location=location" in ops and "asset_picker.ground_point(" in ops
    assert "bpy.ops.mixie_chat.send_message(" in ops
    assert "message_override=asset_picker.drop_reply(pick)" in ops
    browse = _read(MODULES / "space_mixie_chat/core/library_browse.py")
    assert "location=None):" in browse and "mathutils.Vector(location) if location is not None" in browse
