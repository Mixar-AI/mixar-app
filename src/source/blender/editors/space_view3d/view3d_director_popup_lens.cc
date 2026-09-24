/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The Director camera-lens popup: projection type, focal-length presets, and
 * the fields the chosen projection actually uses.
 *
 * Split from `view3d_director_popup.cc` for the 500-line rule once the
 * panoramic projections grew their own controls.
 *
 * Presentation only; behavior stays owned by the Python operators every row
 * invokes (`mixar.director_*`), and the value controls bind the camera's own
 * RNA so no range or unit is duplicated here — only the slider TRAVEL is
 * narrowed, which is a UI decision, not a property one.
 */

#include <algorithm>
#include <cmath>

#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_camera_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "../interface/interface_mixar_profile_card.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/**
 * One cell of a segmented group: the row state (BUT_ACTIVE_DEFAULT carries
 * "active", BUT_DISABLED "locked"), then the Segment kind on top so the
 * cells on this baseline paint as one hover-expanding group. The cells are
 * laid out as equal parts of the row; their hit rects never change on hover
 * (a refresh happens only after a row runs), only the painted widths do.
 */
void popup_segment_state(ui::Button *but, const bool active, const bool enabled)
{
  director_popup_state(but, active, enabled);
  ui::UI_mixar_cinema_row_tag(but, ui::MixarCinemaRowKind::Segment);
}

/**
 * The controls each panoramic projection is actually defined by.
 *
 * Blender puts these on the camera data and which ones MEAN anything depends
 * on `panorama_type`; showing all of them would be as unhelpful as showing
 * none. Keyed by the RNA enum IDENTIFIER rather than a DNA constant so the
 * table reads the same list the property itself accepts.
 *
 * A projection not listed here (Mirror Ball, Equiangular Cubemap Face) has no
 * parameters of its own — an empty row list is the correct answer, not a gap.
 */
struct PanoramaFields {
  const char *identifier;
  const char *properties[8];
};

const PanoramaFields PANORAMA_FIELDS[] = {
    {"EQUIRECTANGULAR",
     {"latitude_min", "latitude_max", "longitude_min", "longitude_max", nullptr}},
    {"FISHEYE_EQUIDISTANT", {"fisheye_fov", nullptr}},
    /* Equisolid is defined by a real lens on a real sensor. */
    {"FISHEYE_EQUISOLID", {"fisheye_lens", "fisheye_fov", "sensor_width", nullptr}},
    {"FISHEYE_LENS_POLYNOMIAL",
     {"fisheye_fov",
      "fisheye_polynomial_k0",
      "fisheye_polynomial_k1",
      "fisheye_polynomial_k2",
      "fisheye_polynomial_k3",
      "fisheye_polynomial_k4",
      nullptr}},
    {"MIRRORBALL", {nullptr}},
    {"EQUIANGULAR_CUBEMAP_FACE", {nullptr}},
};

/** The camera's current `panorama_type` identifier, or null. */
const char *panorama_type_identifier(bContext *C, PointerRNA *camera_data_ptr)
{
  PropertyRNA *prop = RNA_struct_find_property(camera_data_ptr, "panorama_type");
  if (prop == nullptr) {
    return nullptr;
  }
  const char *identifier = nullptr;
  if (!RNA_property_enum_identifier(C,
                                    camera_data_ptr,
                                    prop,
                                    RNA_property_enum_get(camera_data_ptr, prop),
                                    &identifier))
  {
    return nullptr;
  }
  return identifier;
}

/** Lay the live projection's own rows; returns the y below them. */
int panorama_fields(ui::Block *block,
                    bContext *C,
                    DirectorPopupData *data,
                    int y,
                    const int width,
                    const int row_h,
                    const int gap)
{
  const char *identifier = panorama_type_identifier(C, &data->camera_data_ptr);
  if (identifier == nullptr) {
    return y;
  }
  for (const PanoramaFields &entry : PANORAMA_FIELDS) {
    if (!STREQ(entry.identifier, identifier)) {
      continue;
    }
    for (const char *property : entry.properties) {
      if (property == nullptr) {
        break;
      }
      /* Skipped rather than drawn blank when the running Blender does not
       * have it: a renamed property costs one control, not the popup. */
      if (RNA_struct_find_property(&data->camera_data_ptr, property) == nullptr) {
        continue;
      }
      y -= gap + row_h;
      /* The label is the property's own RNA name — nothing about it is
       * restated here, so a Blender rename carries through. */
      ui::Button *but = ui::uiDefButR(block,
                                      ui::ButtonType::NumSlider,
                                      std::nullopt,
                                      0,
                                      y,
                                      short(width),
                                      short(row_h),
                                      &data->camera_data_ptr,
                                      property,
                                      0,
                                      0,
                                      0,
                                      std::nullopt);
      director_popup_state(but, false, data->editable);
    }
    break;
  }
  return y;
}

/* A projection switch DISMISSES the popup, and the popup shows one
 * projection's controls at a time.
 *
 * Drawing Perspective's rows AND Orthographic's, always, captioned, put a
 * focal length, a preset ladder and an orthographic scale on screen together
 * and left the director to work out which half applied. Picking a
 * projection is picking a mode: the row's own value label reads it back
 * ("Orthographic", "50mm") and reopening shows that projection's controls.
 * The popup could re-lay in place now (`BLOCK_MIXAR_POPUPS_REFRESH`), but
 * closing also clears the view for what a Panoramic pick switches — Cycles
 * and the Rendered viewport (`director/core/panoramic.py`). */
void lens_popup_close(bContext * /*C*/, void *arg_block, void * /*arg2*/)
{
  ui::popup_menu_retval_set(static_cast<ui::Block *>(arg_block), ui::RETURN_OK, true);
}

/* -------------------------------------------------------------------- */
/* Lens: projection type plus photographic focal-length presets. */

ui::Block *lens_popup_create(bContext *C, ARegion *region, void *arg)
{
  ui::Block *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || !data.camera) {
    director_popup_section_label(block, "No active shot camera", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }

  const int width = director_popup_width(arg, UI_UNIT_X * 12);
  const int row_h = int(UI_UNIT_Y * 1.15f);
  const int gap = int(UI_UNIT_Y * 0.3f);
  int y = 0;

  struct LensType {
    const char *identifier;
    const char *label;
    short camera_type;
  };
  const LensType types[] = {
      {"PERSP", "Perspective", CAM_PERSP},
      {"ORTHO", "Orthographic", CAM_ORTHO},
      {"PANO", "Panoramic", CAM_PANO},
  };
  /* Each cell spans from its own edge to the NEXT one's, so integer
   * division cannot leave the last cell short of the row's right edge. */
  const auto segment_x = [width](const int index) { return (width * index) / 3; };
  y -= row_h;
  for (int index = 0; index < 3; index++) {
    ui::Button *but = director_overlay_operator_button(block,
                                 "MIXAR_OT_director_set_lens_type",
                                 ICON_NONE,
                                 types[index].label,
                                 segment_x(index),
                                 y,
                                 segment_x(index + 1) - segment_x(index),
                                 row_h,
                                 "Switch the lens projection");
    RNA_enum_set_identifier(
        C, ui::button_operator_ptr_ensure(but), "lens_type", types[index].identifier);
    const bool live = data.camera->type == types[index].camera_type;
    popup_segment_state(but, live, data.editable);
    if (!live) {
      /* Only a real switch dismisses: re-picking the live projection is a
       * no-op and closing on it would read as the popup misbehaving. */
      ui::button_func_set(but, lens_popup_close, block, nullptr);
    }
  }
  y -= gap;

  /* ONE projection's controls: the live one. A switch closes the popup
   * (`lens_popup_close`), so these rows can never be the previous
   * projection's. */
  const int label_h = int(UI_UNIT_Y * 0.85f);
  if (data.camera->type == CAM_PERSP) {
    y -= gap + label_h;
    director_popup_section_label(block, "Perspective", y, width);
    /* A focal length is named by its focal length: a descriptive word in
     * front of it is the same number plus the arguable half, since 35mm reads
     * as normal to one director and wide to another. Mirrors LENS_PRESETS_MM
     * in `director/constants.py`. */
    const int presets[] = {18, 24, 35, 50, 85, 135};
    for (const int mm : presets) {
      y -= row_h;
      char label[16];
      BLI_snprintf(label, sizeof(label), "%dmm", mm);
      ui::Button *but = director_overlay_operator_button(block,
                                   "MIXAR_OT_director_set_lens",
                                   ICON_NONE,
                                   label,
                                   0,
                                   y,
                                   width,
                                   row_h,
                                   "Apply this focal length");
      RNA_int_set(ui::button_operator_ptr_ensure(but), "lens_mm", mm);
      director_popup_state(but, std::abs(data.camera->lens - float(mm)) < 0.5f, data.editable);
    }
    y -= gap + row_h;
    /* The slider's TRAVEL, not the property's limits.
     *
     * `Camera.lens` has a stock soft range of 1-5000mm, which puts the whole
     * usable photographic range inside the first few pixels of the drag: the
     * control was unusable for the values anyone actually wants. Passing
     * min/max here narrows the DRAG; typing still reaches the property's hard
     * range, so nothing is taken away. Mirrors LENS_SLIDER_MIN_MM /
     * LENS_SLIDER_MAX_MM in `director/constants.py`. */
    ui::Button *slider = ui::uiDefButR(block,
                              ui::ButtonType::NumSlider,
                              "Focal Length",
                              0,
                              y,
                              short(width),
                              short(row_h),
                              &data.camera_data_ptr,
                              "lens",
                              0,
                              LENS_SLIDER_MIN_MM,
                              LENS_SLIDER_MAX_MM,
                              std::nullopt);
    /* One millimetre per step, and no decimals: a focal length nobody quotes
     * to two places should not be shown to two places. */
    ui::button_number_slider_step_size_set(slider, 1.0f);
    ui::button_number_slider_precision_set(slider, 0.0f);
    director_popup_state(slider, false, data.editable);
  }

  if (data.camera->type == CAM_ORTHO) {
    y -= gap + label_h;
    director_popup_section_label(block, "Orthographic", y, width);
    y -= row_h;
    /* Same problem as the focal length: `ortho_scale`'s stock soft range runs
     * to 1000, so one pixel of drag was a different shot. Mirrors
     * ORTHO_SCALE_SLIDER_MIN / _MAX in `director/constants.py`. */
    ui::Button *value = ui::uiDefButR(block,
                             ui::ButtonType::NumSlider,
                             "Scale",
                             0,
                             y,
                             short(width),
                             short(row_h),
                             &data.camera_data_ptr,
                             "ortho_scale",
                             0,
                             ORTHO_SCALE_SLIDER_MIN,
                             ORTHO_SCALE_SLIDER_MAX,
                             std::nullopt);
    ui::button_number_slider_step_size_set(value, 0.05f);
    ui::button_number_slider_precision_set(value, 2.0f);
    director_popup_state(value, false, data.editable);
  }

  if (data.camera->type == CAM_PANO) {
    /* Panoramic's fields are defined by `panorama_type`, a menu INSIDE this
     * popup. The popup re-lays itself after a row runs
     * (`BLOCK_MIXAR_POPUPS_REFRESH`), so picking a panorama type shows that
     * type's parameters at once; it used to need the popup reopened. */
    y -= gap + label_h;
    director_popup_section_label(block, "Panoramic", y, width);
    y -= gap + row_h;
    ui::Button *type_menu = ui::uiDefButR(block,
                                          ui::ButtonType::Menu,
                                          std::nullopt,
                                          0,
                                          y,
                                          short(width),
                                          short(row_h),
                                          &data.camera_data_ptr,
                                          "panorama_type",
                                          0,
                                          0,
                                          0,
                                          std::nullopt);
    director_popup_state(type_menu, false, data.editable);

    /* Each projection has its OWN controls, and the popup used to offer the
     * type and nothing else — so picking Fisheye Equisolid changed the
     * projection and left no way to set the lens or the field of view it is
     * defined by. Rows are looked up by name and skipped when the running
     * Blender does not have them, so a renamed property costs a control
     * rather than the whole popup. Labels come from the properties' own RNA
     * names; nothing about them is restated here. */
    y = panorama_fields(block, C, &data, y, width, row_h, gap);

    /* Panoramic projections are a Cycles feature: EEVEE renders the camera as
     * a plain perspective, so the viewport can disagree with the render and
     * nothing on screen would say why. */
    const Scene *scene = CTX_data_scene(C);
    if (scene != nullptr && !STREQ(scene->r.engine, "CYCLES")) {
      y -= gap + int(UI_UNIT_Y * 0.85f);
      director_popup_section_label(block, "Renders in Cycles only", y, width);
    }
  }

  director_popup_block_end(block);
  return block;
}

}  // namespace

ui::Block *view3d_director_lens_popup_create(bContext *C, ARegion *region, void *arg)
{
  return lens_popup_create(C, region, arg);
}

}  // namespace blender
