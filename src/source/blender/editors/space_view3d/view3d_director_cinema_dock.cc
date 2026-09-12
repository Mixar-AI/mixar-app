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
 * Painting only; every control is a real ui::Button over the painted pixels.
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

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Design px. */
constexpr float ROW_H = 30.0f;
constexpr float ROW_TOP_GAP = 18.0f;
constexpr float SIDE_PAD = 26.0f;
constexpr float CHIP_W = 44.0f;
constexpr float CHIP_H = 26.0f;
constexpr float FIELD_W = 100.0f;
/** Transport hit box (square) and the clear space between neighbours: the
 * glyph centres sit `TRANSPORT_SIZE + TRANSPORT_GAP` = 44 apart. */
constexpr float TRANSPORT_SIZE = 26.0f;
constexpr float TRANSPORT_GAP = 18.0f;
/* Transport glyph sizes, measured off the design mock (see #transport_glyph).
 * They are explicit so the hit box no longer decides how big a glyph is. */
constexpr float PLAY_H = 18.0f;
constexpr float STEP_H = 12.0f;
constexpr float DOT_D = 5.5f;
constexpr float STEP_GAP = 3.0f;
/** Triangle width over height: the mock's play is 16 x 15, a step's 8.5 x 9.5. */
constexpr float GLYPH_ASPECT = 0.95f;
/** One muted grey for every transport glyph (mock: RGB 135, pause included). */
constexpr float TRANSPORT_COL[4] = {0.53f, 0.53f, 0.53f, 1.0f};
constexpr float TOOL_SIZE = 24.0f;
constexpr float TOOL_GAP = 6.0f;
/** Clear space the frame fields must keep from the centred transport. */
constexpr float FIELD_CLEARANCE = 16.0f;

/**
 * Media glyphs per the design: the preview (play) is a filled triangle; a
 * step is a smaller triangle pointing outward with a dot on its INNER side
 * (`◂●  ▶  ●▸`), not the stock bar-on-the-outside.
 *
 * Proportions measured off the 1x design mock (glyph pixel bounding boxes):
 * play 16 wide x 15 tall (a squat, near-equilateral triangle, NOT tall and
 * narrow); a step pair 15 x 10 overall — triangle ~8.5 x 9.5, dot ~4.5 in
 * diameter, ~2.5 between the triangle's flat inner edge and the dot; glyph
 * centres 36 apart, i.e. ~2.4x the play height; every glyph the same muted
 * grey. The tokens above (`PLAY_H`, `STEP_H`, `DOT_D`, `STEP_GAP`,
 * `GLYPH_ASPECT`, `TRANSPORT_COL`) are those numbers rounded to the design's
 * unit; only `box` centre is used — the hit box never sizes the glyph.
 */
void transport_glyph(const rctf &box, const bool forward, const bool step, const bool pause)
{
  const float u = cinema_unit();
  const float *col = TRANSPORT_COL;
  const float cx = BLI_rctf_cent_x(&box);
  const float cy = BLI_rctf_cent_y(&box);
  if (pause) {
    /* Two bars as tall as the play glyph, each ~0.3 of that wide and as far
     * apart. */
    const float half = PLAY_H * 0.5f * u;
    const float bar = PLAY_H * 0.3f * u;
    const float gap = PLAY_H * 0.3f * u;
    rctf left = {cx - gap * 0.5f - bar, cx - gap * 0.5f, cy - half, cy + half};
    rctf right = {cx + gap * 0.5f, cx + gap * 0.5f + bar, cy - half, cy + half};
    cinema_fill(left, bar * 0.3f, col);
    cinema_fill(right, bar * 0.3f, col);
    return;
  }
  const float dir = forward ? 1.0f : -1.0f;
  if (!step) {
    /* Flat edge left, apex right, the bounding box centred on the slot. */
    const float half = PLAY_H * 0.5f * u;
    const float w = PLAY_H * GLYPH_ASPECT * u;
    cinema_triangle(cx - dir * w * 0.5f, cy, dir * w, half, col);
    return;
  }
  /* Step: a smaller triangle plus a dot, the pair centred on the slot. The
   * dot sits on the side facing the play button. */
  const float sh = STEP_H * 0.5f * u; /* half height */
  const float sw = STEP_H * GLYPH_ASPECT * u;
  const float dot = DOT_D * u;
  const float gap = STEP_GAP * u;
  const float total = sw + gap + dot;
  const float outer = cx + dir * total * 0.5f; /* outer end of the pair */
  /* Triangle: flat edge on the inner side, apex at the outer end. */
  cinema_triangle(outer - dir * sw, cy, dir * sw, sh, col);
  const float dot_x0 = outer - dir * (sw + gap);
  const float dot_x1 = dot_x0 - dir * dot;
  rctf disc = {std::min(dot_x0, dot_x1), std::max(dot_x0, dot_x1), cy - dot * 0.5f, cy + dot * 0.5f};
  cinema_fill(disc, dot * 0.5f, col);
}

/** Small labelled numeric field ("Start 1"). */
void frame_field(ui::Block *block,
                 PointerRNA *scene_ptr,
                 const char *label,
                 const char *property,
                 const rctf &rect,
                 const char *tooltip)
{
  const float u = cinema_unit();
  const float bg[4] = {0.149f, 0.149f, 0.149f, 1.0f};
  const float label_col[4] = CINEMA_COL_DIM;
  /* The same radius as every other rounded control, capped to a pill. */
  cinema_fill(rect, std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&rect) * 0.5f), bg);
  cinema_text_left(label,
                   rect.xmin + 12.0f * u,
                   BLI_rctf_cent_y(&rect),
                   CINEMA_FONT_VALUE * u,
                   label_col);

  /* The value IS the button: a Num button under Emboss::None paints only its
   * value string, so it reads as the design's plain number and still drags
   * and text-edits like any frame field. */
  rctf value = rect;
  value.xmin = rect.xmin + BLI_rctf_size_x(&rect) * 0.52f;
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  uiDefButR(block,
            ui::ButtonType::Num,
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
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
}

/** One of the Duration unit chips. */
void unit_chip(ui::Block *block,
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
  cinema_fill(rect, std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&rect) * 0.5f), active ? on_bg : off_bg);
  cinema_text_center(label,
                     BLI_rctf_cent_x(&rect),
                     BLI_rctf_cent_y(&rect),
                     CINEMA_FONT_LABEL * u,
                     active ? on : off);

  cinema_qa_record(region, rect, "director_ruler_unit", value, -1);
  ui::Button *but = cinema_op_button(
      block, "WM_OT_context_set_enum", rect, "Label the ruler in minutes or seconds");
  if (but != nullptr) {
    PointerRNA *ptr = ui::button_operator_ptr_ensure(but);
    RNA_string_set(ptr, "data_path", "scene.mixar_director.ruler_unit");
    RNA_string_set(ptr, "value", value);
  }
}

/** Quiet right-edge icon the design has no slot for, but the mode needs. */
void tool_icon(ui::Block *block,
               const char *operator_id,
               const int icon,
               const rctf &rect,
               const char *tooltip,
               const bool enabled)
{
  ui::Button *but = cinema_icon_button(block, operator_id, icon, rect, tooltip);
  director_overlay_disable_button(but, !enabled);
}

/** Right edge of the centred transport group, in region px. */
float transport_right_edge(const ARegion *region)
{
  const float u = cinema_unit();
  const float group_w = TRANSPORT_SIZE * 3.0f * u + TRANSPORT_GAP * 2.0f * u;
  return (float(region->winx) + group_w) * 0.5f;
}

/** Transport triple (previous / preview / next), centred on the dock. */
void draw_transport(ui::Block *block,
                    const ARegion *region,
                    const DirectorViewState &state,
                    const float cy,
                    const bool playing)
{
  const float u = cinema_unit();
  const float group_w = TRANSPORT_SIZE * 3.0f * u + TRANSPORT_GAP * 2.0f * u;
  float tx = (float(region->winx) - group_w) * 0.5f;
  const struct {
    const char *op;
    bool forward;
    bool step;
    const char *tip;
  } transport[3] = {
      {"MIXAR_OT_director_previous_beat", false, true, "Previous keyframe"},
      {"MIXAR_OT_director_preview", true, false, "Preview this shot"},
      {"MIXAR_OT_director_next_beat", true, true, "Next keyframe"},
  };
  const bool no_beats = state.beats.is_empty();
  for (int index = 0; index < 3; index++) {
    /* Every slot is the same TRANSPORT_SIZE hit box; the glyphs size
     * themselves (#transport_glyph) and only borrow the box's centre. */
    const float size = TRANSPORT_SIZE * u;
    const float slot_cx = tx + TRANSPORT_SIZE * u * 0.5f;
    const rctf box = {slot_cx - size * 0.5f, slot_cx + size * 0.5f, cy - size * 0.5f, cy + size * 0.5f};
    transport_glyph(box, transport[index].forward, transport[index].step, index == 1 && playing);
    cinema_qa_record(region, box, "director_transport", transport[index].tip, index);
    ui::Button *but = cinema_op_button(block, transport[index].op, box, transport[index].tip);
    const bool enabled = index == 1 ? (state.beats.size() >= 2 &&
                                       state.frame_end > state.frame_start)
                                    : !no_beats;
    director_overlay_disable_button(but, !enabled);
    tx += (TRANSPORT_SIZE + TRANSPORT_GAP) * u;
  }
}

/**
 * Right-edge mode tools. Returns the x the next group may claim.
 *
 * \a full adds capture and add-camera; the compact layout leaves those out
 * because its viewport rail already carries both as primary buttons.
 */
float draw_mode_tools(ui::Block *block,
                      const ARegion *region,
                      const DirectorViewState &state,
                      const float cy,
                      const bool full)
{
  const float u = cinema_unit();
  float right = float(region->winx) - (SIDE_PAD + 8.0f) * u;
  const struct {
    const char *op;
    int icon;
    const char *tip;
    bool enabled;
    bool wide_only;
  } tools[5] = {
      {"MIXAR_OT_director_toggle_timeline", ICON_X, "Collapse timeline", true, false},
      {"MIXAR_OT_director_toggle_immersive",
       ICON_FULLSCREEN_ENTER,
       "Toggle immersive Director view",
       true,
       false},
      {"MIXAR_OT_director_explore",
       ICON_VIEW_PAN,
       "Fly the scene freely without moving the shot camera",
       state.has_shot,
       false},
      {state.locked ? "MIXAR_OT_director_new_take" : "MIXAR_OT_director_capture_beat",
       state.locked ? ICON_DUPLICATE : ICON_KEYFRAME_HLT,
       state.locked ? "Start an editable child take" : "Capture the live camera pose (F)",
       state.has_camera,
       true},
      /* The camera entry point. The right column carries it as "+ Add Camera",
       * but that column only draws in the wide layout — without this the
       * compact one has no way to start directing at all. */
      {state.has_shot ? "MIXAR_OT_director_new_shot" : "MIXAR_OT_director_start",
       state.has_shot ? ICON_ADD : ICON_CAMERA_DATA,
       state.has_shot ? "Create a new shot camera from this view" :
                        "Direct the active scene camera from the viewport",
       true,
       true},
  };
  for (const auto &tool : tools) {
    if (tool.wide_only && !full) {
      continue;
    }
    const rctf box = {right - TOOL_SIZE * u,
                      right,
                      cy - TOOL_SIZE * u * 0.5f,
                      cy + TOOL_SIZE * u * 0.5f};
    tool_icon(block, tool.op, tool.icon, box, tool.tip, tool.enabled);
    right -= (TOOL_SIZE + TOOL_GAP) * u;
  }
  return right;
}

}  // namespace

float cinema_dock_control_height()
{
  return (ROW_H + ROW_TOP_GAP * 2.0f) * cinema_unit();
}

void cinema_draw_dock_panel(const ARegion *region)
{
  const float u = cinema_unit();
  const float top[4] = {0.110f, 0.110f, 0.110f, 1.0f};
  const float bottom[4] = {0.070f, 0.070f, 0.070f, 1.0f};
  const float line[4] = {0.180f, 0.180f, 0.180f, 1.0f};
  rctf panel = {float(region->winx) * 0.0f + 8.0f * u,
                float(region->winx) - 8.0f * u,
                6.0f * u,
                float(region->winy) - 6.0f * u};
  cinema_panel(panel, CINEMA_PANEL_RADIUS * u, top, bottom);
  cinema_outline(panel, CINEMA_PANEL_RADIUS * u, line, u);
}

void cinema_draw_dock_controls(ui::Block *block,
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
  draw_transport(block, region, state, cy, playing);

  /* -------- Right edge: mode tools, then the frame range -------- */
  float right = draw_mode_tools(block, region, state, cy, /*full=*/true);
  right -= 14.0f * u;

  /* The fields are created LAST and `ui_but_find_mouse_over_ex` walks a
   * block's buttons BACKWARDS, so an invisible ui::ButtonType::Num overlapping the
   * transport wins its clicks — "previous keyframe" started a drag-edit on
   * the scene Start frame. Drop the pair when the dock is too narrow to hold
   * them clear of the transport; the transport is the load-bearing group and
   * the frame range is reachable from Blender's own timeline. */
  const float fields_w = (FIELD_W * 2.0f + 8.0f) * u;
  const bool fields_fit = (right - fields_w) >=
                          (transport_right_edge(region) + FIELD_CLEARANCE * u);
  if (scene != nullptr && fields_fit) {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    const rctf end_rect = {right - FIELD_W * u, right, row_ymin, row_ymax};
    frame_field(block, &scene_ptr, "End", "frame_end", end_rect, "Last frame of the scene range");
    right -= (FIELD_W + 8.0f) * u;
    const rctf start_rect = {right - FIELD_W * u, right, row_ymin, row_ymax};
    frame_field(
        block, &scene_ptr, "Start", "frame_start", start_rect, "First frame of the scene range");
  }
}

void cinema_draw_dock_compact(ui::Block *block,
                              const ARegion *region,
                              const DirectorViewState &state,
                              const bool playing)
{
  /* The designed dock row belongs to the wide surface. Below the gate the old
   * viewport rail is what draws, and painting the design's Duration chips and
   * frame fields over it stacked two control sets on one screen. What survives
   * is only what has no other home while the timeline is expanded: the
   * transport, and collapse / immersive / explore. */
  cinema_qa_begin(region);
  const float u = cinema_unit();
  const float cy = float(region->winy) - (ROW_TOP_GAP + ROW_H * 0.5f) * u;
  draw_transport(block, region, state, cy, playing);
  draw_mode_tools(block, region, state, cy, /*full=*/false);
}

}  // namespace blender
