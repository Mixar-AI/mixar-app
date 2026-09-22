/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the left column — output settings, template styles, speed.
 *
 * Painting only — every control is an invisible ui::Button over the painted
 * pixels invoking a Python-owned `mixar.director_*` operator, or one of the
 * existing native Director popups.
 */

#include <algorithm>
#include <cmath>
#include <numeric>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_camera_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Readers
 * \{ */

const Camera *active_camera_data(const bContext *C)
{
  const Scene *scene = CTX_data_scene(C);
  const Object *camera = scene ? scene->camera : nullptr;
  if (camera == nullptr || camera->type != OB_CAMERA) {
    return nullptr;
  }
  return id_cast<const Camera *>(camera->data);
}

void lens_label(const bContext *C, char *label, const int size)
{
  const Camera *camera = active_camera_data(C);
  if (camera == nullptr) {
    BLI_strncpy(label, "No camera", size);
    return;
  }
  if (camera->type == CAM_ORTHO) {
    BLI_strncpy(label, "Orthographic", size);
    return;
  }
  if (camera->type == CAM_PANO) {
    BLI_strncpy(label, "Panoramic", size);
    return;
  }
  /* Millimetres, never FOV degrees — the Director contract. The row is
   * already captioned "Camera lens", so the value is just the length. */
  BLI_snprintf(label, size, "%dmm", int(std::round(camera->lens)));
}

/** The active camera's depth-of-field settings, through RNA. */
bool active_camera_dof(const bContext *C, PointerRNA *r_dof)
{
  const Scene *scene = CTX_data_scene(C);
  Object *camera = scene ? scene->camera : nullptr;
  if (camera == nullptr || camera->type != OB_CAMERA || camera->data == nullptr) {
    return false;
  }
  PointerRNA data_ptr = RNA_id_pointer_create(static_cast<ID *>(camera->data));
  PropertyRNA *prop = RNA_struct_find_property(&data_ptr, "dof");
  if (prop == nullptr) {
    return false;
  }
  *r_dof = RNA_property_pointer_get(&data_ptr, prop);
  return r_dof->data != nullptr;
}

/** ``f/8 · Suzanne``, ``f/2.8 · 4.2m``, or ``Off``. */
void dof_label(const bContext *C, char *label, const int size)
{
  PointerRNA dof = {};
  if (!active_camera_dof(C, &dof)) {
    BLI_strncpy(label, "No camera", size);
    return;
  }
  PropertyRNA *use_prop = RNA_struct_find_property(&dof, "use_dof");
  if (use_prop == nullptr || !RNA_property_boolean_get(&dof, use_prop)) {
    /* The one word that matters: everything is sharp. */
    BLI_strncpy(label, "Off", size);
    return;
  }
  char stop[16] = "";
  PropertyRNA *fstop_prop = RNA_struct_find_property(&dof, "aperture_fstop");
  if (fstop_prop != nullptr) {
    const double fstop = double(RNA_property_float_get(&dof, fstop_prop));
    /* f/8, not f/8.0: nobody quotes a stop to a decimal it does not need.
     * Two calls rather than a ternary format string, which is the one shape
     * a printf-checked helper cannot verify. */
    if (std::fabs(fstop - std::round(fstop)) < 0.05) {
      BLI_snprintf(stop, sizeof(stop), "f/%.0f", fstop);
    }
    else {
      BLI_snprintf(stop, sizeof(stop), "f/%.1f", fstop);
    }
  }
  PropertyRNA *focus_prop = RNA_struct_find_property(&dof, "focus_object");
  const Object *focus = nullptr;
  if (focus_prop != nullptr) {
    const PointerRNA target = RNA_property_pointer_get(&dof, focus_prop);
    focus = static_cast<const Object *>(target.data);
  }
  if (focus != nullptr) {
    /* What it is focused ON says more than how far away that happens to be,
     * and it is the value that keeps being true while the subject moves. */
    BLI_snprintf(label, size, "%s · %s", stop, focus->id.name + 2);
    return;
  }
  PropertyRNA *distance_prop = RNA_struct_find_property(&dof, "focus_distance");
  const double distance = distance_prop ? double(RNA_property_float_get(&dof, distance_prop)) :
                                          0.0;
  BLI_snprintf(label, size, "%s · %.1fm", stop, distance);
}

void aspect_label(const bContext *C, char *label, const int size)
{
  const Scene *scene = CTX_data_scene(C);
  if (scene == nullptr) {
    BLI_strncpy(label, "—", size);
    return;
  }
  const int w = scene->r.xsch;
  const int h = scene->r.ysch;
  /* The RATIO and nothing else. A director reads "2.39:1"; "Cinema 2.39:1"
   * is the same information plus a claim the ratios did not support — two of
   * the old labels named one medium at two different ratios. Mirrors
   * ASPECT_PRESETS in `director/constants.py`. */
  if (w <= 0 || h <= 0) {
    BLI_strncpy(label, "—", size);
    return;
  }
  const int divisor = std::gcd(w, h);
  const int rw = w / divisor;
  const int rh = h / divisor;
  /* Above TIDY_DENOMINATOR a reduced ratio stops reading as a ratio — 1.85:1
   * reduces to 37:20 and 2.39:1 to 239:100, and neither is how anyone says
   * it. Mirrors `ratio_label` in `director/core/aspect.py`. */
  constexpr int TIDY_DENOMINATOR = 16;
  if (std::min(rw, rh) <= TIDY_DENOMINATOR) {
    BLI_snprintf(label, size, "%d:%d", rw, rh);
  }
  else if (rw >= rh) {
    BLI_snprintf(label, size, "%.2f:1", double(rw) / double(rh));
  }
  else {
    BLI_snprintf(label, size, "1:%.2f", double(rh) / double(rw));
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Rows
 * \{ */

/** Labelled dropdown: grey caption, graded row, value, chevron. */
void dropdown_row(ui::Block *block,
                  const ARegion *region,
                  const char *caption,
                  const char *value,
                  const float design_y,
                  ui::BlockCreateFunc popup,
                  const char *tooltip,
                  const bool enabled)
{
  const float u = cinema_unit();
  MIXAR_THEME_LOAD(caption_col, CinemaRowCaption);
  MIXAR_THEME_LOAD(value_col, CinemaRowTextOn);
  MIXAR_THEME_LOAD(top, CinemaRowTop);
  MIXAR_THEME_LOAD(bottom, CinemaRowBottom);

  const rctf row = cinema_design_rect(
      region, cinema_margin(region) + CINEMA_CARD_PAD, design_y, CINEMA_ROW_W, CINEMA_ROW_H);
  /* Caption sits 12 design px above the row. */
  cinema_text_left(caption,
                   row.xmin,
                   row.ymax + 12.0f * u,
                   CINEMA_FONT_LABEL * u,
                   caption_col);

  /* The same row class as the My Cameras list: height, radius, gradient. */
  cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);
  /* Measured: `dof_label` builds "f/2.8 · <focus object>", and a long object
   * name used to run under the chevron and out of the card. */
  const float value_x = row.xmin + 12.0f * u;
  const float chevron_x = row.xmax - 18.0f * u;
  cinema_text_left_fitted(value,
                          value_x,
                          BLI_rctf_cent_y(&row),
                          CINEMA_FONT_VALUE * u,
                          chevron_x - 9.0f * u - value_x,
                          value_col);
  const float chevron[4] = {0.851f, 0.851f, 0.851f, 1.0f};
  cinema_chevron(chevron_x, BLI_rctf_cent_y(&row), 9.0f * u, chevron);

  ui::Button *but = cinema_popup_button(block, popup, row, tooltip, CinemaPopupSlot::Row);
  director_overlay_disable_button(but, !enabled);
  cinema_qa_record(region, row, "director_dropdown", caption, -1);
}

/** One template-style row; the live one gets the graded chip. */
void template_row(ui::Block *block,
                  const bContext *C,
                  const ARegion *region,
                  const char *label,
                  const char *identifier,
                  const float design_y,
                  const bool active,
                  const bool enabled)
{
  const float u = cinema_unit();
  /* List rows advance by CINEMA_LIST_PITCH; a taller row overlaps the next
   * one and the later-created button wins the shared band. */
  const rctf row = cinema_design_rect(
      region, cinema_margin(region) + CINEMA_CARD_PAD, design_y, CINEMA_ROW_W, cinema_list_row_h());
  if (active) {
    MIXAR_THEME_LOAD(top, CinemaRowTop);
    MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
    cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);
  }
  MIXAR_THEME_LOAD(on, CinemaRowTextOn);
  MIXAR_THEME_LOAD(off, CinemaRowTextDisabled);
  cinema_text_left_fitted(label,
                          row.xmin + 12.0f * u,
                          BLI_rctf_cent_y(&row),
                          CINEMA_FONT_VALUE * u,
                          BLI_rctf_size_x(&row) - 24.0f * u,
                          active ? on : off);

  cinema_qa_record(region, row, "director_template", identifier, -1);
  ui::Button *but = cinema_op_button(
      block, "MIXAR_OT_director_set_template", row, "Apply this camera template");
  if (but != nullptr) {
    RNA_enum_set_identifier(
        const_cast<bContext *>(C), ui::button_operator_ptr_ensure(but), "template", identifier);
    director_overlay_disable_button(but, !enabled);
  }
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Left column
 * \{ */

void cinema_draw_left_panel(ui::Block *block,
                            const bContext *C,
                            const ARegion *region,
                            const DirectorViewState &state)
{
  /* Records are cleared once per draw by the overlay, before the top strip
   * (which publishes the eyedropper and interpolation rects) — not here. */
  const float u = cinema_unit();
  MIXAR_THEME_LOAD(label_col, CinemaRowCaption);
  const bool editable = state.has_camera && !state.locked;

  /* Card 1 — output settings: three captioned rows at CINEMA_ROW_PITCH.
   *
   * The third used to be "Output", summarising what Export to Moodboard would
   * produce and opening the very popup the Export button opens — it said
   * nothing the export surface does not say better at the moment of use. Its
   * slot now holds Depth of Field, which is an output decision too and was
   * the one camera control the Cinema surface could not reach at all. */
  const rctf card1 = cinema_design_rect(region, cinema_margin(region), 208.0f, CINEMA_PANEL_W, 220.0f);
  cinema_glass_panel(card1, CINEMA_PANEL_RADIUS * u);

  char label[128];
  aspect_label(C, label, sizeof(label));
  dropdown_row(block,
               region,
               "Aspect Ratio",
               label,
               242.0f,
               view3d_director_aspect_popup_create,
               "Choose the output aspect ratio",
               editable);

  lens_label(C, label, sizeof(label));
  dropdown_row(block,
               region,
               "Camera lens",
               label,
               242.0f + CINEMA_ROW_PITCH,
               view3d_director_lens_popup_create,
               "Choose the lens type and focal length",
               editable);

  dof_label(C, label, sizeof(label));
  dropdown_row(block,
               region,
               "Depth of Field",
               label,
               242.0f + CINEMA_ROW_PITCH * 2.0f,
               view3d_director_dof_popup_create,
               "Choose what stays sharp and how much of the shot is blurred",
               editable);

  /* Card 2 — template styles. */
  const rctf card2 = cinema_design_rect(region, cinema_margin(region), 439.0f, CINEMA_PANEL_W, 220.0f);
  cinema_glass_panel(card2, CINEMA_PANEL_RADIUS * u);
  cinema_text_left("Template Style",
                   card2.xmin + CINEMA_CARD_PAD * u,
                   card2.ymax - 22.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  /* The shot records which template it is under, so the list highlights the
   * real state instead of guessing it from the flags each one happens to
   * leave behind. */
  char current[32] = "NONE";
  PointerRNA shot_ptr = {};
  if (view3d_director_active_shot_pointer(CTX_data_scene(const_cast<bContext *>(C)), &shot_ptr)) {
    PropertyRNA *prop = RNA_struct_find_property(&shot_ptr, "camera_template");
    if (prop != nullptr) {
      const int value = RNA_property_enum_get(&shot_ptr, prop);
      const char *identifier = nullptr;
      if (RNA_property_enum_identifier(
              const_cast<bContext *>(C), &shot_ptr, prop, value, &identifier) &&
          identifier != nullptr)
      {
        BLI_strncpy(current, identifier, sizeof(current));
      }
    }
  }

  struct TemplateRow {
    const char *label;
    const char *identifier;
    float y;
  };
  constexpr float first_template_y = 485.0f;
  const TemplateRow rows[] = {
      {"None", "NONE", first_template_y},
      {"Handheld camera", "HANDHELD", first_template_y + CINEMA_LIST_PITCH},
      {"Z-Fixed", "Z_FIXED", first_template_y + CINEMA_LIST_PITCH * 2.0f},
      {"Dolly Zoom", "DOLLY_ZOOM", first_template_y + CINEMA_LIST_PITCH * 3.0f},
      {"Crane", "CRANE", first_template_y + CINEMA_LIST_PITCH * 4.0f},
  };
  for (const TemplateRow &row : rows) {
    template_row(block,
                 C,
                 region,
                 row.label,
                 row.identifier,
                 row.y,
                 STREQ(current, row.identifier),
                 editable);
  }

  /* Card 3 — speed: retimes the shot. */
  const rctf card3 = cinema_design_rect(
      region, cinema_margin(region), CINEMA_SPEED_CARD_Y, CINEMA_PANEL_W, CINEMA_SPEED_CARD_H);
  cinema_glass_panel(card3, CINEMA_PANEL_RADIUS * u);
  cinema_text_left("Speed",
                   card3.xmin + CINEMA_CARD_PAD * u,
                   card3.ymax - 20.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  /* The meter is the card's content, so it takes the card's own inset and
   * width — it used to start 3 px right of the caption above it. */
  const rctf meter = cinema_design_rect(
      region, cinema_margin(region) + CINEMA_CARD_PAD, CINEMA_SPEED_CARD_Y + 40.0f,
      CINEMA_ROW_W, 16.0f);
  /* The meter IS the slider's painted track, so it has to light over the
   * property's OWN range (CINEMA_SPEED_MIN/MAX, mirroring SPEED_MIN/MAX in
   * `director/constants.py`) and in the direction the slider travels:
   * `shot.speed` rests at 0 in the middle (half-lit), dragging right contracts
   * the shot (faster) and fills the bar, dragging left expands it. */
  float speed = 0.0f;
  PropertyRNA *speed_prop = shot_ptr.data ? RNA_struct_find_property(&shot_ptr, "speed") :
                                            nullptr;
  if (speed_prop != nullptr) {
    speed = RNA_property_float_get(&shot_ptr, speed_prop);
  }
  /* The design's level bar: lit from the left as the slider travels, so the
   * neutral 0 sits half-lit in the middle and a faster shot reads as more. */
  constexpr int TICKS = 30;
  const float span = std::max(0.001f, CINEMA_SPEED_MAX - CINEMA_SPEED_MIN);
  const float travel = std::clamp((speed - CINEMA_SPEED_MIN) / span, 0.0f, 1.0f);
  cinema_tick_meter(meter, TICKS, int(std::round(travel * float(TICKS))));

  /* The real control rides on top of the painted meter so dragging behaves
   * exactly like any Blender slider.
   *
   * ui::ButtonType::Scroll, not NumSlider: both drag through `ui_numedit_but_SLI`,
   * but only Num/NumSlider build a value string in `ui_but_update`, and an
   * Emboss::None button still draws its text — a "0.0" straight across the
   * design's tick meter. Scroll leaves `drawstr` empty. */
  if (speed_prop != nullptr) {
    ui::block_emboss_set(block, blender::ui::EmbossType::None);
    ui::Button *slider = uiDefButR(block,
                              ui::ButtonType::Scroll,
                              "",
                              int(meter.xmin),
                              int(meter.ymin),
                              short(BLI_rctf_size_x(&meter)),
                              short(BLI_rctf_size_y(&meter)),
                              &shot_ptr,
                              "speed",
                              0,
                              0,
                              0,
                              "Speed of the shot: right plays it faster, left slower; the middle is as captured");
    ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
    director_overlay_disable_button(slider, !editable);
    cinema_qa_record(region, meter, "director_speed", "speed", -1);
  }
}

/** \} */

}  // namespace blender
