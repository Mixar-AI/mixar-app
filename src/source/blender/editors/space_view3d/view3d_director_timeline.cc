/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Poll-driven native camera-beat timeline dock for Director mode.
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_string.h"

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

#include "view3d_director.hh"

namespace {

constexpr float DOCK_BG[4] = {0.038f, 0.041f, 0.048f, 1.0f};
constexpr float PANEL_BG[4] = {0.065f, 0.068f, 0.078f, 1.0f};
constexpr float PANEL_BORDER[4] = {0.23f, 0.24f, 0.28f, 1.0f};
constexpr float TRACK_COLOR[4] = {0.36f, 0.37f, 0.42f, 1.0f};
constexpr float MUTED_COLOR[4] = {0.61f, 0.62f, 0.67f, 1.0f};
constexpr float PLAYHEAD_COLOR[4] = {0.62f, 0.82f, 1.0f, 1.0f};
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

void draw_text(
    const char *text, const float x, const float y, const float size, const float color[4])
{
  const int font = BLF_default();
  BLF_size(font, size);
  BLF_color4fv(font, color);
  BLF_position(font, x, y, 0.0f);
  BLF_draw(font, text, strlen(text));
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
                                    "Previous camera beat");
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
                                "Next camera beat");
  const bool no_beats = state.beats.is_empty();
  disable_button(previous, no_beats);
  disable_button(play, state.beats.size() < 2 || state.frame_end <= state.frame_start);
  disable_button(next, no_beats);
}

void draw_control_row(uiBlock *block,
                      const bContext *C,
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
  PointerRNA shot_ptr;
  PropertyRNA *camera_prop = nullptr;
  if (state.has_shot && view3d_director_active_shot_pointer(CTX_data_scene(C), &shot_ptr) &&
      (camera_prop = RNA_struct_find_property(&shot_ptr, "camera")))
  {
    uiBut *camera = uiDefAutoButR(
        block, &shot_ptr, camera_prop, -1, "", ICON_CAMERA_DATA, x, y, camera_w, button_h);
    disable_button(camera, state.locked);
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

  uiBut *navigate = operator_button(block,
                                    "MIXAR_OT_director_navigate",
                                    ICON_VIEW_PAN,
                                    compact ? "" : "Navigate",
                                    x,
                                    y,
                                    compact ? button_h : unit * 5,
                                    button_h,
                                    "Navigate with WASD and mouse");
  if (state.navigate_mode) {
    UI_but_flag_enable(navigate, UI_BUT_ACTIVE_DEFAULT);
  }
  x += (compact ? button_h : unit * 5) + gap;
  uiBut *precise = operator_button(block,
                                   "MIXAR_OT_director_precise",
                                   ICON_ORIENTATION_GIMBAL,
                                   compact ? "" : "Precise",
                                   x,
                                   y,
                                   compact ? button_h : unit * 4,
                                   button_h,
                                   "Fine-tune the camera with native gizmos");
  if (!state.navigate_mode) {
    UI_but_flag_enable(precise, UI_BUT_ACTIVE_DEFAULT);
  }
  disable_button(navigate, !state.has_camera || state.locked);
  disable_button(precise, !state.has_camera || state.locked);

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
                    "MIXAR_OT_director_send_video",
                    ICON_FILE_MOVIE,
                    compact ? "" : "Send to Video",
                    right - (compact ? button_h : unit * 7),
                    y,
                    compact ? button_h : unit * 7,
                    button_h,
                    "Use the ordered camera beats in Video Gen");
    right -= (compact ? button_h : unit * 7) + gap;
  }
  uiBut *capture = operator_button(
      block,
      state.locked ? "MIXAR_OT_director_new_take" : "MIXAR_OT_director_capture_beat",
      state.locked ? ICON_DUPLICATE : ICON_KEYFRAME_HLT,
      compact ? "" : (state.locked ? "New Take" : "Add Beat"),
      right - (compact ? button_h : unit * 6),
      y,
      compact ? button_h : unit * 6,
      button_h,
      state.locked ? "Start an editable child take" : "Capture the live camera pose (F)");
  disable_button(capture, !state.has_camera);
}

void draw_timeline(uiBlock *block,
                   const ARegion *region,
                   const DirectorViewState &state,
                   const int margin,
                   const int unit)
{
  const float x_start = float(margin + unit);
  const float x_end = float(region->winx - margin - unit);
  const float y = float(margin + unit * 2);
  const int default_span = std::max(1, int(std::round(state.fps * 10.0f)));
  const int frame_start = state.frame_start;
  const bool has_shot_span = state.beats.size() >= 2 && state.frame_end > frame_start;
  const int frame_end = has_shot_span ? state.frame_end : frame_start + default_span;
  const float span = float(std::max(frame_end - frame_start, 1));
  const auto frame_x = [&](const int frame) {
    const float t = std::clamp(float(frame - frame_start) / span, 0.0f, 1.0f);
    return x_start + t * (x_end - x_start);
  };

  draw_rect(x_start, y, x_end, y + UI_SCALE_FAC, TRACK_COLOR);
  const int tick_count = 10;
  for (int tick = 0; tick <= tick_count; tick++) {
    const float t = float(tick) / float(tick_count);
    const float x = x_start + t * (x_end - x_start);
    draw_rect(x, y - 4.0f * UI_SCALE_FAC, x + UI_SCALE_FAC, y + 5.0f * UI_SCALE_FAC, TRACK_COLOR);
    char label[32];
    const float seconds = (span * t) / std::max(state.fps, 0.001f);
    BLI_snprintf(label, sizeof(label), "%.0fs", seconds);
    draw_text(label,
              x - 7.0f * UI_SCALE_FAC,
              y + 9.0f * UI_SCALE_FAC,
              10.0f * UI_SCALE_FAC,
              MUTED_COLOR);
  }

  for (const DirectorBeatView &beat : state.beats) {
    const int size = std::max(16, int(18.0f * UI_SCALE_FAC));
    const int x = int(frame_x(beat.frame)) - size / 2;
    uiBut *marker = operator_button(block,
                                    "MIXAR_OT_director_jump_beat",
                                    ICON_KEYTYPE_KEYFRAME_VEC,
                                    "",
                                    x,
                                    int(y) - size / 2,
                                    size,
                                    size,
                                    "View this camera beat");
    PointerRNA *operator_ptr = UI_but_operator_ptr_ensure(marker);
    RNA_int_set(operator_ptr, "index", beat.index);
    if (beat.index == state.active_beat_index) {
      UI_but_flag_enable(marker, UI_BUT_ACTIVE_DEFAULT);
    }
  }

  const float playhead_x = frame_x(state.frame_current);
  draw_rect(playhead_x, float(margin), playhead_x + UI_SCALE_FAC, y + unit * 2.0f, PLAYHEAD_COLOR);
  char frame_label[32];
  BLI_snprintf(frame_label, sizeof(frame_label), "F%d", state.frame_current);
  draw_text(frame_label,
            playhead_x + 5.0f * UI_SCALE_FAC,
            float(margin),
            10.0f * UI_SCALE_FAC,
            PLAYHEAD_COLOR);
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
  draw_control_row(block, C, region, state, playing, margin, unit, gap);
  draw_timeline(block, region, state, margin, unit);
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
  art->draw = director_timeline_draw;
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
