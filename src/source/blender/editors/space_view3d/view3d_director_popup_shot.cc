/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native Flow-styled Shots, Camera, and Animation popups for the Director
 * tool rail. Presentation only: rows invoke the Python-owned
 * `mixar.director_*` operators and fields bind registered RNA directly.
 * Controls that already live elsewhere on the surface (Navigate/Precise on
 * the gate and dock, lens/aspect in their own popups, Fix Z / Auto Key)
 * are deliberately absent — each control has exactly one home.
 */

#include "BKE_context.hh"

#include "BLI_string.h"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"

namespace {

constexpr int POPUP_UNITS_WIDE = 12;

int popup_width()
{
  return UI_UNIT_X * POPUP_UNITS_WIDE;
}

int popup_row_height()
{
  return int(UI_UNIT_Y * 1.15f);
}

/* -------------------------------------------------------------------- */
/* Shots: the take list and session actions. */

uiBlock *shots_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  uiBlock *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data)) {
    director_popup_section_label(block, "Director is not available", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }

  const int width = popup_width();
  const int row_h = popup_row_height();
  const int gap = int(UI_UNIT_Y * 0.25f);
  int y = 0;

  PropertyRNA *shots_prop = RNA_struct_find_property(&data.state_ptr, "shots");
  const int shot_count = shots_prop ?
                             RNA_property_collection_length(&data.state_ptr, shots_prop) :
                             0;
  const int active_index = RNA_int_get(&data.state_ptr, "active_shot_index");

  y -= row_h;
  char heading[64];
  BLI_snprintf(heading, sizeof(heading), "Shots  ·  %d", shot_count);
  director_popup_section_label(block, heading, y, width - row_h - gap);
  uiBut *add = director_overlay_operator_button(block,
                                                "MIXAR_OT_director_new_shot",
                                                ICON_ADD,
                                                "",
                                                width - row_h,
                                                y,
                                                row_h,
                                                row_h,
                                                "Create a new shot camera from this view");
  director_popup_state(add, false, true);

  if (data.shot_ptr.data != nullptr) {
    y -= gap + row_h;
    uiBut *name = uiDefButR(block,
                            ButType::Text,
                            0,
                            "",
                            0,
                            y,
                            short(width),
                            short(row_h),
                            &data.shot_ptr,
                            "name",
                            0,
                            0,
                            0,
                            "Rename this shot");
    director_popup_state(name, false, !data.state.locked);
  }

  y -= gap;
  for (int index = 0; index < shot_count; index++) {
    PointerRNA shot_ptr;
    if (!RNA_property_collection_lookup_int(&data.state_ptr, shots_prop, index, &shot_ptr)) {
      continue;
    }
    char shot_name[128] = "";
    RNA_string_get(&shot_ptr, "name", shot_name);
    const int version = RNA_int_get(&shot_ptr, "version");
    const bool locked = RNA_enum_get(&shot_ptr, "state") == 1;
    char label[160];
    BLI_snprintf(label, sizeof(label), "%s  ·  T%d", shot_name, version);
    y -= row_h;
    uiBut *row = director_overlay_operator_button(block,
                                                  "MIXAR_OT_director_set_active_shot",
                                                  locked ? ICON_LOCKED : ICON_CAMERA_DATA,
                                                  label,
                                                  0,
                                                  y,
                                                  width,
                                                  row_h,
                                                  "Direct this shot");
    RNA_int_set(UI_but_operator_ptr_ensure(row), "index", index);
    director_popup_state(row, index == active_index, true);
  }

  y -= gap + row_h;
  if (data.state.locked) {
    uiBut *take = director_overlay_operator_button(block,
                                                   "MIXAR_OT_director_new_take",
                                                   ICON_DUPLICATE,
                                                   "Start New Take",
                                                   0,
                                                   y,
                                                   width,
                                                   row_h,
                                                   "Create an editable child of this locked take");
    director_popup_state(take, false, true);
    y -= row_h;
  }
  uiBut *remove = director_overlay_operator_button(block,
                                                   "MIXAR_OT_director_remove_shot",
                                                   ICON_CANCEL,
                                                   "Remove Shot",
                                                   0,
                                                   y,
                                                   width,
                                                   row_h,
                                                   "Remove this shot; the camera and images stay");
  director_popup_state(remove, false, shot_count > 0);
  y -= row_h;
  uiBut *finish = director_overlay_operator_button(block,
                                                   "MIXAR_OT_director_finish",
                                                   ICON_CHECKMARK,
                                                   "Finish Directing",
                                                   0,
                                                   y,
                                                   width,
                                                   row_h,
                                                   "Leave camera view without losing this take");
  director_popup_state(finish, false, true);

  director_popup_block_end(block);
  return block;
}

/* -------------------------------------------------------------------- */
/* Camera: the shot's story — direction, adherence, timing, guides. */

uiBlock *camera_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  uiBlock *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || data.shot_ptr.data == nullptr) {
    director_popup_section_label(block, "No active shot", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }
  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PointerRNA render_ptr = RNA_property_pointer_get(
      &scene_ptr, RNA_struct_find_property(&scene_ptr, "render"));

  const int width = popup_width();
  const int row_h = popup_row_height();
  const int gap = int(UI_UNIT_Y * 0.25f);
  const int half_w = (width - gap) / 2;
  const int label_h = int(UI_UNIT_Y * 0.85f);
  int y = 0;

  y -= label_h;
  director_popup_section_label(block, "What happens in the shot?", y, width);
  y -= row_h;
  uiBut *prompt = uiDefButR(block,
                            ButType::Text,
                            0,
                            "",
                            0,
                            y,
                            short(width),
                            short(row_h),
                            &data.shot_ptr,
                            "prompt",
                            0,
                            0,
                            0,
                            "Describe the action and motion between keyframes");
  director_popup_state(prompt, false, data.editable);
  y -= row_h;
  uiBut *adherence = uiDefButR(block,
                               ButType::Menu,
                               0,
                               std::nullopt,
                               0,
                               y,
                               short(width),
                               short(row_h),
                               &data.shot_ptr,
                               "guidance_strength",
                               0,
                               0,
                               0,
                               "How closely the video should follow the keyframes");
  director_popup_state(adherence, false, data.editable);

  y -= gap + label_h;
  director_popup_section_label(block, "Timing", y, width);
  y -= row_h;
  uiBut *fps = uiDefButR(block,
                         ButType::Num,
                         0,
                         "Frame Rate",
                         0,
                         y,
                         short(half_w),
                         short(row_h),
                         &render_ptr,
                         "fps",
                         0,
                         0,
                         0,
                         std::nullopt);
  director_popup_state(fps, false, data.editable);
  uiBut *spacing = uiDefButR(block,
                             ButType::NumSlider,
                             0,
                             "Spacing",
                             half_w + gap,
                             y,
                             short(half_w),
                             short(row_h),
                             &data.state_ptr,
                             "beat_seconds",
                             0,
                             0,
                             0,
                             "Seconds automatically placed between captured keyframes");
  director_popup_state(spacing, false, data.editable);

  if (data.camera != nullptr) {
    y -= gap + label_h;
    director_popup_section_label(block, "Guides", y, width);
    y -= row_h;
    const int third_w = (width - gap * 2) / 3;
    uiBut *thirds = uiDefButR(block,
                              ButType::Toggle,
                              0,
                              "Thirds",
                              0,
                              y,
                              short(third_w),
                              short(row_h),
                              &data.camera_data_ptr,
                              "show_composition_thirds",
                              0,
                              0,
                              0,
                              std::nullopt);
    director_popup_state(thirds, false, true);
    uiBut *safe = uiDefButR(block,
                            ButType::Toggle,
                            0,
                            "Safe Areas",
                            third_w + gap,
                            y,
                            short(third_w),
                            short(row_h),
                            &data.camera_data_ptr,
                            "show_safe_areas",
                            0,
                            0,
                            0,
                            std::nullopt);
    director_popup_state(safe, false, true);
    uiBut *path = uiDefButR(block,
                            ButType::Toggle,
                            0,
                            "Path",
                            (third_w + gap) * 2,
                            y,
                            short(width - (third_w + gap) * 2),
                            short(row_h),
                            &data.state_ptr,
                            "show_trajectory",
                            0,
                            0,
                            0,
                            std::nullopt);
    director_popup_state(path, false, true);
  }

  director_popup_block_end(block);
  return block;
}

/* -------------------------------------------------------------------- */
/* Animation: blocking-level presets for the selected character. */

uiBlock *animation_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  uiBlock *block = director_popup_block_begin(C, region, __func__);
  const Object *active = CTX_data_active_object(C);
  const bool character = active && active->type != OB_CAMERA;

  const int width = popup_width();
  const int row_h = popup_row_height();
  const int gap = int(UI_UNIT_Y * 0.25f);
  const int half_w = (width - gap) / 2;
  const int label_h = int(UI_UNIT_Y * 0.85f);
  int y = 0;

  if (!character) {
    director_popup_section_label(block, "Select a character to animate", 0, UI_UNIT_X * 11);
    director_popup_block_end(block);
    return block;
  }

  DirectorPopupData data;
  const bool available = director_popup_data_get(C, &data);

  y -= label_h;
  char heading[160];
  BLI_snprintf(heading, sizeof(heading), "Animate  ·  %s", active->id.name + 2);
  director_popup_section_label(block, heading, y, width);

  struct PresetPair {
    const char *left_identifier;
    const char *left_label;
    const char *right_identifier;
    const char *right_label;
  };
  const PresetPair pairs[] = {
      {"WALK", "Walk Forward", "RUN", "Run Forward"},
      {"TURN_LEFT", "Turn Left", "TURN_RIGHT", "Turn Right"},
      {"TURN_AROUND", "Turn Around", "IDLE", "Idle"},
  };
  for (const PresetPair &pair : pairs) {
    y -= row_h;
    uiBut *left = director_overlay_operator_button(
        block,
        "MIXAR_OT_director_apply_animation",
        ICON_NONE,
        pair.left_label,
        0,
        y,
        half_w,
        row_h,
        "Key this blocking-level motion from the playhead");
    RNA_enum_set_identifier(C, UI_but_operator_ptr_ensure(left), "preset", pair.left_identifier);
    director_popup_state(left, false, true);
    uiBut *right = director_overlay_operator_button(
        block,
        "MIXAR_OT_director_apply_animation",
        ICON_NONE,
        pair.right_label,
        half_w + gap,
        y,
        half_w,
        row_h,
        "Key this blocking-level motion from the playhead");
    RNA_enum_set_identifier(C, UI_but_operator_ptr_ensure(right), "preset", pair.right_identifier);
    director_popup_state(right, false, true);
    y -= gap;
  }

  if (available) {
    y -= row_h;
    uiBut *seconds = uiDefButR(block,
                               ButType::NumSlider,
                               0,
                               "Motion Length",
                               0,
                               y,
                               short(width),
                               short(row_h),
                               &data.state_ptr,
                               "animation_seconds",
                               0,
                               0,
                               0,
                               std::nullopt);
    director_popup_state(seconds, false, true);
  }

  director_popup_block_end(block);
  return block;
}

}  // namespace

uiBlock *view3d_director_shots_popup_create(bContext *C, ARegion *region, void *arg)
{
  return shots_popup_create(C, region, arg);
}

uiBlock *view3d_director_camera_popup_create(bContext *C, ARegion *region, void *arg)
{
  return camera_popup_create(C, region, arg);
}

uiBlock *view3d_director_animation_popup_create(bContext *C, ARegion *region, void *arg)
{
  return animation_popup_create(C, region, arg);
}
