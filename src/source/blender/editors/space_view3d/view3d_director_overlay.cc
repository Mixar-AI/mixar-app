/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Floating Flow-inspired controls over the Director camera viewport.
 */

#include <algorithm>
#include <cmath>
#include <cstring>
#include <numeric>

#include "BLF_api.hh"

#include "BLI_math_base.h"
#include "BLI_math_rotation.h"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_camera.h"
#include "BKE_context.hh"

#include "DNA_camera_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_view3d_types.h"

#include "ED_screen.hh"
#include "ED_view3d.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"

namespace {

constexpr float PANEL_COLOR[4] = {0.055f, 0.058f, 0.066f, 0.94f};
constexpr float PANEL_BORDER[4] = {0.28f, 0.29f, 0.33f, 0.8f};
constexpr float TEXT_MUTED[4] = {0.70f, 0.71f, 0.75f, 1.0f};

void draw_panel(const rctf &rect, const float radius)
{
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv_ex(&rect, PANEL_COLOR, nullptr, 1.0f, PANEL_BORDER, UI_SCALE_FAC, radius);
}

void draw_centered_text(const char *text,
                        const float center_x,
                        const float baseline_y,
                        const float size,
                        const float color[4])
{
  const int font_id = BLF_default();
  BLF_size(font_id, size);
  BLF_color4fv(font_id, color);
  const float width = BLF_width(font_id, text, strlen(text));
  BLF_position(font_id, center_x - width * 0.5f, baseline_y, 0.0f);
  BLF_draw(font_id, text, strlen(text));
}

uiBut *operator_button(uiBlock *block,
                       const char *operator_id,
                       const int icon,
                       const char *label,
                       const int x,
                       const int y,
                       const int width,
                       const int height,
                       const char *tooltip)
{
  if (label && label[0]) {
    return uiDefIconTextButO(block,
                             ButType::But,
                             operator_id,
                             blender::wm::OpCallContext::InvokeRegionWin,
                             icon,
                             label,
                             x,
                             y,
                             width,
                             height,
                             tooltip);
  }
  return uiDefIconButO(block,
                       ButType::But,
                       operator_id,
                       blender::wm::OpCallContext::InvokeRegionWin,
                       icon,
                       x,
                       y,
                       width,
                       height,
                       tooltip);
}

void disable_button(uiBut *button, const bool disabled)
{
  if (disabled && button) {
    UI_but_flag_enable(button, UI_BUT_DISABLED);
  }
}

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

const char *fov_name(const int degrees)
{
  if (degrees < 23) {
    return "Ultra Narrow";
  }
  if (degrees < 38) {
    return "Narrow";
  }
  if (degrees < 53) {
    return "Standard";
  }
  if (degrees < 68) {
    return "Wide";
  }
  if (degrees < 83) {
    return "Ultra Wide";
  }
  return "Extreme";
}

void camera_lens_label(const View3D *v3d, char *label, const int label_size)
{
  const Object *object = v3d ? v3d->camera : nullptr;
  const Camera *camera = object && object->type == OB_CAMERA ?
                             static_cast<const Camera *>(object->data) :
                             nullptr;
  if (!camera || camera->type != CAM_PERSP) {
    BLI_strncpy(
        label, camera && camera->type == CAM_ORTHO ? "Orthographic" : "Camera Lens", label_size);
    return;
  }
  const float sensor = BKE_camera_sensor_size(
      camera->sensor_fit, camera->sensor_x, camera->sensor_y);
  const int degrees = int(std::round(RAD2DEGF(focallength_to_fov(camera->lens, sensor))));
  BLI_snprintf(label, label_size, "%s  %d°  ▾", fov_name(degrees), degrees);
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

void draw_camera_frame_controls(uiBlock *block,
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

  uiBut *lens = operator_button(block,
                                "MIXAR_OT_director_show_fov_presets",
                                ICON_CAMERA_DATA,
                                lens_label,
                                left,
                                top,
                                lens_w,
                                button_h,
                                "Choose a director-facing field of view");
  disable_button(lens, state.locked);

  uiBut *navigate = operator_button(block,
                                    "MIXAR_OT_director_navigate",
                                    ICON_VIEW_PAN,
                                    compact_navigation ? "" : "Navigate",
                                    left,
                                    bottom,
                                    navigation_button_w,
                                    button_h,
                                    "Navigate with WASD and mouse");
  uiBut *precise = operator_button(block,
                                   "MIXAR_OT_director_precise",
                                   ICON_ORIENTATION_GIMBAL,
                                   compact_navigation ? "" : "Precise",
                                   left + navigation_button_w + gap,
                                   bottom,
                                   navigation_button_w,
                                   button_h,
                                   "Fine-tune with native camera gizmos");
  UI_but_flag_enable(state.navigate_mode ? navigate : precise, UI_BUT_ACTIVE_DEFAULT);
  disable_button(navigate, state.locked);
  disable_button(precise, state.locked);

  uiBut *aspect = operator_button(block,
                                  "MIXAR_OT_director_show_aspect_presets",
                                  ICON_IMAGE_PLANE,
                                  aspect_label,
                                  right - aspect_w,
                                  bottom,
                                  aspect_w,
                                  button_h,
                                  "Choose the shot output aspect ratio");
  disable_button(aspect, state.locked);

  const float dot_size = std::max(7.0f, 8.0f * UI_SCALE_FAC);
  const rctf active_dot = {border.xmax - inset - dot_size,
                           border.xmax - inset,
                           border.ymax - inset - dot_size,
                           border.ymax - inset};
  const float active_color[4] = {0.25f, 0.92f, 0.52f, 1.0f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&active_dot, true, dot_size * 0.5f, active_color);
}

void draw_tool_rail(uiBlock *block,
                    const bContext *C,
                    const ARegion *region,
                    const DirectorViewState &state,
                    const int unit,
                    const int gap)
{
  struct Tool {
    const char *operator_id;
    int icon;
    const char *tooltip;
  };
  /* The rail follows the active object: a camera shows framing/navigation
   * tools, a character shows the animation presets instead. */
  const Object *active = CTX_data_active_object(C);
  const bool character = active && active->type != OB_CAMERA;
  const Tool camera_tools[] = {
      {"MIXAR_OT_director_show_shots", ICON_CAMERA_DATA, "Shots and takes"},
      {"MIXAR_OT_director_navigate", ICON_VIEW_PAN, "Navigate with WASD and mouse"},
      {"MIXAR_OT_director_precise", ICON_ORIENTATION_GIMBAL, "Fine-tune with camera gizmos"},
      {"MIXAR_OT_director_show_camera", ICON_VIEW_CAMERA, "Framing, lens, timing, and direction"},
  };
  const Tool character_tools[] = {
      {"MIXAR_OT_director_show_shots", ICON_CAMERA_DATA, "Shots and takes"},
      {"MIXAR_OT_director_show_animation", ICON_ARMATURE_DATA, "Animation presets"},
  };
  const Tool *tools = character ? character_tools : camera_tools;
  const int button_count = character ? 2 : 4;

  const int rail_w = unit * 2 + gap * 2;
  const int rail_h = button_count * unit * 2 + gap * (button_count + 1);
  const int rail_x = gap * 2;
  const int rail_y = std::max((region->winy - rail_h) / 2, gap * 3);
  draw_panel({float(rail_x), float(rail_x + rail_w), float(rail_y), float(rail_y + rail_h)},
             float(rail_w) * 0.5f);

  int y = rail_y + rail_h - gap - unit * 2;
  for (int index = 0; index < button_count; index++, y -= unit * 2 + gap) {
    uiBut *button = operator_button(block,
                                    tools[index].operator_id,
                                    tools[index].icon,
                                    "",
                                    rail_x + gap,
                                    y,
                                    unit * 2,
                                    unit * 2,
                                    tools[index].tooltip);
    if (!character && ((index == 1 && state.navigate_mode) ||
                       (index == 2 && !state.navigate_mode)))
    {
      UI_but_flag_enable(button, UI_BUT_ACTIVE_DEFAULT);
    }
    disable_button(button, !character && index > 0 && (!state.has_camera || state.locked));
  }
}

void draw_empty_state(uiBlock *block, const ARegion *region, const int unit, const int gap)
{
  const int panel_w = std::min(unit * 22, region->winx - gap * 12);
  const int panel_h = unit * 8;
  const int x = (region->winx - panel_w) / 2;
  const int y = (region->winy - panel_h) / 2;
  draw_panel({float(x), float(x + panel_w), float(y), float(y + panel_h)}, 16.0f * UI_SCALE_FAC);

  const float white[4] = {0.96f, 0.96f, 0.98f, 1.0f};
  draw_centered_text("Direct your first camera shot",
                     float(region->winx) * 0.5f,
                     float(y + panel_h - unit * 2),
                     18.0f * UI_SCALE_FAC,
                     white);
  draw_centered_text(
      "Explore the scene, frame a moment, then capture only the "
      "keyframes that matter.",
      float(region->winx) * 0.5f,
      float(y + panel_h - unit * 4),
      12.0f * UI_SCALE_FAC,
      TEXT_MUTED);
  operator_button(block,
                  "MIXAR_OT_director_start",
                  ICON_VIEW_CAMERA,
                  "Create Camera & Direct",
                  x + (panel_w - unit * 10) / 2,
                  y + gap * 2,
                  unit * 10,
                  unit * 2,
                  "Create a camera aligned to this view and start directing");
}

void draw_context_actions(uiBlock *block,
                          const ARegion *region,
                          const DirectorViewState &state,
                          const int unit,
                          const int gap)
{
  if (state.has_shot) {
    const int action_w = unit * 8;
    const int action_x = (region->winx - action_w) / 2;
    /* Keep the primary action in the top safe area, above the camera gate. */
    const int action_y = region->winy - unit * 2 - gap * 2;
    const char *operator_id = state.locked ? "MIXAR_OT_director_new_take" :
                                             "MIXAR_OT_director_capture_beat";
    const int icon = state.locked ? ICON_DUPLICATE : ICON_KEYFRAME_HLT;
    const char *label = state.locked ? "Start New Take" : "Capture Keyframe";
    operator_button(block,
                    operator_id,
                    icon,
                    label,
                    action_x,
                    action_y,
                    action_w,
                    unit * 2,
                    state.locked ? "Create an editable child of this locked take" :
                                   "Key this camera pose and capture its reference frame (F)");
  }

  if (!state.timeline_expanded) {
    operator_button(block,
                    "MIXAR_OT_director_toggle_timeline",
                    ICON_TIME,
                    "Timeline",
                    (region->winx - unit * 7) / 2,
                    gap * 2,
                    unit * 7,
                    unit * 2,
                    "Expand the shot timeline");
  }

  if (!state.beats.is_empty()) {
    operator_button(block,
                    "MIXAR_OT_director_show_render",
                    ICON_RENDER_ANIMATION,
                    "Shot Renders",
                    region->winx - unit * 24 - gap * 4,
                    gap * 2,
                    unit * 8,
                    unit * 2,
                    "Render Beauty Preview, Clay, or Depth videos to Moodboard");
    operator_button(block,
                    "MIXAR_OT_director_send_keyframes",
                    ICON_EXPORT,
                    "Moodboard",
                    region->winx - unit * 16 - gap * 3,
                    gap * 2,
                    unit * 8,
                    unit * 2,
                    "Group this shot's keyframes on the Moodboard");
    operator_button(block,
                    "MIXAR_OT_director_send_video",
                    ICON_FILE_MOVIE,
                    "Video Gen",
                    region->winx - unit * 8 - gap * 2,
                    gap * 2,
                    unit * 8,
                    unit * 2,
                    "Use these ordered keyframes in Video Gen");
  }
}

}  // namespace

void view3d_director_overlay_draw(const bContext *C, ARegion *region)
{
  DirectorViewState state;
  if (!view3d_director_state_read(CTX_data_scene(C), &state) || !state.active) {
    return;
  }

  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);

  const int unit = std::max(18, int(20.0f * UI_SCALE_FAC));
  const int gap = std::max(4, int(6.0f * UI_SCALE_FAC));
  uiBlock *block = UI_block_begin(
      C, region, "mixar_director_overlay", blender::ui::EmbossType::Emboss);
  UI_block_theme_style_set(block, UI_BLOCK_THEME_STYLE_POPUP);

  draw_camera_frame_controls(block, C, region, state, unit, gap);
  if (region->winy > unit * 18) {
    draw_tool_rail(block, C, region, state, unit, gap);
  }
  if (!state.has_shot) {
    draw_empty_state(block, region, unit, gap);
  }
  draw_context_actions(block, region, state, unit, gap);

  UI_block_end(C, block);
  UI_block_draw(C, block);
  GPU_blend(GPU_BLEND_NONE);
}
