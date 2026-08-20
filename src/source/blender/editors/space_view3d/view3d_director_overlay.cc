/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Floating Flow-inspired controls over the Director camera viewport.
 */

#include <algorithm>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_object_types.h"

#include "ED_screen.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

constexpr float PANEL_COLOR[4] = {0.055f, 0.058f, 0.066f, 0.94f};
constexpr float PANEL_BORDER[4] = {0.28f, 0.29f, 0.33f, 0.8f};
constexpr float TEXT_MUTED[4] = {0.70f, 0.71f, 0.75f, 1.0f};

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

void draw_tool_rail(ui::Block *block,
                    const bContext *C,
                    const ARegion *region,
                    const DirectorViewState &state,
                    const int unit,
                    const int gap)
{
  struct Tool {
    uiBlockCreateFunc block_func;
    int icon;
    const char *tooltip;
    bool group_above;
  };
  /* Camera tools are the mode's backbone and never hide — selection must
   * not be load-bearing (in camera view the camera is only clickable via
   * its gate rim, an obscure trick). Selecting a character ADDS the
   * animation tool instead of swapping the rail. Navigate/Precise live on
   * the camera gate and the timeline dock, deliberately NOT here — each
   * control has one home. Buttons float like the native navigation gizmos
   * on the opposite edge — no container panel, so their own emboss is the
   * only rectangle; groups read through wider spacing. */
  const Object *active = CTX_data_active_object(C);
  const bool character = active && active->type != OB_CAMERA;
  const Tool tools[] = {
      {view3d_director_shots_popup_create, ICON_CAMERA_DATA, "Shots and takes", false},
      {view3d_director_moves_popup_create,
       ICON_CON_CAMERASOLVER,
       "One-click camera moves, timing, and handheld",
       true},
      {view3d_director_camera_popup_create,
       ICON_VIEW_CAMERA,
       "Direction, adherence, timing, and guides",
       false},
      {view3d_director_animation_popup_create,
       ICON_ARMATURE_DATA,
       "Animation presets for the selected character",
       true},
  };
  const int button_count = character ? 4 : 3;
  const int group_gap = gap * 3;
  int group_count = 0;
  for (int index = 0; index < button_count; index++) {
    group_count += int(tools[index].group_above);
  }

  const int slot = unit * 2 + gap;
  const int rail_h = button_count * slot - gap + group_count * group_gap;
  const int rail_x = gap * 2;
  const int rail_y = std::max((region->winy - rail_h) / 2, gap * 3);

  int y = rail_y + rail_h - unit * 2;
  for (int index = 0; index < button_count; index++) {
    if (tools[index].group_above) {
      y -= group_gap;
    }
    ui::Button *button = ui::uiDefIconBlockBut(block,
                                      tools[index].block_func,
                                      nullptr,
                                      0,
                                      tools[index].icon,
                                      rail_x,
                                      y,
                                      short(unit * 2),
                                      short(unit * 2),
                                      tools[index].tooltip);
    /* Moves needs an editable camera; Shots/Camera/Animation always open. */
    director_overlay_disable_button(button,
                                    index == 1 && (!state.has_camera || state.locked));
    y -= slot;
  }
}

void draw_empty_state(ui::Block *block, const ARegion *region, const int unit, const int gap)
{
  const int panel_w = std::min(unit * 22, region->winx - gap * 12);
  const int panel_h = unit * 8;
  const int x = (region->winx - panel_w) / 2;
  const int y = (region->winy - panel_h) / 2;
  director_overlay_panel_draw(
      {float(x), float(x + panel_w), float(y), float(y + panel_h)}, 16.0f * UI_SCALE_FAC);

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
  director_overlay_operator_button(block,
                                   "MIXAR_OT_director_start",
                                   ICON_VIEW_CAMERA,
                                   "Create Camera & Direct",
                                   x + (panel_w - unit * 10) / 2,
                                   y + gap * 2,
                                   unit * 10,
                                   unit * 2,
                                   "Create a camera aligned to this view and start directing");
}

void draw_context_actions(ui::Block *block,
                          const ARegion *region,
                          const DirectorViewState &state,
                          const int unit,
                          const int gap)
{
  if (state.has_shot && state.explore_mode) {
    /* Free-fly exploration: the shot camera is parked, so capturing makes no
     * sense — the primary action is planting a new shot camera at this view,
     * which is how directors cover ground inside imported worlds. */
    const int action_w = unit * 9;
    const int action_x = (region->winx - action_w) / 2;
    const int action_y = region->winy - unit * 2 - gap * 2;
    director_overlay_operator_button(block,
                                     "MIXAR_OT_director_new_shot",
                                     ICON_ADD,
                                     "Add Camera Here",
                                     action_x,
                                     action_y,
                                     action_w,
                                     unit * 2,
                                     "Create a new shot camera exactly at this view");
    director_overlay_operator_button(block,
                                     "MIXAR_OT_director_return_to_shot",
                                     ICON_LOOP_BACK,
                                     "",
                                     action_x + action_w + gap,
                                     action_y,
                                     unit * 2,
                                     unit * 2,
                                     "Back to the active shot camera without adding");
  }
  else if (state.has_shot) {
    const int action_w = unit * 8;
    const int action_x = (region->winx - action_w) / 2;
    /* Keep the primary action in the top safe area, above the camera gate. */
    const int action_y = region->winy - unit * 2 - gap * 2;
    const char *operator_id = state.locked ? "MIXAR_OT_director_new_take" :
                                             "MIXAR_OT_director_capture_beat";
    const int icon = state.locked ? ICON_DUPLICATE : ICON_KEYFRAME_HLT;
    const char *label = state.locked ? "Start New Take" : "Capture Keyframe";
    director_overlay_operator_button(
        block,
        operator_id,
        icon,
        label,
        action_x,
        action_y,
        action_w,
        unit * 2,
        state.locked ? "Create an editable child of this locked take" :
                       "Key this camera pose and capture its reference frame (F)");
    if (!state.locked) {
      /* Blender's timeline auto-key flips RECORD_OFF to RECORD_ON when armed
       * (rna_scene.cc ui_icon); mirror that instead of a static REC glyph. */
      ui::Button *auto_key = director_overlay_operator_button(
          block,
          "MIXAR_OT_director_toggle_auto_key",
          state.auto_key ? ICON_RECORD_ON : ICON_RECORD_OFF,
          "",
          action_x + action_w + gap,
          action_y,
          unit * 2,
          unit * 2,
          "Auto Key: capture a keyframe automatically after every camera move");
      if (state.auto_key) {
        ui::button_flag_enable(auto_key, ui::BUT_ACTIVE_DEFAULT);
      }
    }
  }

  if (!state.timeline_expanded) {
    /* Bottom-left corner: centering collided with the right-anchored
     * Export to Moodboard button on narrow viewports. */
    director_overlay_operator_button(block,
                                     "MIXAR_OT_director_toggle_timeline",
                                     ICON_TIME,
                                     "Timeline",
                                     gap * 2,
                                     gap * 2,
                                     unit * 7,
                                     unit * 2,
                                     "Expand the shot timeline");
  }

  if (!state.beats.is_empty()) {
    /* One combined export menu: keyframe stills and rendered Beauty/Clay/Depth
     * guides both reach the Moodboard from here. A native block popup like the
     * lens dropdown — the Python popover looked foreign over the calm surface.
     * Video Gen was removed from this cluster. */
    ui::uiDefBlockBut(block,
                  view3d_director_render_popup_create,
                  nullptr,
                  "Export to Moodboard",
                  region->winx - unit * 11 - gap * 2,
                  gap * 2,
                  short(unit * 11),
                  short(unit * 2),
                  "Export keyframes and rendered guides to the Moodboard");
  }
}

}  // namespace

void director_overlay_panel_draw(const rctf &rect, const float radius)
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv_ex(&rect, PANEL_COLOR, nullptr, 1.0f, PANEL_BORDER, UI_SCALE_FAC, radius);
}

ui::Button *director_overlay_operator_button(ui::Block *block,
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
    return ui::uiDefIconTextButO(block,
                             ui::ButtonType::But,
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
  return ui::uiDefIconButO(block,
                       ui::ButtonType::But,
                       operator_id,
                       blender::wm::OpCallContext::InvokeRegionWin,
                       icon,
                       x,
                       y,
                       width,
                       height,
                       tooltip);
}

void director_overlay_disable_button(ui::Button *button, const bool disabled)
{
  if (disabled && button) {
    ui::button_flag_enable(button, ui::BUT_DISABLED);
  }
}

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
  ui::Block *block = ui::block_begin(
      C, region, "mixar_director_overlay", blender::ui::EmbossType::Emboss);
  ui::block_theme_style_set(block, ui::BLOCK_THEME_STYLE_POPUP);

  view3d_director_frame_controls_draw(block, C, region, state, unit, gap);
  if (region->winy > unit * 18) {
    draw_tool_rail(block, C, region, state, unit, gap);
  }
  if (!state.has_shot) {
    draw_empty_state(block, region, unit, gap);
  }
  draw_context_actions(block, region, state, unit, gap);

  ui::block_end(C, block);
  ui::block_draw(C, block);
  GPU_blend(GPU_BLEND_NONE);
}
}  // namespace blender
