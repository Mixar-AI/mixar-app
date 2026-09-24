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

#include "BLI_function_ref.hh"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_minimap.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

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

/**
 * A card of the right column, at design \a y and \a h.
 *
 * Anchored on the region's RIGHT edge so the column hugs the viewport at any
 * width. Every card in this column is the column's full width, which is why
 * this takes no x: the version that did always resolved to the same offset.
 */
rctf column_card(const ARegion *region, const float y, const float h)
{
  const float u = cinema_unit();
  rctf rect;
  rect.xmax = float(region->winx) - cinema_margin(region) * u;
  rect.xmin = rect.xmax - CINEMA_PANEL_W * u;
  rect.ymax = float(region->winy) - (y - CINEMA_VIEWPORT_TOP) * u;
  rect.ymin = rect.ymax - h * u;
  return rect;
}

/** One cell of an \a count-way segmented track, inset from it. */
rctf segment_cell(const rctf &track, const int index, const int count)
{
  const float inset = 2.0f * cinema_unit();
  const float cell_w = (BLI_rctf_size_x(&track) - inset * 2.0f) / float(count);
  rctf cell;
  cell.xmin = track.xmin + inset + cell_w * float(index);
  cell.xmax = cell.xmin + cell_w;
  cell.ymin = track.ymin + inset;
  cell.ymax = track.ymax - inset;
  return cell;
}

/**
 * A segmented row of \a count cells: graded track, chip behind the live one.
 *
 * \a setup gives each cell's button its own properties. It used to be
 * hard-wired to three cells and one `WM_OT_context_set_int`, so the
 * four-cell resolution row was a thirty-line copy of it beside it.
 */
void segment_row(ui::Block *block,
                 const ARegion *region,
                 const float design_y,
                 const char *const *labels,
                 const char *const *values,
                 const int count,
                 const int active_index,
                 const char *operator_id,
                 const bool enabled,
                 const char *tooltip,
                 const char *surface,
                 blender::FunctionRef<void(ui::Button *, int)> setup)
{
  const float u = cinema_unit();
  MIXAR_THEME_LOAD(track_top, CinemaCardTop);
  MIXAR_THEME_LOAD(track_bottom, CinemaCardBottom);
  MIXAR_THEME_LOAD(chip, CinemaChip);
  MIXAR_THEME_LOAD(on, CinemaRowTextOn);
  MIXAR_THEME_LOAD(off, CinemaDimmer);

  const rctf track = column_card(region, design_y, CINEMA_SEGMENT_H);
  cinema_panel(track, CINEMA_ROW_RADIUS * u, track_top, track_bottom);

  for (int index = 0; index < count; index++) {
    const rctf cell = segment_cell(track, index, count);
    if (index == active_index) {
      cinema_fill(cell, BLI_rctf_size_y(&cell) * 0.5f, chip);
    }
    cinema_text_center_fitted(labels[index],
                              BLI_rctf_cent_x(&cell),
                              BLI_rctf_cent_y(&cell),
                              CINEMA_FONT_VALUE * u,
                              BLI_rctf_size_x(&cell) - 6.0f * u,
                              index == active_index ? on : off);

    cinema_qa_record(region, cell, surface, values[index], index);
    ui::Button *but = cinema_op_button(block, operator_id, cell, tooltip);
    if (but != nullptr) {
      setup(but, index);
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
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));

  /* -------- Cameras -------- */
  /* The list is the SCENE's cameras (view3d_director_cinema_cameras.cc): a
   * shot-based list could not show the scene's own default camera, nor any
   * camera added, imported or deleted outside Director. */
  cinema_draw_camera_list(
      block, C, region, state, column_card(region, CINEMA_COLUMN_TOP, CINEMA_CAMERAS_H));

  /* -------- Aerial view -------- */
  /* A live top-down map of the scene with the shot camera on it; a click or
   * drag on it places the camera at that world XY (`mixar.director_place_camera`).
   * Keyframe stills stay packed on the beats, only this card stopped showing
   * them; `cinema_image_preview` remains in `_paint.cc` for a future home. */
  cinema_draw_minimap(
      block, C, region, state, column_card(region, PREVIEW_Y, CINEMA_PREVIEW_H));

  /* -------- Frame rate --------
   *
   * Lit on the EFFECTIVE rate, `fps / fps_base`. Reading `fps` alone lit
   * "24fps" on a 23.976 scene (24 / 1.001) and "30fps" on a 29.97 one — the
   * chip claiming a rate the scene does not have. For the same reason the
   * cells go through a Director operator rather than `WM_OT_context_set_int`,
   * which could only write `fps` and would have left the base behind.
   *
   * The scene's frame rate and resolution are SCENE settings and are not
   * gated on a shot: they work before one exists, the way the grid chip
   * does. Gating them meant a fresh Cinema session could not set its rate. */
  const float fps_base = (scene && scene->r.frs_sec_base > 0.0f) ? scene->r.frs_sec_base : 1.0f;
  const float fps_effective = scene ? float(scene->r.frs_sec) / fps_base : 24.0f;
  constexpr int FPS_COUNT = 3;
  const char *const fps_labels[FPS_COUNT] = {"24fps", "30fps", "60fps"};
  const char *const fps_values[FPS_COUNT] = {"24", "30", "60"};
  const int fps_rates[FPS_COUNT] = {24, 30, 60};
  int fps_active = -1;
  for (int index = 0; index < FPS_COUNT; index++) {
    if (std::fabs(fps_effective - float(fps_rates[index])) < 0.01f) {
      fps_active = index;
    }
  }
  segment_row(block,
              region,
              FPS_Y,
              fps_labels,
              fps_values,
              FPS_COUNT,
              fps_active,
              "MIXAR_OT_director_set_fps",
              /*enabled=*/true,
              "Set the scene frame rate",
              "director_fps",
              [&](ui::Button *but, const int index) {
                RNA_int_set(ui::button_operator_ptr_ensure(but), "fps", fps_rates[index]);
              });

  /* -------- Resolution -------- */
  /* MIXAR_OT_director_set_resolution scales the SHORTER side to the tier, so
   * a 9:16 scene at 1080p is 1080x1920 — reading `ysch` matched nothing there
   * and no chip lit. The tier IS the short side. */
  const int short_side = scene ? std::min(scene->r.xsch, scene->r.ysch) : 1080;
  /* Mirrors RESOLUTION_PRESETS in `director/constants.py` — the tiers the
   * operator accepts. Keep the two in step. */
  constexpr int RES_COUNT = 4;
  const char *const res_labels[RES_COUNT] = {"720p", "1080p", "2K", "4K"};
  const char *const res_values[RES_COUNT] = {"HD720", "HD1080", "K2", "K4"};
  const int res_tiers[RES_COUNT] = {720, 1080, 1440, 2160};
  int res_active = -1;
  for (int index = 0; index < RES_COUNT; index++) {
    if (short_side == res_tiers[index]) {
      res_active = index;
    }
  }
  segment_row(block,
              region,
              RES_Y,
              res_labels,
              res_values,
              RES_COUNT,
              res_active,
              "MIXAR_OT_director_set_resolution",
              /*enabled=*/true,
              "Set the output resolution",
              "director_resolution",
              [&](ui::Button *but, const int index) {
                RNA_enum_set_identifier(const_cast<bContext *>(C),
                                        ui::button_operator_ptr_ensure(but),
                                        "preset",
                                        res_values[index]);
              });

  /* -------- Export -------- */
  const rctf export_rect = column_card(region, CINEMA_EXPORT_Y, CINEMA_EXPORT_H);
  MIXAR_THEME_LOAD(export_col, Primary);
  cinema_fill(export_rect, CINEMA_ROW_RADIUS * u, export_col);
  const bool can_export = !state.beats.is_empty();
  const float export_text[4] = {1.0f, 1.0f, 1.0f, can_export ? 1.0f : 0.45f};
  cinema_text_center_fitted("Export to Moodboard",
                            BLI_rctf_cent_x(&export_rect),
                            BLI_rctf_cent_y(&export_rect),
                            CINEMA_FONT_ACTION * u,
                            BLI_rctf_size_x(&export_rect) - CINEMA_CARD_PAD * 2.0f * u,
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
