/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the right column — camera list, the aerial map, frame rate
 * and resolution segments, and the export action.
 *
 * Painting only; the controls are invisible uiButs over the painted pixels
 * driving Python-owned operators and native Director popups. The one
 * exception is the aerial map (`view3d_director_minimap_draw.cc`): it lays
 * no button, its LEFTMOUSE binding is a keymap item scoped by its poll.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "../interface/interface_mixar_profile_card.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

constexpr float VIEWPORT_TOP = 85.0f;
/** Right column's left edge in the design's window space. */
constexpr float COLUMN_X = 1486.0f;

/* The column stacks from CINEMA_COLUMN_TOP at CINEMA_CARD_GAP; the Export
 * button's design y is a header token (it feeds the fit gate), so the stack
 * is checked against it here rather than trusted. */
constexpr float PREVIEW_Y = CINEMA_COLUMN_TOP + CINEMA_CAMERAS_H + CINEMA_CARD_GAP;
constexpr float FPS_Y = PREVIEW_Y + CINEMA_PREVIEW_H + CINEMA_CARD_GAP;
constexpr float RES_Y = FPS_Y + CINEMA_SEGMENT_H + CINEMA_CARD_GAP;
static_assert(RES_Y + CINEMA_SEGMENT_H + CINEMA_CARD_GAP == CINEMA_EXPORT_Y,
              "CINEMA_EXPORT_Y must be the foot of the right column's stack");

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

/**
 * In-place editable text over a name the surface painted itself (T12).
 *
 * A Text button under Emboss::None is NOT interactive for plain hover or
 * clicks (`button_is_interactive_ex`): those fall through to the operator
 * button created before it on the same rect. A label edit (Ctrl held)
 * reaches it directly, and the operator button — tagged with
 * #UI_mixar_button_double_click_edits_label — hands it a double-click or
 * Ctrl+click the way a UI-list row does; the stock text editor then runs
 * (Enter commits, Esc cancels). Idle it paints nothing; tagged #Field so
 * the card painter lays the row chip under Blender's edit drawing.
 */
ui::Button *cinema_text_field(ui::Block *block,
                              PointerRNA *ptr,
                              const char *prop_name,
                              const rctf &rect,
                              const char *tooltip)
{
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = ui::uiDefButR(block,
                                  ui::ButtonType::Text,
                                  "",
                                  int(rect.xmin),
                                  int(rect.ymin),
                                  short(BLI_rctf_size_x(&rect)),
                                  short(BLI_rctf_size_y(&rect)),
                                  ptr,
                                  prop_name,
                                  0,
                                  0,
                                  0,
                                  tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  if (but != nullptr) {
    /* Contract with the tag: a Text button's `hardmax` IS its edit-buffer
     * size (`button_string_get_maxncpy`), so the tag must leave it alone for
     * `ButtonType::Text` and the painter must key #Field on the type, the way
     * Option is keyed on `ButtonType::Row`. A tag that wrote the kind there
     * would truncate every rename to five characters. */
    ui::UI_mixar_cinema_row_tag(but, ui::MixarCinemaRowKind::Field);
  }
  return but;
}

/** Three-way segmented row: graded track, chip behind the live choice. */
void segment_row(ui::Block *block,
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
  cinema_panel(track, CINEMA_ROW_RADIUS * u, track_top, track_bottom);

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
    ui::Button *but = cinema_op_button(block, operator_id, cell, tooltip);
    if (but != nullptr) {
      PointerRNA *ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(ptr, "data_path", property);
      RNA_int_set(ptr, "value", values[index]);
      director_overlay_disable_button(but, !enabled);
    }
  }
}

}  // namespace

void cinema_draw_right_panel(ui::Block *block,
                             const bContext *C,
                             const ARegion *region,
                             const DirectorViewState &state)
{
  const float u = cinema_unit();
  const float card_top[4] = CINEMA_COL_CARD_TOP;
  const float card_bottom[4] = CINEMA_COL_CARD_BOTTOM;
  const float label_col[4] = CINEMA_COL_CAPTION;
  const float value_col[4] = CINEMA_COL_VALUE;
  const float dim_col[4] = CINEMA_COL_DIM;
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));

  /* -------- Cameras -------- */
  const rctf cameras = design_rect_right(
      region, COLUMN_X, CINEMA_COLUMN_TOP, CINEMA_PANEL_W, CINEMA_CAMERAS_H);
  cinema_panel(cameras, CINEMA_PANEL_RADIUS * u, card_top, card_bottom);
  cinema_text_left("My Cameras",
                   cameras.xmin + 13.0f * u,
                   cameras.ymax - 22.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  /* Add Camera chip. */
  rctf add;
  add.xmax = cameras.xmax - 10.0f * u;
  add.xmin = add.xmax - 96.0f * u;
  add.ymax = cameras.ymax - 12.0f * u;
  add.ymin = add.ymax - 22.0f * u;
  const float add_top[4] = CINEMA_COL_ROW_TOP;
  const float add_bottom[4] = {0.192f, 0.192f, 0.192f, 1.0f}; /* #313131 */
  cinema_panel(add, BLI_rctf_size_y(&add) * 0.5f, add_top, add_bottom);
  cinema_text_center("+ Add Camera",
                     BLI_rctf_cent_x(&add),
                     BLI_rctf_cent_y(&add),
                     11.0f * u,
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

  const float row_h = cinema_list_row_h() * u;
  const float first_row_y = CINEMA_COLUMN_TOP + 66.0f;
  /* The card fits CINEMA_LIST_MAX_ROWS and nothing scrolls, so the window
   * follows the active shot: the live camera is always one of the rows drawn,
   * and the highlight can never go missing. */
  const int first_row = cinema_list_window_start(shot_count, active_index);
  const int visible_rows = std::min(shot_count, int(CINEMA_LIST_MAX_ROWS));
  for (int slot = 0; slot < visible_rows; slot++) {
    const int index = first_row + slot;
    PointerRNA shot_ptr;
    if (!RNA_property_collection_lookup_int(&state_ptr, shots_prop, index, &shot_ptr)) {
      continue;
    }
    /* "My Cameras": show the camera's own name, falling back to the shot's. */
    char name[128] = "";
    PointerRNA camera_ptr = PointerRNA_NULL;
    PropertyRNA *camera_prop = RNA_struct_find_property(&shot_ptr, "camera");
    if (camera_prop != nullptr) {
      camera_ptr = RNA_property_pointer_get(&shot_ptr, camera_prop);
      if (camera_ptr.data != nullptr) {
        PropertyRNA *name_prop = RNA_struct_find_property(&camera_ptr, "name");
        if (name_prop != nullptr) {
          RNA_property_string_get(&camera_ptr, name_prop, name);
        }
      }
    }
    /* The row renames the name it shows: the camera's, or the shot's. */
    PointerRNA *name_ptr = &camera_ptr;
    if (name[0] == '\0') {
      RNA_string_get(&shot_ptr, "name", name);
      name_ptr = &shot_ptr;
    }

    const bool active = index == active_index;
    rctf row;
    row.xmin = cameras.xmin + 11.0f * u;
    row.xmax = cameras.xmax - 10.0f * u;
    row.ymax = float(region->winy) -
               (first_row_y - VIEWPORT_TOP + CINEMA_LIST_PITCH * float(slot)) * u;
    row.ymin = row.ymax - row_h;
    if (active) {
      const float top[4] = CINEMA_COL_ROW_TOP;
      const float bottom[4] = CINEMA_COL_ROW_BOTTOM;
      cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);
    }
    cinema_text_left(name,
                     row.xmin + 12.0f * u,
                     BLI_rctf_cent_y(&row),
                     CINEMA_FONT_VALUE * u,
                     active ? value_col : dim_col);
    cinema_qa_record(region, row, "director_camera", name, index);
    ui::Button *but = cinema_op_button(
        block, "MIXAR_OT_director_set_active_shot", row, "Direct this camera");
    if (but != nullptr) {
      RNA_int_set(ui::button_operator_ptr_ensure(but), "index", index);
      ui::UI_mixar_button_double_click_edits_label(but);
    }
    /* The rename field is created AFTER the operator button on the same
     * rect: hit-testing walks a block backwards, so it is asked first — and
     * declines everything but a label edit, leaving the click to the
     * operator, which hands back double-click and Ctrl+click through its
     * tag. Renaming an ID through RNA keeps names unique on its own. */
    cinema_text_field(
        block, name_ptr, "name", row, "Rename this camera: double-click or Ctrl+click");
  }
  if (shot_count == 0) {
    cinema_text_center("No cameras yet",
                       BLI_rctf_cent_x(&cameras),
                       BLI_rctf_cent_y(&cameras) - 10.0f * u,
                       CINEMA_FONT_VALUE * u,
                       dim_col);
  }

  /* -------- Aerial view -------- */
  /* A live top-down map of the scene with the shot camera on it; a click or
   * drag on it places the camera at that world XY (`mixar.director_place_camera`).
   * Keyframe stills stay packed on the beats, only this card stopped showing
   * them; `cinema_image_preview` remains in `_paint.cc` for a future home. */
  const rctf preview = design_rect_right(
      region, COLUMN_X, PREVIEW_Y, CINEMA_PANEL_W, CINEMA_PREVIEW_H);
  cinema_draw_minimap(block, C, region, state, preview);

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
              FPS_Y,
              fps_labels,
              fps_active,
              "WM_OT_context_set_int",
              "scene.render.fps",
              fps_values,
              state.has_shot,
              "Set the scene frame rate",
              "director_fps");

  /* -------- Resolution -------- */
  /* MIXAR_OT_director_set_resolution scales the SHORTER side to the tier, so
   * a 9:16 scene at 1080p is 1080x1920 — reading `ysch` matched nothing there
   * and no chip lit. The tier IS the short side. */
  const int short_side = scene ? std::min(scene->r.xsch, scene->r.ysch) : 1080;
  const char *const res_labels[3] = {"720p", "1080p", "2K"};
  const int res_values[3] = {720, 1080, 1440};
  int res_active = -1;
  for (int index = 0; index < 3; index++) {
    if (short_side == res_values[index]) {
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
        region, COLUMN_X, RES_Y, CINEMA_PANEL_W, CINEMA_SEGMENT_H);
    cinema_panel(track, CINEMA_ROW_RADIUS * u, track_top, track_bottom);
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
      ui::Button *but = cinema_op_button(
          block, "MIXAR_OT_director_set_resolution", cell, "Set the output resolution");
      if (but != nullptr) {
        RNA_enum_set_identifier(
            const_cast<bContext *>(C), ui::button_operator_ptr_ensure(but), "preset", identifiers[index]);
        director_overlay_disable_button(but, !state.has_shot);
      }
    }
  }

  /* -------- Export -------- */
  const rctf export_rect = design_rect_right(
      region, COLUMN_X, CINEMA_EXPORT_Y, CINEMA_PANEL_W, CINEMA_EXPORT_H);
  const float export_col[4] = CINEMA_COL_EXPORT;
  cinema_fill(export_rect, CINEMA_ROW_RADIUS * u, export_col);
  const bool can_export = !state.beats.is_empty();
  const float export_text[4] = {1.0f, 1.0f, 1.0f, can_export ? 1.0f : 0.45f};
  cinema_text_center("Export to moodboard",
                     BLI_rctf_cent_x(&export_rect),
                     BLI_rctf_cent_y(&export_rect),
                     14.0f * u,
                     export_text);
  ui::Button *export_but = cinema_popup_button(block,
                                          view3d_director_render_popup_create,
                                          export_rect,
                                          "Export keyframes and rendered guides to the Moodboard",
                                          CinemaPopupSlot::Export);
  director_overlay_disable_button(export_but, !can_export);
  cinema_qa_record(region, export_rect, "director_export", "export", -1);
}

}  // namespace blender
