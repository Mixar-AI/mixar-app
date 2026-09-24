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

#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "ED_screen.hh"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_cinema_phone.hh"
#include "view3d_director_minimap.hh"
#include "view3d_director_overlay_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

constexpr float PANEL_BORDER[4] = {0.28f, 0.29f, 0.33f, 0.8f};
constexpr float TEXT_MUTED[4] = {0.70f, 0.71f, 0.75f, 1.0f};

void draw_tool_rail(ui::Block *block,
                    const bContext *C,
                    const ARegion *region,
                    const DirectorViewState &state,
                    const int unit,
                    const int gap)
{
  struct Tool {
    ui::BlockCreateFunc block_func;
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
  /* Centred when it fits; otherwise TOP-aligned, because a rail centred on
   * a region shorter than itself runs off both ends and the first tool — the
   * one the mode is about — goes off the top. */
  const int rail_y = rail_h + gap * 3 <= region->winy ? (region->winy - rail_h) / 2 :
                                                        region->winy - rail_h - gap * 2;

  int y = rail_y + rail_h - unit * 2;
  for (int index = 0; index < button_count; index++) {
    if (tools[index].group_above) {
      y -= group_gap;
    }
    ui::Button *button = ui::uiDefIconBlockBut(block,
                                      tools[index].block_func,
                                      nullptr,
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

  /* Through the surface's own painter: centred on the line rather than on a
   * baseline the caller guesses, and MEASURED — the blurb is a full sentence
   * at 12 px and used to run out of a panel this narrow. */
  const float white[4] = {0.96f, 0.96f, 0.98f, 1.0f};
  const float text_w = float(panel_w) - float(gap) * 4.0f;
  cinema_text_center_fitted("Direct your first camera shot",
                            float(x + panel_w / 2),
                            float(y + panel_h - unit * 2),
                            18.0f * UI_SCALE_FAC,
                            text_w,
                            white);
  cinema_text_center_fitted("Explore the scene, frame a moment, then capture only the "
                            "keyframes that matter.",
                            float(x + panel_w / 2),
                            float(y + panel_h - unit * 4),
                            12.0f * UI_SCALE_FAC,
                            text_w,
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
                          const bContext *C,
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
                       "Key this camera pose and capture its reference frame (I)");
    Scene *scene = CTX_data_scene(const_cast<bContext *>(C));
    if (!state.locked && scene != nullptr) {
      /* Blender's own Auto Keying toggle, as on the dock: an RNA toggle on
       * the property the Timeline's record button flips, drawn with the
       * glyph that button uses (RECORD_OFF, RECORD_ON when armed). */
      PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
      PointerRNA tool_settings_ptr = RNA_pointer_get(&scene_ptr, "tool_settings");
      uiDefIconButR(block,
                    ui::ButtonType::Toggle,
                    state.auto_key ? ICON_RECORD_ON : ICON_RECORD_OFF,
                    action_x + action_w + gap,
                    action_y,
                    short(unit * 2),
                    short(unit * 2),
                    &tool_settings_ptr,
                    "use_keyframe_insert_auto",
                    0,
                    0.0f,
                    0.0f,
                    state.auto_key ? "Auto Keying is on (the Timeline's record button)" :
                                     "Auto Keying (the Timeline's record button): key the "
                                     "camera automatically after every move");
    }
  }

  /* The bottom row, left and right. Both are anchored to their own corner,
   * and on a viewport too narrow to hold the pair the EXPORT gives way — the
   * timeline chip is the only way back to the dock, so it is the one that
   * cannot be dropped. */
  const int timeline_w = unit * 7;
  const int export_w = unit * 11;
  const bool bottom_row_fits = region->winx > timeline_w + export_w + gap * 6;
  if (!state.timeline_expanded) {
    /* Bottom-left corner: centering collided with the right-anchored
     * Export to Moodboard button on narrow viewports. */
    director_overlay_operator_button(block,
                                     "MIXAR_OT_director_toggle_timeline",
                                     ICON_TIME,
                                     "Timeline",
                                     gap * 2,
                                     gap * 2,
                                     timeline_w,
                                     unit * 2,
                                     "Expand the shot timeline");
  }

  if (!state.beats.is_empty() && (bottom_row_fits || state.timeline_expanded)) {
    /* One combined export menu: keyframe stills and rendered Beauty/Clay/Depth
     * guides both reach the Moodboard from here. A native block popup like the
     * lens dropdown — the Python popover looked foreign over the calm surface.
     * Video Gen was removed from this cluster. */
    ui::uiDefBlockBut(block,
                  view3d_director_render_popup_create,
                  nullptr,
                  "Export to Moodboard",
                  region->winx - export_w - gap * 2,
                  gap * 2,
                  short(export_w),
                  short(unit * 2),
                  "Export keyframes and rendered guides to the Moodboard");
  }
}

}  // namespace

void director_overlay_panel_draw(const rctf &rect, const float radius)
{
  cinema_glass_panel(rect, radius);
  cinema_outline(rect, radius, PANEL_BORDER, UI_SCALE_FAC);
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
  ui::Button *button;
  if (label && label[0]) {
    button = ui::uiDefIconTextButO(block,
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
  else {
    button = ui::uiDefIconButO(block,
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
  ui::mixar_style_button(button, ui::MixarComponent::Action, ui::MixarVariant::Secondary);
  return button;
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
    cinema_release_chat_seat(C);
    /* Director left: the aerial map's render buffers go with it (a GPU
     * context is bound here), and its click transform must not outlive the
     * card. Owner-guarded so another viewport's draw never frees them. */
    view3d_director_minimap_release(region, /*free_gpu=*/true);
    /* Same rule for the camera list's published rect: a poll must never be
     * answered by a card that is no longer on screen — and for the gate's
     * remembered fit, which is keyed on this region's pointer. */
    cinema_camera_list_release(region);
    cinema_gate_release(region);
    return;
  }

  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);
  cinema_unit_begin(region);
  /* Records from a previous wide draw must not outlive a compact one. */
  cinema_qa_begin(region);

  const int unit = std::max(18, int(20.0f * UI_SCALE_FAC));
  const int gap = std::max(4, int(6.0f * UI_SCALE_FAC));
  ui::Block *block = ui::block_begin(
      C, region, "mixar_director_overlay", blender::ui::EmbossType::Emboss);
  ui::block_theme_style_set(block, ui::BLOCK_THEME_STYLE_POPUP);
  /* The popups opened from here are settings panels that stay open: each
   * re-lays itself after a row runs, so a new choice shows at once. */
  ui::block_flag_enable(block, ui::BLOCK_MIXAR_POPUPS_REFRESH);

  /* Cinema Mode surface (the designed shell): a top strip and two anchored
   * columns replace the old floating rail and its popovers. The rail's
   * content did not disappear — the lens/aspect/moves/export popups are the
   * same native blocks, now opened from named rows instead of icon buttons.
   *
   * Needs room for both columns plus the gate between them; below that the
   * old compact controls are still the honest fallback. */
  if (cinema_surface_fits(region)) {
    /* No empty-state card here: it would sit on top of the two columns, and
     * the right column's own "+ Add Camera" is the same first action. The
     * camera gate is the frame: fitted to the stage, no chrome around it. */
    cinema_fit_camera_gate(C, region);
    cinema_draw_top_strip(block, C, region, state);
    cinema_draw_left_panel(block, C, region, state);
    cinema_draw_right_panel(block, C, region, state);
    /* Last, so the pairing card sits above both columns and the gate. */
    cinema_draw_phone_card(block, C, region);
  }
  else {
    cinema_release_chat_seat(C);
    /* Compact rail: no card, so no click target — but keep the render
     * cached, a second viewport below the fit gate must not thrash it. */
    view3d_director_minimap_release(region, /*free_gpu=*/false);
    cinema_camera_list_release(region);
    /* The rail draws no gate, so the wide layout must refit when it returns. */
    cinema_gate_release(region);
    view3d_director_frame_controls_draw(block, C, region, state, unit, gap);
    if (region->winy > unit * 18) {
      draw_tool_rail(block, C, region, state, unit, gap);
    }
    if (!state.has_shot) {
      draw_empty_state(block, region, unit, gap);
    }
    draw_context_actions(block, C, region, state, unit, gap);
  }

  ui::block_end(C, block);
  ui::block_draw(C, block);
  GPU_blend(GPU_BLEND_NONE);
}
}  // namespace blender
