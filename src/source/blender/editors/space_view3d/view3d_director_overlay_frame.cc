/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Flow-inspired lens, navigation, aspect, and frame tools pinned to the
 * live camera gate of the Director viewport.
 */

#include <algorithm>
#include <cmath>
#include <numeric>

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_camera_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_view3d_types.h"

#include "ED_view3d.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"

namespace {

bool camera_border_get(const bContext *C, const ARegion *region, rctf *r_border)
{
  const View3D *v3d = CTX_wm_view3d(C);
  const RegionView3D *rv3d = CTX_wm_region_view3d(C);
  if (!v3d || !v3d->camera || !rv3d || rv3d->persp != RV3D_CAMOB) {
    return false;
  }
  ED_view3d_calc_camera_border(CTX_data_scene(C),
                               CTX_data_ensure_evaluated_depsgraph(C),
                               region,
                               v3d,
                               rv3d,
                               false,
                               r_border);
  r_border->xmin = std::clamp(r_border->xmin, 0.0f, float(region->winx));
  r_border->xmax = std::clamp(r_border->xmax, 0.0f, float(region->winx));
  r_border->ymin = std::clamp(r_border->ymin, 0.0f, float(region->winy));
  r_border->ymax = std::clamp(r_border->ymax, 0.0f, float(region->winy));
  return BLI_rctf_size_x(r_border) > 0.0f && BLI_rctf_size_y(r_border) > 0.0f;
}

/* Directors think in millimetres, never field-of-view degrees. */
void camera_lens_label(const View3D *v3d, char *label, const int label_size)
{
  const Object *object = v3d ? v3d->camera : nullptr;
  const Camera *camera = object && object->type == OB_CAMERA ?
                             static_cast<const Camera *>(object->data) :
                             nullptr;
  if (!camera) {
    BLI_strncpy(label, "Camera Lens", label_size);
    return;
  }
  if (camera->type == CAM_ORTHO) {
    BLI_strncpy(label, "Orthographic  ▾", label_size);
    return;
  }
  if (camera->type == CAM_PANO) {
    BLI_strncpy(label, "Panoramic  ▾", label_size);
    return;
  }
  BLI_snprintf(label, label_size, "%dmm  ▾", int(std::round(camera->lens)));
}

bool aspect_matches(const int width,
                    const int height,
                    const int ratio_width,
                    const int ratio_height)
{
  return int64_t(width) * ratio_height == int64_t(height) * ratio_width;
}

void camera_aspect_label(const Scene *scene, char *label, const int label_size)
{
  const int width = std::max(scene->r.xsch, 1);
  const int height = std::max(scene->r.ysch, 1);
  if (aspect_matches(width, height, 3, 2)) {
    BLI_strncpy(label, "Photography  3:2  ▾", label_size);
  }
  else if (aspect_matches(width, height, 4, 3)) {
    BLI_strncpy(label, "Smartphone  4:3  ▾", label_size);
  }
  else if (aspect_matches(width, height, 16, 9)) {
    BLI_strncpy(label, "Video / TV  16:9  ▾", label_size);
  }
  else if (aspect_matches(width, height, 185, 100)) {
    BLI_strncpy(label, "Cinema  1.85:1  ▾", label_size);
  }
  else if (aspect_matches(width, height, 239, 100)) {
    BLI_strncpy(label, "Cinema  2.39:1  ▾", label_size);
  }
  else if (aspect_matches(width, height, 9, 16)) {
    BLI_strncpy(label, "Social  9:16  ▾", label_size);
  }
  else if (width == height) {
    BLI_strncpy(label, "Square  1:1  ▾", label_size);
  }
  else {
    const int divisor = std::gcd(width, height);
    BLI_snprintf(label, label_size, "Aspect  %d:%d  ▾", width / divisor, height / divisor);
  }
}

}  // namespace

void view3d_director_frame_controls_draw(uiBlock *block,
                                         const bContext *C,
                                         const ARegion *region,
                                         const DirectorViewState &state,
                                         const int unit,
                                         const int gap)
{
  rctf border;
  if (!state.has_camera || !camera_border_get(C, region, &border)) {
    return;
  }
  const int button_h = unit * 2;
  const int lens_w = unit * 8;
  const int aspect_w = unit * 8;
  const int inset = gap * 2;
  const int border_w = int(BLI_rctf_size_x(&border));
  const int compact_navigation_w = button_h * 2 + gap;
  const int full_navigation_w = unit * 10 + gap;
  const bool compact_navigation = border_w < full_navigation_w + aspect_w + inset * 2 + gap;
  const int navigation_button_w = compact_navigation ? button_h : unit * 5;
  if (border_w < compact_navigation_w + aspect_w + inset * 2 + gap ||
      BLI_rctf_size_y(&border) < button_h * 3)
  {
    return;
  }

  const int left = int(border.xmin) + inset;
  const int right = int(border.xmax) - inset;
  const int bottom = int(border.ymin) + inset;
  const int top = int(border.ymax) - button_h - inset;
  char lens_label[96];
  char aspect_label[96];
  camera_lens_label(CTX_wm_view3d(C), lens_label, sizeof(lens_label));
  camera_aspect_label(CTX_data_scene(C), aspect_label, sizeof(aspect_label));

  uiBut *lens = uiDefBlockBut(block,
                              view3d_director_lens_popup_create,
                              nullptr,
                              lens_label,
                              left,
                              top,
                              short(lens_w),
                              short(button_h),
                              "Choose the lens type and focal length");
  director_overlay_disable_button(lens, state.locked);

  uiBut *navigate = director_overlay_operator_button(block,
                                                     "MIXAR_OT_director_navigate",
                                                     ICON_VIEW_PAN,
                                                     compact_navigation ? "" : "Navigate",
                                                     left,
                                                     bottom,
                                                     navigation_button_w,
                                                     button_h,
                                                     "Navigate with WASD and mouse");
  uiBut *precise = director_overlay_operator_button(block,
                                                    "MIXAR_OT_director_precise",
                                                    ICON_ORIENTATION_GIMBAL,
                                                    compact_navigation ? "" : "Precise",
                                                    left + navigation_button_w + gap,
                                                    bottom,
                                                    navigation_button_w,
                                                    button_h,
                                                    "Fine-tune with native camera gizmos");
  UI_but_flag_enable(state.navigate_mode ? navigate : precise, UI_BUT_ACTIVE_DEFAULT);
  director_overlay_disable_button(navigate, state.locked);
  director_overlay_disable_button(precise, state.locked);

  uiBut *aspect = uiDefBlockBut(block,
                                view3d_director_aspect_popup_create,
                                nullptr,
                                aspect_label,
                                right - aspect_w,
                                bottom,
                                short(aspect_w),
                                short(button_h),
                                "Choose the shot output aspect ratio");
  director_overlay_disable_button(aspect, state.locked);

  const float dot_size = std::max(7.0f, 8.0f * UI_SCALE_FAC);
  /* Frame tools are view-only, so they stay enabled on locked takes. */
  const int frame_tools_right = right - int(dot_size) - gap;
  if (border_w > lens_w + button_h * 3 + inset * 2 + gap * 3) {
    director_overlay_operator_button(block,
                                     "MIXAR_OT_director_fit_frame",
                                     ICON_FULLSCREEN_ENTER,
                                     "",
                                     frame_tools_right - button_h,
                                     top,
                                     button_h,
                                     button_h,
                                     "Fill the viewport with the camera frame; click again to "
                                     "shrink it back");
    director_overlay_operator_button(
        block,
        "MIXAR_OT_director_drag_frame",
        ICON_VIEW_PAN,
        "",
        frame_tools_right - button_h * 2 - gap,
        top,
        button_h,
        button_h,
        "Move the camera frame; scroll resizes, click places, Esc reverts");
  }
  const rctf active_dot = {border.xmax - inset - dot_size,
                           border.xmax - inset,
                           border.ymax - inset - dot_size,
                           border.ymax - inset};
  const float active_color[4] = {0.25f, 0.92f, 0.52f, 1.0f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&active_dot, true, dot_size * 0.5f, active_color);
}
