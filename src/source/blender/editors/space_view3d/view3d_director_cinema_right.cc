/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the right column — camera list, shot preview, frame rate and
 * resolution segments, and the export action.
 *
 * Painting only; the controls are invisible uiButs over the painted pixels
 * driving Python-owned operators and native Director popups.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_image_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

namespace {

constexpr float VIEWPORT_TOP = 85.0f;
/** Right column's left edge in the design's window space. */
constexpr float COLUMN_X = 1486.0f;

/** Rect from design window coordinates, anchored to the region's right edge. */
rctf design_rect_right(const ARegion *region,
                       const float x,
                       const float y,
                       const float w,
                       const float h)
{
  const float u = cinema_unit();
  rctf rect;
  /* Anchor on the right so the column hugs the viewport edge at any width. */
  rect.xmax = float(region->winx) - cinema_margin(region) * u - (COLUMN_X + CINEMA_PANEL_W - (x + w)) * u;
  rect.xmin = rect.xmax - w * u;
  rect.ymax = float(region->winy) - (y - VIEWPORT_TOP) * u;
  rect.ymin = rect.ymax - h * u;
  return rect;
}

/** Three-way segmented row: graded track, chip behind the live choice. */
void segment_row(uiBlock *block,
                 const ARegion *region,
                 const float design_y,
                 const char *const labels[3],
                 const int active_index,
                 const char *operator_id,
                 const char *property,
                 const int values[3],
                 const bool enabled,
                 const char *tooltip,
                 const char *surface)
{
  const float u = cinema_unit();
  const float track_top[4] = CINEMA_COL_CARD_TOP;
  const float track_bottom[4] = CINEMA_COL_CARD_BOTTOM;
  const float chip[4] = CINEMA_COL_CHIP;
  const float on[4] = CINEMA_COL_VALUE;
  const float off[4] = CINEMA_COL_DIMMER;

  const rctf track = design_rect_right(
      region, COLUMN_X, design_y, CINEMA_PANEL_W, CINEMA_SEGMENT_H);
  cinema_panel(track, CINEMA_PANEL_RADIUS * u, track_top, track_bottom);

  const float inset = 2.0f * u;
  const float cell_w = (BLI_rctf_size_x(&track) - inset * 2.0f) / 3.0f;
  for (int index = 0; index < 3; index++) {
    rctf cell;
    cell.xmin = track.xmin + inset + cell_w * float(index);
    cell.xmax = cell.xmin + cell_w;
    cell.ymin = track.ymin + inset;
    cell.ymax = track.ymax - inset;
    if (index == active_index) {
      cinema_fill(cell, BLI_rctf_size_y(&cell) * 0.5f, chip);
    }
    cinema_text_center(labels[index],
                       BLI_rctf_cent_x(&cell),
                       BLI_rctf_cent_y(&cell),
                       CINEMA_FONT_VALUE * u,
                       index == active_index ? on : off);

    cinema_qa_record(region, cell, surface, labels[index], index);
    uiBut *but = cinema_op_button(block, operator_id, cell, tooltip);
    if (but != nullptr) {
      PointerRNA *ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(ptr, "data_path", property);
      RNA_int_set(ptr, "value", values[index]);
      director_overlay_disable_button(but, !enabled);
    }
  }
}

}  // namespace

void cinema_draw_right_panel(uiBlock *block,
                             const bContext *C,
                             const ARegion *region,
                             const DirectorViewState &state)
{
  const float u = cinema_unit();
  const float card_top[4] = CINEMA_COL_CARD_TOP;
  const float card_bottom[4] = CINEMA_COL_CARD_BOTTOM;
  const float label_col[4] = CINEMA_COL_LABEL;
  const float value_col[4] = CINEMA_COL_VALUE;
  const float dim_col[4] = CINEMA_COL_DIM;
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));

  /* -------- Cameras -------- */
  const rctf cameras = design_rect_right(region, COLUMN_X, 206.0f, CINEMA_PANEL_W, 226.0f);
  cinema_panel(cameras, CINEMA_PANEL_RADIUS * u, card_top, card_bottom);
  cinema_text_left("My Cameras",
                   cameras.xmin + 13.0f * u,
                   cameras.ymax - 25.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  /* Add Camera chip. */
  rctf add;
  add.xmax = cameras.xmax - 10.0f * u;
  add.xmin = add.xmax - 102.0f * u;
  add.ymax = cameras.ymax - 14.0f * u;
  add.ymin = add.ymax - 23.0f * u;
  const float add_top[4] = CINEMA_COL_ROW_TOP;
  const float add_bottom[4] = {0.192f, 0.192f, 0.192f, 1.0f}; /* #313131 */
  cinema_panel(add, BLI_rctf_size_y(&add) * 0.5f, add_top, add_bottom);
  cinema_text_center("+ Add Camera",
                     BLI_rctf_cent_x(&add),
                     BLI_rctf_cent_y(&add),
                     11.5f * u,
                     value_col);
  /* With nothing directed yet this is the session's entry point, and it must
   * stay `director_start`: that one adopts a camera the scene already has,
   * where `new_shot` would always mint another one beside it. */
  cinema_qa_record(region, add, "director_add_camera", "add", -1);
  cinema_op_button(block,
                   state.has_shot ? "MIXAR_OT_director_new_shot" : "MIXAR_OT_director_start",
                   add,
                   state.has_shot ? "Create a new shot camera from this view" :
                                    "Direct the active scene camera from the viewport");

  /* Camera rows — one per shot, named after the camera it directs. */
  PointerRNA state_ptr;
  int shot_count = 0;
  int active_index = 0;
  PropertyRNA *shots_prop = nullptr;
  const bool have_state = view3d_director_state_pointer(scene, &state_ptr);
  if (have_state) {
    shots_prop = RNA_struct_find_property(&state_ptr, "shots");
    shot_count = shots_prop ? RNA_property_collection_length(&state_ptr, shots_prop) : 0;
    active_index = RNA_int_get(&state_ptr, "active_shot_index");
  }

  const float row_h = CINEMA_ROW_H * u;
  const float first_row_y = 276.0f;
  const int max_rows = 4; /* The card's height; the rest scrolls out of view. */
  for (int index = 0; index < std::min(shot_count, max_rows); index++) {
    PointerRNA shot_ptr;
    if (!RNA_property_collection_lookup_int(&state_ptr, shots_prop, index, &shot_ptr)) {
      continue;
    }
    /* "My Cameras": show the camera's own name, falling back to the shot's. */
    char name[128] = "";
    PropertyRNA *camera_prop = RNA_struct_find_property(&shot_ptr, "camera");
    if (camera_prop != nullptr) {
      PointerRNA camera_ptr = RNA_property_pointer_get(&shot_ptr, camera_prop);
      if (camera_ptr.data != nullptr) {
        PropertyRNA *name_prop = RNA_struct_find_property(&camera_ptr, "name");
        if (name_prop != nullptr) {
          RNA_property_string_get(&camera_ptr, name_prop, name);
        }
      }
    }
    if (name[0] == '\0') {
      RNA_string_get(&shot_ptr, "name", name);
    }

    const bool active = index == active_index;
    rctf row;
    row.xmin = cameras.xmin + 11.0f * u;
    row.xmax = cameras.xmax - 10.0f * u;
    row.ymax = float(region->winy) -
               (first_row_y - VIEWPORT_TOP + CINEMA_LIST_PITCH * float(index)) * u;
    row.ymin = row.ymax - row_h;
    if (active) {
      const float top[4] = CINEMA_COL_ROW_TOP;
      const float bottom[4] = CINEMA_COL_ROW_BOTTOM;
      cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);
    }
    cinema_text_left(name,
                     row.xmin + 14.0f * u,
                     BLI_rctf_cent_y(&row),
                     CINEMA_FONT_VALUE * u,
                     active ? value_col : dim_col);
    cinema_qa_record(region, row, "director_camera", name, index);
    uiBut *but = cinema_op_button(
        block, "MIXAR_OT_director_set_active_shot", row, "Direct this camera");
    if (but != nullptr) {
      RNA_int_set(UI_but_operator_ptr_ensure(but), "index", index);
    }
  }
  if (shot_count == 0) {
    cinema_text_center("No cameras yet",
                       BLI_rctf_cent_x(&cameras),
                       BLI_rctf_cent_y(&cameras) - 10.0f * u,
                       CINEMA_FONT_VALUE * u,
                       dim_col);
  }

  /* -------- Shot preview -------- */
  const rctf preview = design_rect_right(
      region, COLUMN_X, 447.0f, CINEMA_PANEL_W, CINEMA_PREVIEW_H);
  cinema_panel(preview, CINEMA_PANEL_RADIUS * u, card_top, card_bottom);
  /* The newest captured keyframe still IS the camera preview — Director
   * already packs one per beat, so no new render path is needed. */
  Image *preview_image = nullptr;
  PointerRNA shot_ptr;
  if (view3d_director_active_shot_pointer(scene, &shot_ptr)) {
    PropertyRNA *beats_prop = RNA_struct_find_property(&shot_ptr, "beats");
    const int beat_count = beats_prop ?
                               RNA_property_collection_length(&shot_ptr, beats_prop) :
                               0;
    if (beat_count > 0) {
      PointerRNA beat_ptr;
      if (RNA_property_collection_lookup_int(&shot_ptr, beats_prop, beat_count - 1, &beat_ptr)) {
        PropertyRNA *image_prop = RNA_struct_find_property(&beat_ptr, "image");
        if (image_prop != nullptr) {
          PointerRNA image_ptr = RNA_property_pointer_get(&beat_ptr, image_prop);
          preview_image = static_cast<Image *>(image_ptr.data);
        }
      }
    }
  }
  if (preview_image != nullptr) {
    rctf inner = preview;
    BLI_rctf_pad(&inner, -2.0f * u, -2.0f * u);
    cinema_image_preview(preview_image, inner, 18.0f * u);
  }
  else {
    cinema_text_center("Capture a keyframe",
                       BLI_rctf_cent_x(&preview),
                       BLI_rctf_cent_y(&preview),
                       CINEMA_FONT_VALUE * u,
                       dim_col);
  }

  /* -------- Frame rate -------- */
  const int fps = scene ? scene->r.frs_sec : 24;
  const char *const fps_labels[3] = {"24fps", "30fps", "60fps"};
  const int fps_values[3] = {24, 30, 60};
  int fps_active = -1;
  for (int index = 0; index < 3; index++) {
    if (fps == fps_values[index]) {
      fps_active = index;
    }
  }
  segment_row(block,
              region,
              634.0f,
              fps_labels,
              fps_active,
              "WM_OT_context_set_int",
              "scene.render.fps",
              fps_values,
              state.has_shot,
              "Set the scene frame rate",
              "director_fps");

  /* -------- Resolution -------- */
  const int height = scene ? scene->r.ysch : 1080;
  const char *const res_labels[3] = {"720p", "1080p", "2K"};
  const int res_values[3] = {720, 1080, 1440};
  int res_active = -1;
  for (int index = 0; index < 3; index++) {
    if (height == res_values[index]) {
      res_active = index;
    }
  }
  /* Resolution has to move BOTH axes to keep the chosen aspect, so it goes
   * through a Director operator rather than a context setter. */
  {
    const float track_top[4] = CINEMA_COL_CARD_TOP;
    const float track_bottom[4] = CINEMA_COL_CARD_BOTTOM;
    const float chip[4] = CINEMA_COL_CHIP;
    const float on[4] = CINEMA_COL_VALUE;
    const float off[4] = CINEMA_COL_DIMMER;
    const rctf track = design_rect_right(
        region, COLUMN_X, 695.0f, CINEMA_PANEL_W, CINEMA_SEGMENT_H);
    cinema_panel(track, CINEMA_PANEL_RADIUS * u, track_top, track_bottom);
    const float inset = 2.0f * u;
    const float cell_w = (BLI_rctf_size_x(&track) - inset * 2.0f) / 3.0f;
    const char *const identifiers[3] = {"HD720", "HD1080", "K2"};
    for (int index = 0; index < 3; index++) {
      rctf cell;
      cell.xmin = track.xmin + inset + cell_w * float(index);
      cell.xmax = cell.xmin + cell_w;
      cell.ymin = track.ymin + inset;
      cell.ymax = track.ymax - inset;
      if (index == res_active) {
        cinema_fill(cell, BLI_rctf_size_y(&cell) * 0.5f, chip);
      }
      cinema_text_center(res_labels[index],
                         BLI_rctf_cent_x(&cell),
                         BLI_rctf_cent_y(&cell),
                         CINEMA_FONT_VALUE * u,
                         index == res_active ? on : off);
      cinema_qa_record(region, cell, "director_resolution", identifiers[index], index);
      uiBut *but = cinema_op_button(
          block, "MIXAR_OT_director_set_resolution", cell, "Set the output resolution");
      if (but != nullptr) {
        RNA_enum_set_identifier(
            const_cast<bContext *>(C), UI_but_operator_ptr_ensure(but), "preset", identifiers[index]);
        director_overlay_disable_button(but, !state.has_shot);
      }
    }
  }

  /* -------- Export -------- */
  const rctf export_rect = design_rect_right(
      region, COLUMN_X, 754.0f, CINEMA_PANEL_W, CINEMA_EXPORT_H);
  const float export_col[4] = CINEMA_COL_EXPORT;
  cinema_fill(export_rect, CINEMA_PANEL_RADIUS * u, export_col);
  const bool can_export = !state.beats.is_empty();
  const float export_text[4] = {1.0f, 1.0f, 1.0f, can_export ? 1.0f : 0.45f};
  cinema_text_center("Export to moodboard",
                     BLI_rctf_cent_x(&export_rect),
                     BLI_rctf_cent_y(&export_rect),
                     16.0f * u,
                     export_text);
  uiBut *export_but = cinema_popup_button(block,
                                          view3d_director_render_popup_create,
                                          export_rect,
                                          "Export keyframes and rendered guides to the Moodboard");
  director_overlay_disable_button(export_but, !can_export);
  cinema_qa_record(region, export_rect, "director_export", "export", -1);
}
