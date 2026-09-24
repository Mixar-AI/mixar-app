/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the timeline dock's control row.
 *
 * Two rows. The first reads left to right as one sentence about the scale
 * under it — "Ruler | Frames · Duration | Start | End" — because Start and
 * End are the range that scale measures, and they now read in whatever unit
 * the switch beside them selects. The transport stays centred on it, and
 * interpolation takes the far right: it is how the camera eases BETWEEN
 * KEYFRAMES, a property of the shot rather than of the ruler, and the right
 * margin is where a surface puts the thing that belongs to no group.
 *
 * The second row is the ACTIONS row (`_dock_actions.cc`), centred under the
 * transport: Auto Key and Add Keyframe, next to the play button the eye is
 * already on rather than in the corner furthest from the work.
 *
 * Painting only; every control is a real ui::Button over the painted pixels.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

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
#include "view3d_director_timeline.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Design px. */
constexpr float ROW_H = 30.0f;
constexpr float ROW_TOP_GAP = 12.0f;
/** The actions row under it, and the clear space between the two. SUB_ROW_H
 * is that row's height and must match `ACTION_H` in `_dock_actions.cc`, which
 * is the pill drawn on it; `tests/director/test_dock_actions_row.py` pins
 * the pair so the row can never be shorter than what it holds. */
constexpr float SUB_ROW_H = 30.0f;
constexpr float SUB_ROW_GAP = 6.0f;
constexpr float SIDE_PAD = 26.0f;
/** The interpolation dropdown beside them; fits "Sinusoidal" plus a chevron. */
constexpr float INTERP_W = 118.0f;
constexpr float CHIP_H = 26.0f;
/* A frame field: the whole pill, its label inset, and the gap to the value.
 * FIELD_W has to hold "Start" plus four digits AFTER a Num button's own arrow
 * padding eats roughly 24 design px of the text area. */
constexpr float FIELD_W = 132.0f;
/** What a field shrinks to before there is nowhere left to put it. */
constexpr float FIELD_MIN_W = 88.0f;
constexpr float LABEL_PAD = 12.0f;
constexpr float LABEL_GAP = 8.0f;
/** Clear space the other groups must keep from the centred transport. */
constexpr float FIELD_CLEARANCE = 16.0f;
/** Gap between Start and End, and from the pair to whatever follows. */
constexpr float FIELD_GAP = 8.0f;

/**
 * Small labelled numeric field ("Start 1").
 *
 * \a ptr is whichever datablock owns the property for the unit in force —
 * the SCENE for `frame_start` / `frame_end`, the Director state for the
 * seconds mirrors — so the cell itself never has to know which is on.
 */
void frame_field(ui::Block *block,
                 PointerRNA *ptr,
                 const char *label,
                 const char *property,
                 const rctf &rect,
                 const char *tooltip)
{
  const float u = cinema_unit();
  const float bg[4] = {0.149f, 0.149f, 0.149f, 1.0f};
  /* A CAPTION, at the caption size: it titles the value beside it, the same
   * job "Aspect Ratio" does in the left column. It used to be a 13 px DIM,
   * which is the surface's "not the live one" grey. */
  MIXAR_THEME_LOAD(label_col, CinemaRowCaption);
  /* The same radius as every other rounded control, capped to a pill. */
  cinema_fill(rect, std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&rect) * 0.5f), bg);
  const float font = CINEMA_FONT_LABEL * u;
  cinema_text_left(label, rect.xmin + LABEL_PAD * u, BLI_rctf_cent_y(&rect), font, label_col);

  /* The value IS the button: a Num button under Emboss::None paints only its
   * value string, so it reads as the design's plain number and still drags
   * and text-edits like any frame field.
   *
   * It gets everything the label does not need, measured — a fixed 48% split
   * of a 100-design-px field left about 14px of usable text after a Num
   * button's own arrow padding, which is where "only 2 digits max is visible"
   * came from. A scene ending on frame 1200 must read as 1200.
   *
   * It also keeps the pill's own inset on the right. A Num button CENTRES
   * its value in whatever box it is given, so a box running to the pill's
   * edge floated the number in the middle of the field with a gap after the
   * label — and pushed a four-digit one flush against the edge. */
  rctf value = rect;
  value.xmin = rect.xmin + LABEL_PAD * u + cinema_text_width(label, font) + LABEL_GAP * u;
  value.xmax = rect.xmax - LABEL_PAD * u;
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  uiDefButR(block,
            ui::ButtonType::Num,
            "",
            int(value.xmin),
            int(value.ymin),
            short(BLI_rctf_size_x(&value)),
            short(BLI_rctf_size_y(&value)),
            ptr,
            property,
            0,
            0,
            0,
            tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
}

/** The enum NAME and IDENTIFIER of \a ptr's `interpolation`, if it has one. */
bool interpolation_labels(const bContext *C,
                          PointerRNA *ptr,
                          const char **r_name,
                          const char **r_identifier)
{
  PropertyRNA *prop = ptr->data ? RNA_struct_find_property(ptr, "interpolation") : nullptr;
  if (prop == nullptr) {
    return false;
  }
  const int value = RNA_property_enum_get(ptr, prop);
  const char *found = nullptr;
  if (RNA_property_enum_name(const_cast<bContext *>(C), ptr, prop, value, &found) &&
      found != nullptr)
  {
    *r_name = found;
  }
  if (RNA_property_enum_identifier(const_cast<bContext *>(C), ptr, prop, value, &found) &&
      found != nullptr)
  {
    *r_identifier = found;
  }
  return true;
}

/**
 * Interpolation: how the camera eases BETWEEN KEYFRAMES.
 *
 * It used to live off the stage's right edge in the top strip, as far from
 * the keyframes it describes as the surface allows.
 *
 * It follows the SELECTION. Select keyframes and the chip reads — and its
 * popup writes — their own `interpolation`, which is what makes one span ease
 * differently from the next; a keyframe's interpolation governs the segment
 * from it to the following one. With nothing selected it is the shot's
 * default, which is what every beat rests on. Both are RNA enums and the
 * popup lists whichever property it is about, so a label here can never
 * disagree with what the popup offers.
 */
void interpolation_chip(ui::Block *block,
                        const bContext *C,
                        const ARegion *region,
                        const rctf &rect,
                        const bool enabled)
{
  const float u = cinema_unit();
  MIXAR_THEME_LOAD(top, CinemaRowTop);
  MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
  MIXAR_THEME_LOAD(value_col, CinemaRowTextOn);
  const float chevron[4] = {0.851f, 0.851f, 0.851f, 1.0f};
  cinema_panel(rect, std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&rect) * 0.5f), top, bottom);

  const char *name = "Bezier";
  const char *identifier = "BEZIER";
  PointerRNA shot_ptr = {};
  view3d_director_active_shot_pointer(CTX_data_scene(const_cast<bContext *>(C)), &shot_ptr);

  blender::Vector<int> selected;
  const bool has_selection = view3d_director_timeline_selection(C, &selected);
  if (has_selection && shot_ptr.data) {
    /* One answer only when the selected keyframes AGREE. "Mixed" is the
     * honest label for a selection that spans two easings, and picking any
     * row still writes it to all of them. */
    PropertyRNA *beats = RNA_struct_find_property(&shot_ptr, "beats");
    const int count = beats ? RNA_property_collection_length(&shot_ptr, beats) : 0;
    bool first = true;
    for (const int index : selected) {
      if (index < 0 || index >= count) {
        continue;
      }
      PointerRNA beat_ptr;
      if (!RNA_property_collection_lookup_int(&shot_ptr, beats, index, &beat_ptr)) {
        continue;
      }
      const char *beat_name = "Shot Default";
      const char *beat_id = "SHOT";
      interpolation_labels(C, &beat_ptr, &beat_name, &beat_id);
      if (first) {
        name = beat_name;
        identifier = beat_id;
        first = false;
      }
      else if (!STREQ(identifier, beat_id)) {
        name = "Mixed";
        identifier = "MIXED";
        break;
      }
    }
  }
  else {
    interpolation_labels(C, &shot_ptr, &name, &identifier);
  }
  cinema_text_left(
      name, rect.xmin + 12.0f * u, BLI_rctf_cent_y(&rect), CINEMA_FONT_VALUE * u, value_col);
  cinema_chevron(rect.xmax - 16.0f * u, BLI_rctf_cent_y(&rect), 9.0f * u, chevron);

  cinema_qa_record(region, rect, "director_interpolation", identifier, -1);
  ui::Button *but = cinema_popup_button(
      block,
      view3d_director_interpolation_popup_create,
      rect,
      has_selection ? "Interpolation: how the camera eases out of the selected keyframes" :
                      "Interpolation: how the camera eases between this shot's keyframes",
      CinemaPopupSlot::Strip);
  director_overlay_disable_button(but, !enabled);
}


/**
 * Start and End, immediately right of the ruler's unit switch — and READ IN
 * THAT UNIT.
 *
 * They used to sit at the far end of the row, past the transport, where
 * nothing said they were the range the ruler under them is scaling. Beside
 * the switch the row reads as one sentence: this is the scale, this is what
 * it spans.
 *
 * In DURATION the pair shows seconds instead of frame numbers, through the
 * Director state's `range_*_seconds` mirrors of the scene's own range. The
 * seconds are absolute — frame divided by the effective rate, which is what
 * Blender's own "Show Seconds" means by a time — so both ends stay editable;
 * the ruler's labels measure ELAPSED time from the scene's start, so on a
 * scene starting at frame 1 the two differ by that one frame.
 *
 * The pair SHRINKS before it disappears: dropping it whole meant a slightly
 * narrower viewport made Start and End vanish outright.
 *
 * Returns the x the next group may claim.
 */
float draw_frame_range(ui::Block *block,
                       const bContext *C,
                       const ARegion *region,
                       const DirectorViewState &state,
                       const float start_x,
                       const float row_ymin,
                       const float row_ymax)
{
  const float u = cinema_unit();
  /* NOT `const Scene *`: `view3d_director_state_pointer` takes a mutable
   * scene, the way every Director state reader does. */
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));
  if (scene == nullptr) {
    return start_x;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PointerRNA state_ptr = {};
  const bool seconds = !state.ruler_frames && view3d_director_state_pointer(scene, &state_ptr);
  PointerRNA *ptr = seconds ? &state_ptr : &scene_ptr;

  /* The transport is the load-bearing group; everything else keeps clear of
   * it. */
  const float transport_left = float(region->winx) - cinema_transport_right_edge(region);
  const float available = transport_left - FIELD_CLEARANCE * u - start_x;
  const float field_w = std::min(FIELD_W * u, (available - FIELD_GAP * u) * 0.5f);
  if (field_w < FIELD_MIN_W * u) {
    return start_x;
  }

  float x = start_x;
  const rctf start_rect = {x, x + field_w, row_ymin, row_ymax};
  frame_field(block,
              ptr,
              "Start",
              seconds ? "range_start_seconds" : "frame_start",
              start_rect,
              seconds ? "First frame of the scene range, in seconds" :
                        "First frame of the scene range");
  x += field_w + FIELD_GAP * u;
  const rctf end_rect = {x, x + field_w, row_ymin, row_ymax};
  frame_field(block,
              ptr,
              "End",
              seconds ? "range_end_seconds" : "frame_end",
              end_rect,
              seconds ? "Last frame of the scene range, in seconds" :
                        "Last frame of the scene range");
  return x + field_w + FIELD_GAP * u;
}

}  // namespace

float cinema_dock_control_height(const bool full)
{
  const float u = cinema_unit();
  const float row = (ROW_H + ROW_TOP_GAP * 2.0f) * u;
  /* Only the wide surface draws the actions row; the compact dock's rail
   * already carries the same two controls, so it keeps its old budget and
   * gives the height back to the keyframe strip. */
  return full ? row + (SUB_ROW_GAP + SUB_ROW_H) * u : row;
}

void cinema_draw_dock_panel(const ARegion *region)
{
  const float u = cinema_unit();
  const float line[4] = {0.180f, 0.180f, 0.180f, 0.22f};
  rctf panel = {float(region->winx) * 0.0f + 8.0f * u,
                float(region->winx) - 8.0f * u,
                6.0f * u,
                float(region->winy) - 6.0f * u};
  cinema_glass_panel(panel, CINEMA_PANEL_RADIUS * u);
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

  const float row_ymax = float(region->winy) - ROW_TOP_GAP * u;
  const float row_ymin = row_ymax - ROW_H * u;
  const float cy = (row_ymin + row_ymax) * 0.5f;

  /* -------- Ruler, then the range that scale measures -------- */
  const float x = cinema_draw_ruler_group(block, C, region, SIDE_PAD * u + 8.0f * u, cy);
  /* The range is the last group on the left, so its own "next x" is unused;
   * it is returned all the same, because that hand-off is how every group in
   * this row is laid out. */
  draw_frame_range(block, C, region, state, x, row_ymin, row_ymax);

  /* -------- Interpolation, at the dock's right edge --------
   *
   * It describes the SHOT, not the ruler, so it belongs to no group on the
   * left; the right margin is where a surface puts that. Dropped rather than
   * drawn into the transport when the dock is narrow — the transport is the
   * load-bearing group and everything else keeps clear of it. */
  const float right_edge = float(region->winx) - (SIDE_PAD + 8.0f) * u;
  const rctf interp = {
      right_edge - INTERP_W * u, right_edge, cy - CHIP_H * u * 0.5f, cy + CHIP_H * u * 0.5f};
  if (interp.xmin > cinema_transport_right_edge(region) + FIELD_CLEARANCE * u) {
    interpolation_chip(block, C, region, interp, state.has_shot && !state.locked);
  }

  /* -------- Transport (centred on the dock) --------
   *
   * Created AFTER the groups that can share a band with it.
   * `ui_but_find_mouse_over_ex` walks a block's buttons BACKWARDS, so the
   * later button wins an overlap: with the frame fields last, an invisible
   * Num over the transport turned "previous keyframe" into a drag-edit of
   * the scene's start frame. */
  cinema_draw_transport(block, region, state, cy, playing);

  /* -------- Actions, centred on their own row under it -------- */
  cinema_draw_dock_actions(
      block, C, region, state, row_ymin - (SUB_ROW_GAP + SUB_ROW_H * 0.5f) * u);
}

void cinema_draw_dock_compact(ui::Block *block,
                              const ARegion *region,
                              const DirectorViewState &state,
                              const bool playing)
{
  /* The designed dock row belongs to the wide surface. Below the gate the old
   * viewport rail is what draws, and painting the design's Duration chips and
   * frame fields over it stacked two control sets on one screen. What survives
   * is the transport alone — the rail carries everything else. */
  cinema_qa_begin(region);
  const float u = cinema_unit();
  const float cy = float(region->winy) - (ROW_TOP_GAP + ROW_H * 0.5f) * u;
  cinema_draw_transport(block, region, state, cy, playing);
}

}  // namespace blender
