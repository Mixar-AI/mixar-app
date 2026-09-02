/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the timeline dock's control row.
 *
 * The design gives the dock three groups — a Duration unit switch, a centred
 * transport, and the scene's Start/End frame fields — and moves the camera
 * and export actions it used to carry into the right column. The controls it
 * has no home for (capture, explore, immersive, collapse) survive as quiet
 * icons at the right edge rather than being dropped: collapse in particular
 * is the timeline's only way back.
 *
 * Painting only; every control is a real uiBut over the painted pixels.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

namespace {

/* Design px. */
constexpr float ROW_H = 30.0f;
constexpr float ROW_TOP_GAP = 18.0f;
constexpr float SIDE_PAD = 26.0f;
constexpr float CHIP_W = 44.0f;
constexpr float CHIP_H = 24.0f;
constexpr float FIELD_W = 100.0f;
constexpr float TRANSPORT_SIZE = 26.0f;
constexpr float TRANSPORT_GAP = 26.0f;
constexpr float TOOL_SIZE = 24.0f;
constexpr float TOOL_GAP = 6.0f;

/** Left/right pointing media triangle, optionally with a stop bar. */
void transport_glyph(const rctf &box, const bool forward, const bool bar, const bool pause)
{
  const float col[4] = {0.878f, 0.878f, 0.878f, 1.0f};
  const float cx = BLI_rctf_cent_x(&box);
  const float cy = BLI_rctf_cent_y(&box);
  const float h = BLI_rctf_size_y(&box) * 0.42f;
  const float w = h * 0.92f;
  if (pause) {
    const float thick = w * 0.42f;
    rctf left = {cx - w * 0.55f - thick, cx - w * 0.55f, cy - h, cy + h};
    rctf right = {cx + w * 0.55f, cx + w * 0.55f + thick, cy - h, cy + h};
    cinema_fill(left, thick * 0.3f, col);
    cinema_fill(right, thick * 0.3f, col);
    return;
  }
  const float dir = forward ? 1.0f : -1.0f;
  /* The bar sits on the leading edge, so the triangle shifts back to keep the
   * pair optically centred. */
  const float shift = bar ? -dir * w * 0.28f : 0.0f;
  cinema_triangle(cx + shift - dir * w * 0.5f, cy, dir * w, h, col);
  if (bar) {
    const float thick = std::max(1.0f, w * 0.30f);
    const float edge = cx + shift + dir * (w * 0.5f + thick * 0.6f);
    rctf stop = {std::min(edge, edge + dir * thick),
                 std::max(edge, edge + dir * thick),
                 cy - h,
                 cy + h};
    cinema_fill(stop, thick * 0.3f, col);
  }
}

/** Small labelled numeric field ("Start 1"). */
void frame_field(uiBlock *block,
                 PointerRNA *scene_ptr,
                 const char *label,
                 const char *property,
                 const rctf &rect,
                 const char *tooltip)
{
  const float u = cinema_unit();
  const float bg[4] = {0.149f, 0.149f, 0.149f, 1.0f};
  const float label_col[4] = CINEMA_COL_DIM;
  cinema_fill(rect, BLI_rctf_size_y(&rect) * 0.5f, bg);
  cinema_text_left(label,
                   rect.xmin + 14.0f * u,
                   BLI_rctf_cent_y(&rect),
                   CINEMA_FONT_VALUE * u,
                   label_col);

  /* The value IS the button: a Num button under Emboss::None paints only its
   * value string, so it reads as the design's plain number and still drags
   * and text-edits like any frame field. */
  rctf value = rect;
  value.xmin = rect.xmin + BLI_rctf_size_x(&rect) * 0.52f;
  UI_block_emboss_set(block, blender::ui::EmbossType::None);
  uiDefButR(block,
            ButType::Num,
            0,
            "",
            int(value.xmin),
            int(value.ymin),
            short(BLI_rctf_size_x(&value)),
            short(BLI_rctf_size_y(&value)),
            scene_ptr,
            property,
            0,
            0,
            0,
            tooltip);
  UI_block_emboss_set(block, blender::ui::EmbossType::Emboss);
}

/** One of the Duration unit chips. */
void unit_chip(uiBlock *block,
               const ARegion *region,
               const char *label,
               const char *value,
               const rctf &rect,
               const bool active)
{
  const float u = cinema_unit();
  const float on_bg[4] = CINEMA_COL_CHIP;
  const float off_bg[4] = {0.176f, 0.176f, 0.176f, 1.0f};
  const float on[4] = CINEMA_COL_VALUE;
  const float off[4] = CINEMA_COL_DIM;
  cinema_fill(rect, BLI_rctf_size_y(&rect) * 0.5f, active ? on_bg : off_bg);
  cinema_text_center(label,
                     BLI_rctf_cent_x(&rect),
                     BLI_rctf_cent_y(&rect),
                     CINEMA_FONT_LABEL * u,
                     active ? on : off);

  cinema_qa_record(region, rect, "director_ruler_unit", value, -1);
  uiBut *but = cinema_op_button(
      block, "WM_OT_context_set_enum", rect, "Label the ruler in minutes or seconds");
  if (but != nullptr) {
    PointerRNA *ptr = UI_but_operator_ptr_ensure(but);
    RNA_string_set(ptr, "data_path", "scene.mixar_director.ruler_unit");
    RNA_string_set(ptr, "value", value);
  }
}

/** Quiet right-edge icon the design has no slot for, but the mode needs. */
void tool_icon(uiBlock *block,
               const char *operator_id,
               const int icon,
               const rctf &rect,
               const char *tooltip,
               const bool enabled)
{
  UI_block_emboss_set(block, blender::ui::EmbossType::None);
  uiBut *but = uiDefIconButO(block,
                             ButType::But,
                             operator_id,
                             blender::wm::OpCallContext::InvokeRegionWin,
                             icon,
                             int(rect.xmin),
                             int(rect.ymin),
                             int(BLI_rctf_size_x(&rect)),
                             int(BLI_rctf_size_y(&rect)),
                             tooltip);
  UI_block_emboss_set(block, blender::ui::EmbossType::Emboss);
  director_overlay_disable_button(but, !enabled);
}

}  // namespace

float cinema_dock_control_height()
{
  return (ROW_H + ROW_TOP_GAP * 2.0f) * cinema_unit();
}

void cinema_draw_dock_panel(const ARegion *region)
{
  const float u = cinema_unit();
  const float top[4] = {0.098f, 0.098f, 0.098f, 1.0f};
  const float bottom[4] = {0.043f, 0.043f, 0.043f, 1.0f};
  const float line[4] = {0.145f, 0.145f, 0.145f, 1.0f};
  rctf panel = {float(region->winx) * 0.0f + 8.0f * u,
                float(region->winx) - 8.0f * u,
                6.0f * u,
                float(region->winy) - 6.0f * u};
  cinema_panel(panel, CINEMA_PANEL_RADIUS * u, top, bottom);
  cinema_outline(panel, CINEMA_PANEL_RADIUS * u, line, u);
}

void cinema_draw_dock_controls(uiBlock *block,
                               const bContext *C,
                               const ARegion *region,
                               const DirectorViewState &state,
                               const bool playing)
{
  cinema_qa_begin(region);
  const float u = cinema_unit();
  const float title[4] = {0.925f, 0.925f, 0.925f, 1.0f};
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));

  const float row_ymax = float(region->winy) - ROW_TOP_GAP * u;
  const float row_ymin = row_ymax - ROW_H * u;
  const float cy = (row_ymin + row_ymax) * 0.5f;

  /* -------- Duration -------- */
  float x = SIDE_PAD * u + 8.0f * u;
  cinema_text_left("Duration", x, cy, CINEMA_FONT_TITLE * u, title);
  x += cinema_text_width("Duration", CINEMA_FONT_TITLE * u) + 16.0f * u;

  char unit_id[16] = "SEC";
  PointerRNA state_ptr;
  if (view3d_director_state_pointer(scene, &state_ptr)) {
    PropertyRNA *prop = RNA_struct_find_property(&state_ptr, "ruler_unit");
    const char *identifier = nullptr;
    if (prop != nullptr &&
        RNA_property_enum_identifier(const_cast<bContext *>(C),
                                     &state_ptr,
                                     prop,
                                     RNA_property_enum_get(&state_ptr, prop),
                                     &identifier) &&
        identifier != nullptr)
    {
      BLI_strncpy(unit_id, identifier, sizeof(unit_id));
    }
  }
  const rctf min_chip = {x, x + CHIP_W * u, cy - CHIP_H * u * 0.5f, cy + CHIP_H * u * 0.5f};
  unit_chip(block, region, "Min", "MIN", min_chip, STREQ(unit_id, "MIN"));
  x += (CHIP_W + 8.0f) * u;
  const rctf sec_chip = {x, x + CHIP_W * u, cy - CHIP_H * u * 0.5f, cy + CHIP_H * u * 0.5f};
  unit_chip(block, region, "Sec", "SEC", sec_chip, STREQ(unit_id, "SEC"));

  /* -------- Transport (centred on the dock) -------- */
  const float group_w = TRANSPORT_SIZE * 3.0f * u + TRANSPORT_GAP * 2.0f * u;
  float tx = (float(region->winx) - group_w) * 0.5f;
  const struct {
    const char *op;
    bool forward;
    bool bar;
    const char *tip;
  } transport[3] = {
      {"MIXAR_OT_director_previous_beat", false, true, "Previous keyframe"},
      {"MIXAR_OT_director_preview", true, false, "Preview this shot"},
      {"MIXAR_OT_director_next_beat", true, true, "Next keyframe"},
  };
  const bool no_beats = state.beats.is_empty();
  for (int index = 0; index < 3; index++) {
    const rctf box = {tx,
                      tx + TRANSPORT_SIZE * u,
                      cy - TRANSPORT_SIZE * u * 0.5f,
                      cy + TRANSPORT_SIZE * u * 0.5f};
    transport_glyph(box, transport[index].forward, transport[index].bar, index == 1 && playing);
    cinema_qa_record(region, box, "director_transport", transport[index].tip, index);
    uiBut *but = cinema_op_button(block, transport[index].op, box, transport[index].tip);
    const bool enabled = index == 1 ? (state.beats.size() >= 2 &&
                                       state.frame_end > state.frame_start)
                                    : !no_beats;
    director_overlay_disable_button(but, !enabled);
    tx += (TRANSPORT_SIZE + TRANSPORT_GAP) * u;
  }

  /* -------- Right edge: mode tools, then the frame range -------- */
  float right = float(region->winx) - (SIDE_PAD + 8.0f) * u;
  const struct {
    const char *op;
    int icon;
    const char *tip;
    bool enabled;
  } tools[5] = {
      {"MIXAR_OT_director_toggle_timeline", ICON_X, "Collapse timeline", true},
      {"MIXAR_OT_director_toggle_immersive",
       ICON_FULLSCREEN_ENTER,
       "Toggle immersive Director view",
       true},
      {"MIXAR_OT_director_explore",
       ICON_VIEW_PAN,
       "Fly the scene freely without moving the shot camera",
       state.has_shot},
      {state.locked ? "MIXAR_OT_director_new_take" : "MIXAR_OT_director_capture_beat",
       state.locked ? ICON_DUPLICATE : ICON_KEYFRAME_HLT,
       state.locked ? "Start an editable child take" : "Capture the live camera pose (F)",
       state.has_camera},
      /* The camera entry point. The right column carries it as "+ Add Camera",
       * but that column only draws in the wide layout — without this the
       * compact one has no way to start directing at all. */
      {state.has_shot ? "MIXAR_OT_director_new_shot" : "MIXAR_OT_director_start",
       state.has_shot ? ICON_ADD : ICON_CAMERA_DATA,
       state.has_shot ? "Create a new shot camera from this view" :
                        "Direct the active scene camera from the viewport",
       true},
  };
  for (const auto &tool : tools) {
    const rctf box = {right - TOOL_SIZE * u,
                      right,
                      cy - TOOL_SIZE * u * 0.5f,
                      cy + TOOL_SIZE * u * 0.5f};
    tool_icon(block, tool.op, tool.icon, box, tool.tip, tool.enabled);
    right -= (TOOL_SIZE + TOOL_GAP) * u;
  }
  right -= 14.0f * u;

  if (scene != nullptr) {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    const rctf end_rect = {right - FIELD_W * u, right, row_ymin, row_ymax};
    frame_field(block, &scene_ptr, "End", "frame_end", end_rect, "Last frame of the scene range");
    right -= (FIELD_W + 8.0f) * u;
    const rctf start_rect = {right - FIELD_W * u, right, row_ymin, row_ymax};
    frame_field(
        block, &scene_ptr, "Start", "frame_start", start_rect, "First frame of the scene range");
  }
}
