/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The Director depth-of-field popup: the switch, what the camera focuses on,
 * and the aperture that decides how much of the shot is sharp.
 *
 * It sits in the left column's output card, in the slot the redundant
 * "Output" row left behind — depth of field IS an output decision, and it was
 * the one camera control the Cinema surface had no way to reach.
 *
 * Presentation only. Everything Blender already expresses as a value binds
 * `camera.data.dof`'s OWN properties, so no range, unit or default is
 * restated here; only the f-stop slider's TRAVEL is narrowed, which is a UI
 * decision rather than a property one. The two things a director means that
 * Blender has no property for — focus on THAT, and let it go without the
 * image jumping — are the Python-owned `mixar.director_*` operators.
 */

#include <cmath>

#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_camera_types.h"
#include "DNA_object_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Focus rows
 * \{ */

/** The object the camera is focusing on, or null. */
const Object *focus_object_of(PointerRNA *dof_ptr)
{
  PropertyRNA *prop = RNA_struct_find_property(dof_ptr, "focus_object");
  if (prop == nullptr) {
    return nullptr;
  }
  const PointerRNA focus = RNA_property_pointer_get(dof_ptr, prop);
  return static_cast<const Object *>(focus.data);
}

/** Eyedropper + release, side by side: pick what is sharp, or let it go. */
void focus_pick_row(ui::Block *block,
                    bContext *C,
                    const DirectorPopupData &data,
                    const bool focused,
                    const int y,
                    const int width,
                    const int row_h,
                    const int gap)
{
  const int half_w = (width - gap) / 2;
  /* The SAME eyedropper the top strip uses for tracking: one modal, one
   * hover outline, one ray cast — `purpose` decides only what the picked
   * object becomes. It resolves the real viewport itself, so starting it
   * from this popup hovers where the director is looking. */
  ui::Button *pick = director_overlay_operator_button(
      block,
      "MIXAR_OT_director_pick_track_target",
      ICON_EYEDROPPER,
      "Pick",
      0,
      y,
      half_w,
      row_h,
      "Eyedropper: click an object to keep it in focus");
  if (pick != nullptr) {
    PointerRNA *ptr = ui::button_operator_ptr_ensure(pick);
    RNA_enum_set_identifier(C, ptr, "purpose", "FOCUS");
    director_popup_state(pick, false, data.editable);
  }
  ui::Button *release = director_overlay_operator_button(
      block,
      "MIXAR_OT_director_set_focus",
      ICON_NONE,
      "Release",
      half_w + gap,
      y,
      half_w,
      row_h,
      "Stop following the object and hold the distance it was focused at");
  if (release != nullptr) {
    RNA_enum_set_identifier(C, ui::button_operator_ptr_ensure(release), "mode", "CLEAR");
    /* Nothing to release is not an error to discover by pressing it. */
    director_popup_state(release, false, data.editable && focused);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Popup
 * \{ */

ui::Block *dof_popup_create(bContext *C, ARegion *region, void *arg)
{
  ui::Block *block = director_popup_block_begin(C, region, __func__);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || !data.camera) {
    director_popup_section_label(block, "No active shot camera", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }
  PropertyRNA *dof_prop = RNA_struct_find_property(&data.camera_data_ptr, "dof");
  PointerRNA dof_ptr = {};
  if (dof_prop != nullptr) {
    dof_ptr = RNA_property_pointer_get(&data.camera_data_ptr, dof_prop);
  }
  if (dof_ptr.data == nullptr) {
    director_popup_section_label(block, "Depth of field unavailable", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }

  const int width = director_popup_width(arg, UI_UNIT_X * 12);
  const int row_h = int(UI_UNIT_Y * 1.15f);
  const int gap = int(UI_UNIT_Y * 0.3f);
  const int label_h = int(UI_UNIT_Y * 0.85f);
  int y = 0;

  y -= row_h;
  ui::Button *enable = ui::uiDefButR(block,
                                     ui::ButtonType::Toggle,
                                     "Depth of Field",
                                     0,
                                     y,
                                     short(width),
                                     short(row_h),
                                     &dof_ptr,
                                     "use_dof",
                                     0,
                                     0,
                                     0,
                                     "Blur what is not at the focus distance");
  director_popup_state(enable, false, data.editable);

  /* Every row, always. The popup stays open (BLOCK_KEEP_OPEN) and a
   * block-button popup cannot re-lay itself, so a row that appears only when
   * `use_dof` is on would still be absent the moment after the toggle above
   * turned it on — which is the whole flow: switch it on, then set the stop.
   * Nothing below is dangerous while it is off, and choosing a stop or a
   * focus object switches it on by itself. */
  const Object *focus = focus_object_of(&dof_ptr);

  /* A plain caption, not "Focusing on <name>": the popup stays open and
   * cannot re-lay itself, so a label naming the focus object would keep
   * naming the old one the moment Pick or Release changed it. The left
   * column's own Depth of Field row carries that name and redraws live. */
  y -= gap + label_h;
  director_popup_section_label(block, "Focus", y, width);

  y -= row_h;
  focus_pick_row(block, C, data, focus != nullptr, y, width, row_h, gap);

  /* The camera is very often already pointed at the thing that should be
   * sharp. Offered only when it IS — a row that can only report "pick a
   * subject first" is not a control. */
  PropertyRNA *track_prop = data.shot_ptr.data ?
                                RNA_struct_find_property(&data.shot_ptr, "track_target") :
                                nullptr;
  const Object *tracked = nullptr;
  if (track_prop != nullptr) {
    const PointerRNA target = RNA_property_pointer_get(&data.shot_ptr, track_prop);
    tracked = static_cast<const Object *>(target.data);
  }
  if (tracked != nullptr && tracked != focus) {
    /* The tracked subject can only change from OUTSIDE this popup (the top
     * strip's eyedropper), so branching on it cannot go stale under the
     * pointer the way `use_dof` and the focus object can. */
    y -= gap + row_h;
    ui::Button *subject = director_overlay_operator_button(
        block,
        "MIXAR_OT_director_set_focus",
        ICON_NONE,
        "Focus on Tracked Subject",
        0,
        y,
        width,
        row_h,
        "Focus on the object this camera is already pointing at");
    if (subject != nullptr) {
      RNA_enum_set_identifier(C, ui::button_operator_ptr_ensure(subject), "mode", "SUBJECT");
      director_popup_state(subject, false, data.editable);
    }
  }

  /* Blender ignores the distance while a focus OBJECT is set, and Release
   * writes the distance it was focusing at into this very field — so the row
   * is always here rather than appearing and disappearing under the pointer.
   * The caption above says which of the two is currently in charge. */
  y -= gap + row_h;
  ui::Button *distance = ui::uiDefButR(block,
                                       ui::ButtonType::Num,
                                       "Focus Distance",
                                       0,
                                       y,
                                       short(width),
                                       short(row_h),
                                       &dof_ptr,
                                       "focus_distance",
                                       0,
                                       0,
                                       0,
                                       std::nullopt);
  director_popup_state(distance, false, data.editable);

  y -= gap + label_h;
  director_popup_section_label(block, "Aperture", y, width);

  /* Whole stops, the way a lens barrel is marked. Mirrors FSTOP_PRESETS in
   * `director/constants.py`. */
  constexpr int preset_count = 6;
  const float presets[preset_count] = {1.4f, 2.0f, 2.8f, 4.0f, 5.6f, 8.0f};
  /* Three per line rather than six: at a sixth of the popup's width every
   * label ellipsised, and "f/…" is not a stop. */
  constexpr int preset_cols = 3;
  const int preset_w = (width - gap * (preset_cols - 1)) / preset_cols;
  PropertyRNA *fstop_prop = RNA_struct_find_property(&dof_ptr, "aperture_fstop");
  const float fstop = fstop_prop ? RNA_property_float_get(&dof_ptr, fstop_prop) : 0.0f;
  for (int index = 0; index < preset_count; index++) {
    const int column = index % preset_cols;
    if (column == 0) {
      y -= (index == 0) ? row_h : gap + row_h;
    }
    char label[16];
    /* f/8, not f/8.0: nobody marks a barrel to a decimal it does not need. */
    if (std::fabs(presets[index] - std::round(presets[index])) < 0.05f) {
      BLI_snprintf(label, sizeof(label), "f/%.0f", double(presets[index]));
    }
    else {
      BLI_snprintf(label, sizeof(label), "f/%.1f", double(presets[index]));
    }
    ui::Button *but = director_overlay_operator_button(block,
                                                       "MIXAR_OT_director_set_fstop",
                                                       ICON_NONE,
                                                       label,
                                                       column * (preset_w + gap),
                                                       y,
                                                       preset_w,
                                                       row_h,
                                                       "Open or close the aperture to this stop");
    if (but != nullptr) {
      RNA_float_set(ui::button_operator_ptr_ensure(but), "fstop", presets[index]);
      director_popup_state(
          but, std::fabs(fstop - presets[index]) < 0.05f, data.editable);
    }
  }

  if (fstop_prop != nullptr) {
    y -= gap + row_h;
    /* The slider's TRAVEL, not the property's limits — the same decision the
     * focal-length slider makes. `aperture_fstop` has no upper soft bound
     * anyone would call photographic, so the drag covers f/0.95 to f/22 and
     * text entry still reaches the rest. Mirrors FSTOP_SLIDER_MIN / _MAX in
     * `director/constants.py`. */
    ui::Button *slider = ui::uiDefButR(block,
                                       ui::ButtonType::NumSlider,
                                       "f-stop",
                                       0,
                                       y,
                                       short(width),
                                       short(row_h),
                                       &dof_ptr,
                                       "aperture_fstop",
                                       0,
                                       FSTOP_SLIDER_MIN,
                                       FSTOP_SLIDER_MAX,
                                       std::nullopt);
    ui::button_number_slider_step_size_set(slider, 0.1f);
    ui::button_number_slider_precision_set(slider, 1.0f);
    director_popup_state(slider, false, data.editable);
  }

  director_popup_block_end(block);
  return block;
}

/** \} */

}  // namespace

ui::Block *view3d_director_dof_popup_create(bContext *C, ARegion *region, void *arg)
{
  return dof_popup_create(C, region, arg);
}

}  // namespace blender
