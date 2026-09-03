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
  /* Millimetres, never FOV degrees — the Director contract. */
  BLI_snprintf(label, size, "%dmm Lens", int(std::round(camera->lens)));
}

bool ratio_is(const int w, const int h, const int rw, const int rh)
{
  return int64_t(w) * rh == int64_t(h) * rw;
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
  if (ratio_is(w, h, 3, 2)) {
    BLI_strncpy(label, "Photography 3:2", size);
  }
  else if (ratio_is(w, h, 4, 3)) {
    BLI_strncpy(label, "Smartphone 4:3", size);
  }
  else if (ratio_is(w, h, 16, 9)) {
    BLI_strncpy(label, "Video TV 16:9", size);
  }
  else if (ratio_is(w, h, 185, 100)) {
    BLI_strncpy(label, "Cinema 1.85:1", size);
  }
  else if (ratio_is(w, h, 239, 100)) {
    BLI_strncpy(label, "Cinema 2.39:1", size);
  }
  else if (ratio_is(w, h, 9, 16)) {
    BLI_strncpy(label, "Social 9:16", size);
  }
  else if (ratio_is(w, h, 1, 1)) {
    BLI_strncpy(label, "Square 1:1", size);
  }
  else {
    BLI_snprintf(label, size, "%d x %d", w, h);
  }
}

/** What "Export to moodboard" will produce, summarised for the Output row. */
void output_label(const bContext *C, char *label, const int size)
{
  PointerRNA shot_ptr;
  if (!view3d_director_active_shot_pointer(CTX_data_scene(const_cast<bContext *>(C)), &shot_ptr)) {
    BLI_strncpy(label, "Png Sequence", size);
    return;
  }
  PropertyRNA *prop = RNA_struct_find_property(&shot_ptr, "render_output_types");
  const int flags = prop ? RNA_property_enum_get(&shot_ptr, prop) : 0;
  /* No guide kind selected means the export is keyframe stills only. */
  if (flags == 0) {
    BLI_strncpy(label, "Png Sequence", size);
    return;
  }
  const char *first = (flags & 1) ? "Beauty" : ((flags & 2) ? "Clay" : "Depth");
  int count = 0;
  for (int bit = 0; bit < 3; bit++) {
    count += (flags & (1 << bit)) ? 1 : 0;
  }
  if (count > 1) {
    BLI_snprintf(label, size, "%s +%d Video", first, count - 1);
  }
  else {
    BLI_snprintf(label, size, "%s Video", first);
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
  const float label_col[4] = CINEMA_COL_LABEL;
  const float value_col[4] = CINEMA_COL_VALUE;
  const float top[4] = CINEMA_COL_ROW_TOP;
  const float bottom[4] = CINEMA_COL_ROW_BOTTOM;

  const rctf row = cinema_design_rect(
      region, cinema_margin(region) + 13.0f, design_y, CINEMA_ROW_W, CINEMA_ROW_H);
  /* Caption sits 16 design px above the row. */
  cinema_text_left(caption,
                   row.xmin,
                   row.ymax + 14.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);
  cinema_text_left(value,
                   row.xmin + 14.0f * u,
                   BLI_rctf_cent_y(&row),
                   CINEMA_FONT_VALUE * u,
                   value_col);
  const float chevron[4] = {0.851f, 0.851f, 0.851f, 1.0f};
  cinema_chevron(row.xmax - 20.0f * u, BLI_rctf_cent_y(&row), 10.0f * u, chevron);

  ui::Button *but = cinema_popup_button(block, popup, row, tooltip);
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
      region, cinema_margin(region) + 13.0f, design_y, CINEMA_ROW_W, cinema_list_row_h());
  if (active) {
    const float top[4] = CINEMA_COL_ROW_TOP;
    const float bottom[4] = CINEMA_COL_ROW_BOTTOM;
    cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);
  }
  const float on[4] = CINEMA_COL_VALUE;
  const float off[4] = CINEMA_COL_DIM;
  cinema_text_left(label,
                   row.xmin + 14.0f * u,
                   BLI_rctf_cent_y(&row),
                   CINEMA_FONT_VALUE * u,
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
  cinema_qa_begin(region);
  const float u = cinema_unit();
  const float card_top[4] = CINEMA_COL_CARD_TOP;
  const float card_bottom[4] = CINEMA_COL_CARD_BOTTOM;
  const float label_col[4] = CINEMA_COL_LABEL;
  const bool editable = state.has_camera && !state.locked;

  /* Card 1 — output settings. */
  const rctf card1 = cinema_design_rect(region, cinema_margin(region), 208.0f, CINEMA_PANEL_W, 256.0f);
  cinema_panel(card1, CINEMA_PANEL_RADIUS * u, card_top, card_bottom);

  char label[128];
  aspect_label(C, label, sizeof(label));
  dropdown_row(block,
               region,
               "Aspect Ratio",
               label,
               246.0f,
               view3d_director_aspect_popup_create,
               "Choose the output aspect ratio",
               editable);

  lens_label(C, label, sizeof(label));
  dropdown_row(block,
               region,
               "Camera lens",
               label,
               325.0f,
               view3d_director_lens_popup_create,
               "Choose the lens type and focal length",
               editable);

  output_label(C, label, sizeof(label));
  dropdown_row(block,
               region,
               "Output",
               label,
               404.0f,
               view3d_director_render_popup_create,
               "Choose what Export to Moodboard produces",
               state.has_shot);

  /* Card 2 — template styles. */
  const rctf card2 = cinema_design_rect(region, cinema_margin(region), 475.0f, CINEMA_PANEL_W, 242.0f);
  cinema_panel(card2, CINEMA_PANEL_RADIUS * u, card_top, card_bottom);
  cinema_text_left("Template Style",
                   card2.xmin + 13.0f * u,
                   card2.ymax - 25.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  /* The shot records which template it is under, so the list highlights the
   * real state instead of guessing it from the flags each one happens to
   * leave behind. */
  char current[32] = "NONE";
  PointerRNA shot_ptr;
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
  PointerRNA state_ptr;
  view3d_director_state_pointer(CTX_data_scene(const_cast<bContext *>(C)), &state_ptr);

  struct TemplateRow {
    const char *label;
    const char *identifier;
    float y;
  };
  const TemplateRow rows[] = {
      {"None", "NONE", 523.0f},
      {"Handheld camera", "HANDHELD", 557.0f},
      {"Z- Fixed", "Z_FIXED", 591.0f},
      {"Dolly Zoom", "DOLLY_ZOOM", 625.0f},
      {"Crane", "CRANE", 659.0f},
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

  /* Card 3 — speed (keyframe spacing). */
  const rctf card3 = cinema_design_rect(
      region, cinema_margin(region), CINEMA_SPEED_CARD_Y, CINEMA_PANEL_W, CINEMA_SPEED_CARD_H);
  cinema_panel(card3, CINEMA_PANEL_RADIUS * u, card_top, card_bottom);
  cinema_text_left("Speed",
                   card3.xmin + 13.0f * u,
                   card3.ymax - 22.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  const rctf meter = cinema_design_rect(
      region, cinema_margin(region) + 16.0f, 775.0f, 213.0f, 19.0f);
  /* The meter IS the slider's painted track, so it has to fill over the
   * property's OWN range (CINEMA_BEAT_SECONDS_MIN/MAX, mirroring
   * MIN/MAX_BEAT_SECONDS in `director/constants.py`) and in the direction the
   * slider travels — dragging right raises `beat_seconds` and fills the bar.
   * A narrower range clamped the top of the travel to an empty meter, and
   * filling the other way emptied the bar as the thumb moved right. */
  float beat_seconds = 1.0f;
  if (state_ptr.data != nullptr) {
    PropertyRNA *prop = RNA_struct_find_property(&state_ptr, "beat_seconds");
    if (prop != nullptr) {
      beat_seconds = RNA_property_float_get(&state_ptr, prop);
    }
  }
  constexpr int TICKS = 30;
  const float span = std::max(0.001f, CINEMA_BEAT_SECONDS_MAX - CINEMA_BEAT_SECONDS_MIN);
  const float travel = std::clamp((beat_seconds - CINEMA_BEAT_SECONDS_MIN) / span, 0.0f, 1.0f);
  cinema_tick_meter(meter, TICKS, int(std::round(travel * float(TICKS))));

  /* The real control rides on top of the painted meter so dragging behaves
   * exactly like any Blender slider.
   *
   * ui::ButtonType::Scroll, not NumSlider: both drag through `ui_numedit_but_SLI`,
   * but only Num/NumSlider build a value string in `ui_but_update`, and an
   * Emboss::None button still draws its text — a "1.0" straight across the
   * design's tick meter. Scroll leaves `drawstr` empty. */
  if (state_ptr.data != nullptr) {
    ui::block_emboss_set(block, blender::ui::EmbossType::None);
    ui::Button *slider = uiDefButR(block,
                              ui::ButtonType::Scroll,
                              "",
                              int(meter.xmin),
                              int(meter.ymin),
                              short(BLI_rctf_size_x(&meter)),
                              short(BLI_rctf_size_y(&meter)),
                              &state_ptr,
                              "beat_seconds",
                              0,
                              0,
                              0,
                              "Time placed between captured keyframes");
    ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
    director_overlay_disable_button(slider, !state.has_shot);
    cinema_qa_record(region, meter, "director_speed", "beat_seconds", -1);
  }
}

/** \} */

}  // namespace blender
