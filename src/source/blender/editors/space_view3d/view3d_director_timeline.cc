/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Poll-driven native keyframe timeline dock for Director mode.
 */

#include <algorithm>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_rect.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_immediate_util.hh"
#include "GPU_shader_shared_utils.hh"
#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_director_timeline.hh"

namespace {

constexpr float DOCK_BG[4] = {0.105f, 0.108f, 0.115f, 1.0f};
constexpr float PANEL_BG[4] = {0.195f, 0.195f, 0.195f, 1.0f};
constexpr float PANEL_BORDER[4] = {0.27f, 0.27f, 0.28f, 1.0f};
constexpr double PLAYBACK_REDRAW_INTERVAL = 1.0 / 30.0;

wmTimer *g_playback_redraw_timer = nullptr;

void playback_redraw_timer_update(const bContext *C, const bool enabled)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  if (enabled) {
    if (!g_playback_redraw_timer && CTX_wm_window(C)) {
      g_playback_redraw_timer = WM_event_timer_add_notifier(
          wm, CTX_wm_window(C), NC_SPACE | ND_SPACE_VIEW3D, PLAYBACK_REDRAW_INTERVAL);
    }
  }
  else if (g_playback_redraw_timer) {
    WM_event_timer_remove(wm, nullptr, g_playback_redraw_timer);
    g_playback_redraw_timer = nullptr;
  }
}

void draw_rect(
    const float x1, const float y1, const float x2, const float y2, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  immRectf(pos, x1, y1, x2, y2);
  immUnbindProgram();
}

void draw_dock_panel(const ARegion *region, const int margin)
{
  UI_ThemeClearColor(TH_BACK);
  draw_rect(0.0f, 0.0f, float(region->winx), float(region->winy), DOCK_BG);
  const rctf panel = {
      float(margin), float(region->winx - margin), float(margin), float(region->winy - margin)};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv_ex(
      &panel, PANEL_BG, nullptr, 1.0f, PANEL_BORDER, UI_SCALE_FAC, 12.0f * UI_SCALE_FAC);
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
    if (icon == ICON_NONE) {
      return uiDefButO(block,
                       ButType::But,
                       operator_id,
                       blender::wm::OpCallContext::InvokeRegionWin,
                       label,
                       x,
                       y,
                       width,
                       height,
                       tooltip);
    }
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
  if (button && disabled) {
    UI_but_flag_enable(button, UI_BUT_DISABLED);
  }
}

void draw_transport(uiBlock *block,
                    const ARegion *region,
                    const DirectorViewState &state,
                    const bool playing,
                    const int y,
                    const int size,
                    const int gap)
{
  const int group_w = size * 3 + gap * 2;
  int x = (region->winx - group_w) / 2;
  uiBut *previous = operator_button(block,
                                    "MIXAR_OT_director_previous_beat",
                                    ICON_PREV_KEYFRAME,
                                    "",
                                    x,
                                    y,
                                    size,
                                    size,
                                    "Previous keyframe");
  x += size + gap;
  uiBut *play = operator_button(block,
                                "MIXAR_OT_director_preview",
                                playing ? ICON_PAUSE : ICON_PLAY,
                                "",
                                x,
                                y,
                                size,
                                size,
                                playing ? "Pause shot preview" : "Preview this shot");
  x += size + gap;
  uiBut *next = operator_button(block,
                                "MIXAR_OT_director_next_beat",
                                ICON_NEXT_KEYFRAME,
                                "",
                                x,
                                y,
                                size,
                                size,
                                "Next keyframe");
  const bool no_beats = state.beats.is_empty();
  disable_button(previous, no_beats);
  disable_button(play, state.beats.size() < 2 || state.frame_end <= state.frame_start);
  disable_button(next, no_beats);
}

void draw_control_row(uiBlock *block,
                      const ARegion *region,
                      const DirectorViewState &state,
                      const bool playing,
                      const int margin,
                      const int unit,
                      const int gap)
{
  const int y = region->winy - margin - unit * 2 - gap;
  const int button_h = unit * 2;
  const bool compact = region->winx < int(980.0f * UI_SCALE_FAC);
  int x = margin + gap * 2;

  const int camera_w = compact ? button_h : unit * 8;
  if (state.has_shot) {
    /* Switch between per-camera shots (each its own timeline) rather than
     * reassigning one shot's camera, which collapsed every camera onto one
     * strip. Wide shows the active camera's name; compact shows the icon. */
    operator_button(block,
                    "MIXAR_OT_director_pick_camera",
                    ICON_CAMERA_DATA,
                    compact ? "" : state.camera_name.c_str(),
                    x,
                    y,
                    camera_w,
                    button_h,
                    "Switch to another camera or shot");
  }
  else {
    operator_button(block,
                    "MIXAR_OT_director_start",
                    ICON_CAMERA_DATA,
                    compact ? "" : "Create Camera",
                    x,
                    y,
                    camera_w,
                    button_h,
                    "Create a camera and start directing");
  }
  x += camera_w + gap;
  operator_button(block,
                  "MIXAR_OT_director_new_shot",
                  ICON_ADD,
                  "",
                  x,
                  y,
                  button_h,
                  button_h,
                  "Add a new shot camera from this view");
  x += button_h + gap * 2;

  /* Navigate/Precise deliberately removed from the timeline dock — they
   * duplicated the camera-gate controls (artist feedback). They now live only
   * on the live camera gate. Explore keeps its dock home instead: the gate
   * draws only in camera view, so it cannot host a control that is used
   * while free-flying outside the camera. */
  if (state.has_shot) {
    /* Unlike Navigate, Explore works on locked takes: flying the viewport
     * touches no camera, and Add Camera Here starts a fresh shot anyway.
     * That is the escape hatch for huge imported worlds — travel first,
     * then plant a camera where the frame is right. */
    uiBut *explore = operator_button(block,
                                     "MIXAR_OT_director_explore",
                                     ICON_NONE,
                                     "Explore",
                                     x,
                                     y,
                                     unit * 5,
                                     button_h,
                                     "Fly the scene freely without moving the shot camera; "
                                     "Add Camera Here then starts a new shot at that view");
    if (state.explore_mode) {
      UI_but_flag_enable(explore, UI_BUT_ACTIVE_DEFAULT);
    }
  }

  draw_transport(block, region, state, playing, y, button_h, gap);

  int right = region->winx - margin - gap * 2;
  operator_button(block,
                  "MIXAR_OT_director_toggle_timeline",
                  ICON_X,
                  "",
                  right - button_h,
                  y,
                  button_h,
                  button_h,
                  "Collapse timeline");
  right -= button_h + gap;
  operator_button(block,
                  "MIXAR_OT_director_toggle_immersive",
                  ICON_FULLSCREEN_ENTER,
                  "",
                  right - button_h,
                  y,
                  button_h,
                  button_h,
                  "Toggle immersive Director view");
  right -= button_h + gap * 2;

  if (!state.beats.is_empty()) {
    operator_button(block,
                    "MIXAR_OT_director_send_keyframes",
                    ICON_EXPORT,
                    compact ? "" : "Send to Moodboard",
                    right - (compact ? button_h : unit * 7),
                    y,
                    compact ? button_h : unit * 7,
                    button_h,
                    "Group this shot's keyframes on the Moodboard");
    right -= (compact ? button_h : unit * 7) + gap;
  }
  uiBut *capture = operator_button(
      block,
      state.locked ? "MIXAR_OT_director_new_take" : "MIXAR_OT_director_capture_beat",
      state.locked ? ICON_DUPLICATE : ICON_KEYFRAME_HLT,
      compact ? "" : (state.locked ? "New Take" : "Add Keyframe"),
      right - (compact ? button_h : unit * 6),
      y,
      compact ? button_h : unit * 6,
      button_h,
      state.locked ? "Start an editable child take" : "Capture the live camera pose (F)");
  disable_button(capture, !state.has_camera);
}

bool director_timeline_poll(const RegionPollParams *params)
{
  DirectorViewState state;
  const bool visible = view3d_director_state_read(CTX_data_scene(params->context), &state) &&
                       state.active && state.timeline_expanded;
  if (!visible) {
    playback_redraw_timer_update(params->context, false);
  }
  return visible;
}

void director_timeline_draw(const bContext *C, ARegion *region)
{
  DirectorViewState state;
  if (!view3d_director_state_read(CTX_data_scene(C), &state) || !state.active) {
    return;
  }
  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);
  const int margin = std::max(6, int(8.0f * UI_SCALE_FAC));
  const int unit = std::max(18, int(20.0f * UI_SCALE_FAC));
  const int gap = std::max(4, int(5.0f * UI_SCALE_FAC));
  const bool playing = ED_screen_animation_playing(CTX_wm_manager(C)) != nullptr;
  playback_redraw_timer_update(C, playing);
  draw_dock_panel(region, margin);

  uiBlock *block = UI_block_begin(
      C, region, "mixar_director_timeline", blender::ui::EmbossType::Emboss);
  UI_block_theme_style_set(block, UI_BLOCK_THEME_STYLE_POPUP);
  draw_control_row(block, region, state, playing, margin, unit, gap);
  DirectorTimelineRuntime *runtime = view3d_director_timeline_runtime_ensure(region);
  const int content_top = region->winy - margin - unit * 2 - gap * 2;
  view3d_director_timeline_draw_content(region, state, runtime, margin, unit, content_top);
  UI_block_end(C, block);
  UI_block_draw(C, block);
  GPU_blend(GPU_BLEND_NONE);
}

void director_timeline_listener(const wmRegionListenerParams *params)
{
  const wmNotifier *notifier = params->notifier;
  if (ELEM(notifier->category, NC_SCENE, NC_ANIMATION, NC_SPACE) ||
      (notifier->category == NC_SCREEN && notifier->data == ND_ANIMPLAY))
  {
    ED_region_tag_redraw(params->region);
  }
}

}  // namespace

void view3d_director_timeline_region_ensure(ScrArea *area)
{
  if (!area || area->spacetype != SPACE_VIEW3D ||
      BKE_area_find_region_type(area, RGN_TYPE_CHANNELS))
  {
    return;
  }

  /* Builds made before the Director dock used RGN_TYPE_FOOTER, whose height
   * Blender hard-clamps to one header row. Retype a saved legacy region before
   * adding a new one so existing workspaces recover the full timeline. */
  ARegion *region = BKE_area_find_region_type(area, RGN_TYPE_FOOTER);
  if (region) {
    region->regiontype = RGN_TYPE_CHANNELS;
  }
  else {
    region = BKE_area_region_new();
    ARegion *window_region = BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
    if (window_region) {
      BLI_insertlinkbefore(&area->regionbase, window_region, region);
    }
    else {
      BLI_addtail(&area->regionbase, region);
    }
    region->regiontype = RGN_TYPE_CHANNELS;
  }

  /* ED_area_and_region_types_init() has already run when SpaceType.init is
   * called. RGN_TYPE_CHANNELS is intentionally used as an otherwise-unused
   * View3D region type because RGN_TYPE_FOOTER ignores custom heights. */
  region->alignment = RGN_ALIGN_BOTTOM;
  region->sizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;
  region->flag |= RGN_FLAG_TEMP_REGIONDATA | RGN_FLAG_POLL_FAILED;
  /* The normal type-assignment pass preceded this callback. Without this,
   * ED_area_init() dereferences a null runtime type while visiting the newly
   * inserted region. */
  region->runtime->type = BKE_regiontype_from_id(area->type, region->regiontype);
}

void view3d_director_timeline_region_register(SpaceType *st)
{
  ARegionType *art = MEM_callocN<ARegionType>("spacetype view3d director timeline region");
  art->regionid = RGN_TYPE_CHANNELS;
  art->prefsizey = VIEW3D_DIRECTOR_TIMELINE_HEIGHT;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FRAMES;
  art->poll = director_timeline_poll;
  art->init = view3d_director_timeline_region_init;
  art->draw = director_timeline_draw;
  art->free = view3d_director_timeline_region_free;
  art->duplicate = view3d_director_timeline_region_duplicate;
  art->listener = director_timeline_listener;
  BLI_addhead(&st->regiontypes, art);

  /* Keep the old type readable long enough for SpaceType.init to migrate it.
   * Without a registered type, opening a .blend saved by the first Director
   * build would fail before view3d_director_timeline_region_ensure() runs. */
  art = MEM_callocN<ARegionType>("spacetype view3d legacy director timeline region");
  art->regionid = RGN_TYPE_FOOTER;
  art->poll = director_timeline_poll;
  BLI_addhead(&st->regiontypes, art);
}
