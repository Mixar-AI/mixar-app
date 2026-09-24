/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the timeline dock's Ruler group — its title and the unit
 * switch beside it.
 *
 * Split from `view3d_director_cinema_dock.cc`, which was at the module size
 * limit, along the seam the dock's own layout already uses: each group takes
 * the x it may start at and returns the x the next one may claim.
 */

#include <algorithm>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Design px; the dock's own tokens for the row these cells sit on. */
constexpr float CHIP_W = 72.0f;
constexpr float CHIP_H = 26.0f;
/** Inset of a segmented cell inside its track. */
constexpr float SEGMENT_PAD = 3.0f;
/** Gap to whatever group comes next. */
constexpr float GROUP_GAP = 20.0f;

/**
 * The ruler's unit switch: ONE pill holding both options, the live one
 * filled.
 *
 * They were two separate pills, which reads as two buttons that happen to sit
 * next to each other — nothing about it said that picking one un-picks the
 * other, or which of them was a state rather than an action. A segmented
 * control says "one of these", which is what this is. The cells keep their
 * own buttons and QA records, so a click and a scripted pick still land on
 * the cell the director sees.
 */
void unit_switch(ui::Block *block,
                 const ARegion *region,
                 const rctf &track,
                 const char *unit_id)
{
  const float u = cinema_unit();
  const float radius = std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&track) * 0.5f);
  const float track_bg[4] = {0.176f, 0.176f, 0.176f, 1.0f};
  cinema_fill(track, radius, track_bg);

  const struct {
    const char *label;
    const char *value;
  } cells[2] = {{"Frames", "FRAMES"}, {"Duration", "DURATION"}};

  const float pad = SEGMENT_PAD * u;
  const float cell_w = (BLI_rctf_size_x(&track) - pad * 2.0f) * 0.5f;
  MIXAR_THEME_LOAD(on_bg, CinemaChip);
  MIXAR_THEME_LOAD(on, CinemaRowTextOn);
  MIXAR_THEME_LOAD(off, CinemaRowTextDisabled);
  for (int index = 0; index < 2; index++) {
    const float x0 = track.xmin + pad + cell_w * float(index);
    const rctf cell = {x0, x0 + cell_w, track.ymin + pad, track.ymax - pad};
    const bool active = STREQ(unit_id, cells[index].value);
    if (active) {
      cinema_fill(cell, std::min(radius, BLI_rctf_size_y(&cell) * 0.5f), on_bg);
    }
    cinema_text_center(cells[index].label,
                       BLI_rctf_cent_x(&cell),
                       BLI_rctf_cent_y(&cell),
                       CINEMA_FONT_LABEL * u,
                       active ? on : off);
    cinema_qa_record(region, cell, "director_ruler_unit", cells[index].value, -1);
    ui::Button *but = cinema_op_button(
        block, "WM_OT_context_set_enum", cell, "Label the ruler in frames or elapsed time");
    if (but != nullptr) {
      PointerRNA *ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(ptr, "data_path", "scene.mixar_director.ruler_unit");
      RNA_string_set(ptr, "value", cells[index].value);
    }
  }
}

}  // namespace

float cinema_draw_ruler_group(ui::Block *block,
                              const bContext *C,
                              const ARegion *region,
                              const float start_x,
                              const float cy)
{
  const float u = cinema_unit();
  /* NOT `const Scene *`: `view3d_director_state_pointer` takes a mutable
   * scene, the way every Director state reader does. */
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));
  /* The same near-white the dock's other group titles use. */
  const float title[4] = {0.925f, 0.925f, 0.925f, 1.0f};
  float x = start_x;
  /* Titled "Ruler", not "Duration": Duration is now one of the two cells it
   * introduces, and a group labelled with the name of one of its own options
   * reads as a statement rather than a choice. */
  cinema_text_left("Ruler", x, cy, CINEMA_FONT_TITLE * u, title);
  x += cinema_text_width("Ruler", CINEMA_FONT_TITLE * u) + 16.0f * u;

  char unit_id[16] = "DURATION";
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
  /* Frames or elapsed time — the choice a director actually has. The cells
   * used to be Min and Sec, two spellings of elapsed time, and neither of
   * them offered frame numbers at all. */
  const float unit_track_w = (CHIP_W * 2.0f + SEGMENT_PAD * 2.0f) * u;
  const rctf unit_track = {
      x, x + unit_track_w, cy - CHIP_H * u * 0.5f, cy + CHIP_H * u * 0.5f};
  unit_switch(block, region, unit_track, unit_id);
  return x + unit_track_w + GROUP_GAP * u;
}

}  // namespace blender
