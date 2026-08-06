/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native Flow-styled popups for the Director camera gate and tool rail.
 *
 * Presentation lives here; behavior stays owned by the Python operators
 * every row invokes (`mixar.director_*`). RNA sliders bind straight to the
 * registered Director/camera properties, so no value logic is duplicated.
 */

#include <cmath>

#include "BKE_context.hh"

#include "DNA_camera_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"

bool director_popup_data_get(bContext *C, DirectorPopupData *r_data)
{
  Scene *scene = CTX_data_scene(C);
  if (!view3d_director_state_read(scene, &r_data->state) || !r_data->state.available) {
    return false;
  }
  view3d_director_state_pointer(scene, &r_data->state_ptr);
  if (view3d_director_active_shot_pointer(scene, &r_data->shot_ptr)) {
    PropertyRNA *camera_prop = RNA_struct_find_property(&r_data->shot_ptr, "camera");
    if (camera_prop) {
      PointerRNA camera_ptr = RNA_property_pointer_get(&r_data->shot_ptr, camera_prop);
      Object *object = static_cast<Object *>(camera_ptr.data);
      if (object && object->type == OB_CAMERA) {
        r_data->camera_object = object;
        r_data->camera = static_cast<Camera *>(object->data);
        r_data->camera_data_ptr = RNA_id_pointer_create(&r_data->camera->id);
      }
    }
  }
  r_data->editable = r_data->camera != nullptr && !r_data->state.locked;
  return true;
}

uiBlock *director_popup_block_begin(bContext *C, ARegion *region, const char *name)
{
  uiBlock *block = UI_block_begin(C, region, name, blender::ui::EmbossType::Emboss);
  UI_block_theme_style_set(block, UI_BLOCK_THEME_STYLE_POPUP);
  return block;
}

void director_popup_block_end(uiBlock *block)
{
  UI_block_direction_set(block, UI_DIR_DOWN);
  UI_block_bounds_set_normal(block, int(0.4f * UI_UNIT_X));
}

void director_popup_state(uiBut *but, const bool active, const bool enabled)
{
  if (active) {
    UI_but_flag_enable(but, UI_BUT_ACTIVE_DEFAULT);
  }
  if (!enabled) {
    UI_but_flag_enable(but, UI_BUT_DISABLED);
  }
}

void director_popup_section_label(uiBlock *block,
                                  const char *text,
                                  const int y,
                                  const int width)
{
  uiDefBut(block,
           ButType::Label,
           0,
           text,
           0,
           y,
           short(width),
           short(UI_UNIT_Y * 0.85f),
           nullptr,
           0,
           0,
           std::nullopt);
}

namespace {

uiBut *popup_op_button(uiBlock *block,
                       const char *operator_id,
                       const int icon,
                       const char *label,
                       const int x,
                       const int y,
                       const int width,
                       const int height,
                       const char *tooltip)
{
  return director_overlay_operator_button(
      block, operator_id, icon, label, x, y, width, height, tooltip);
}

/* -------------------------------------------------------------------- */
/* Lens: projection type plus photographic focal-length presets. */

uiBlock *lens_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  uiBlock *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || !data.camera) {
    director_popup_section_label(block, "No active shot camera", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }

  const int width = UI_UNIT_X * 12;
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
  const int segment_w = width / 3;
  y -= row_h;
  for (int index = 0; index < 3; index++) {
    uiBut *but = popup_op_button(block,
                                 "MIXAR_OT_director_set_lens_type",
                                 ICON_NONE,
                                 types[index].label,
                                 index * segment_w,
                                 y,
                                 segment_w,
                                 row_h,
                                 "Switch the lens projection");
    RNA_enum_set_identifier(
        C, UI_but_operator_ptr_ensure(but), "lens_type", types[index].identifier);
    director_popup_state(but, data.camera->type == types[index].camera_type, data.editable);
  }
  y -= gap;

  if (data.camera->type == CAM_PERSP) {
    struct LensPreset {
      int mm;
      const char *label;
    };
    const LensPreset presets[] = {
        {18, "Ultra Wide  ·  18mm"},
        {24, "Wide  ·  24mm"},
        {35, "Classic  ·  35mm"},
        {50, "Standard  ·  50mm"},
        {85, "Portrait  ·  85mm"},
        {135, "Telephoto  ·  135mm"},
    };
    for (const LensPreset &preset : presets) {
      y -= row_h;
      uiBut *but = popup_op_button(block,
                                   "MIXAR_OT_director_set_lens",
                                   ICON_NONE,
                                   preset.label,
                                   0,
                                   y,
                                   width,
                                   row_h,
                                   "Apply this photographic focal length");
      RNA_int_set(UI_but_operator_ptr_ensure(but), "lens_mm", preset.mm);
      director_popup_state(but, std::abs(data.camera->lens - float(preset.mm)) < 0.5f, data.editable);
    }
    y -= gap + row_h;
    uiBut *slider = uiDefButR(block,
                              ButType::NumSlider,
                              0,
                              "Focal Length",
                              0,
                              y,
                              short(width),
                              short(row_h),
                              &data.camera_data_ptr,
                              "lens",
                              0,
                              0,
                              0,
                              std::nullopt);
    director_popup_state(slider, false, data.editable);
  }
  else {
    y -= gap + row_h;
    const bool ortho = data.camera->type == CAM_ORTHO;
    const std::optional<blender::StringRef> value_label =
        ortho ? std::optional<blender::StringRef>("Scale") : std::nullopt;
    uiBut *value = uiDefButR(block,
                             ortho ? ButType::NumSlider : ButType::Menu,
                             0,
                             value_label,
                             0,
                             y,
                             short(width),
                             short(row_h),
                             &data.camera_data_ptr,
                             ortho ? "ortho_scale" : "panorama_type",
                             0,
                             0,
                             0,
                             std::nullopt);
    director_popup_state(value, false, data.editable);
  }

  director_popup_block_end(block);
  return block;
}

/* -------------------------------------------------------------------- */
/* Aspect: named output formats. */

uiBlock *aspect_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  uiBlock *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || !data.camera) {
    director_popup_section_label(block, "No active shot camera", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }
  const Scene *scene = CTX_data_scene(C);

  struct AspectPreset {
    const char *identifier;
    const char *label;
    int ratio_width;
    int ratio_height;
  };
  const AspectPreset presets[] = {
      {"PHOTO", "Photography / DSLR  ·  3:2", 3, 2},
      {"SMARTPHONE", "Smartphones  ·  4:3", 4, 3},
      {"WIDE", "Video / TV  ·  16:9", 16, 9},
      {"CINEMA_185", "Cinema  ·  1.85:1", 185, 100},
      {"CINEMA_239", "Cinema  ·  2.39:1", 239, 100},
      {"VERTICAL", "Social media  ·  9:16", 9, 16},
      {"SQUARE", "Square  ·  1:1", 1, 1},
  };
  const int width = UI_UNIT_X * 12;
  const int row_h = int(UI_UNIT_Y * 1.15f);
  int y = 0;
  for (const AspectPreset &preset : presets) {
    y -= row_h;
    uiBut *but = popup_op_button(block,
                                 "MIXAR_OT_director_set_aspect",
                                 ICON_NONE,
                                 preset.label,
                                 0,
                                 y,
                                 width,
                                 row_h,
                                 "Set this output aspect ratio");
    RNA_enum_set_identifier(
        C, UI_but_operator_ptr_ensure(but), "preset", preset.identifier);
    const bool active = int64_t(scene->r.xsch) * preset.ratio_height ==
                        int64_t(scene->r.ysch) * preset.ratio_width;
    director_popup_state(but, active, data.editable);
  }

  director_popup_block_end(block);
  return block;
}

/* -------------------------------------------------------------------- */
/* Moves: one-click cinematic camera moves, timing, and handheld. */

uiBlock *moves_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  uiBlock *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || !data.camera) {
    director_popup_section_label(block, "No active shot camera", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }

  struct MovePair {
    const char *section;
    const char *left_identifier;
    int left_icon;
    const char *left_label;
    const char *right_identifier;
    int right_icon;
    const char *right_label;
  };
  const MovePair pairs[] = {
      {"Orbit", "ORBIT_LEFT", ICON_LOOP_BACK, "Left", "ORBIT_RIGHT", ICON_LOOP_FORWARDS, "Right"},
      {"Dolly", "DOLLY_IN", ICON_ZOOM_IN, "In", "DOLLY_OUT", ICON_ZOOM_OUT, "Out"},
      {"Crane", "CRANE_UP", ICON_TRIA_UP, "Up", "CRANE_DOWN", ICON_TRIA_DOWN, "Down"},
      {"Pan", "PAN_LEFT", ICON_BACK, "Left", "PAN_RIGHT", ICON_FORWARD, "Right"},
  };
  const int width = UI_UNIT_X * 12;
  const int row_h = int(UI_UNIT_Y * 1.15f);
  const int label_h = int(UI_UNIT_Y * 0.85f);
  const int gap = int(UI_UNIT_Y * 0.25f);
  const int half_w = (width - gap) / 2;
  int y = 0;

  for (const MovePair &pair : pairs) {
    y -= label_h;
    director_popup_section_label(block, pair.section, y, width);
    y -= row_h;
    uiBut *left = popup_op_button(block,
                                  "MIXAR_OT_director_camera_move",
                                  pair.left_icon,
                                  pair.left_label,
                                  0,
                                  y,
                                  half_w,
                                  row_h,
                                  "Capture this move as sparse keyframes");
    RNA_enum_set_identifier(
        C, UI_but_operator_ptr_ensure(left), "move", pair.left_identifier);
    director_popup_state(left, false, data.editable);
    uiBut *right = popup_op_button(block,
                                   "MIXAR_OT_director_camera_move",
                                   pair.right_icon,
                                   pair.right_label,
                                   half_w + gap,
                                   y,
                                   half_w,
                                   row_h,
                                   "Capture this move as sparse keyframes");
    RNA_enum_set_identifier(
        C, UI_but_operator_ptr_ensure(right), "move", pair.right_identifier);
    director_popup_state(right, false, data.editable);
    y -= gap;
  }

  y -= gap + row_h;
  uiBut *spacing = uiDefButR(block,
                             ButType::NumSlider,
                             0,
                             "Keyframe Spacing",
                             0,
                             y,
                             short(width),
                             short(row_h),
                             &data.state_ptr,
                             "beat_seconds",
                             0,
                             0,
                             0,
                             std::nullopt);
  director_popup_state(spacing, false, data.editable);

  y -= gap + row_h;
  uiBut *handheld = uiDefIconTextButR(block,
                                      ButType::Toggle,
                                      0,
                                      ICON_FORCE_TURBULENCE,
                                      "Handheld",
                                      0,
                                      y,
                                      short(half_w),
                                      short(row_h),
                                      &data.shot_ptr,
                                      "handheld",
                                      0,
                                      std::nullopt);
  director_popup_state(handheld, false, data.editable);
  uiBut *intensity = uiDefButR(block,
                               ButType::NumSlider,
                               0,
                               "",
                               half_w + gap,
                               y,
                               short(half_w),
                               short(row_h),
                               &data.shot_ptr,
                               "handheld_strength",
                               0,
                               0,
                               0,
                               std::nullopt);
  director_popup_state(intensity, false, data.editable);

  director_popup_block_end(block);
  return block;
}

}  // namespace

uiBlock *view3d_director_lens_popup_create(bContext *C, ARegion *region, void *arg)
{
  return lens_popup_create(C, region, arg);
}

uiBlock *view3d_director_aspect_popup_create(bContext *C, ARegion *region, void *arg)
{
  return aspect_popup_create(C, region, arg);
}

uiBlock *view3d_director_moves_popup_create(bContext *C, ARegion *region, void *arg)
{
  return moves_popup_create(C, region, arg);
}
