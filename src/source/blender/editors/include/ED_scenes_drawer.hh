/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edscr
 *
 * Hit geometry for the Zen Mode Scenes drawer: the mirror image of the
 * moodboard drawer (`ED_moodboard_drawer.hh`), docked to the LEFT edge of the
 * 3D View. Lives in `editors/include` so screen event routing and the View3D
 * drawer share one expression without a screen → space_view3d link.
 *
 * The drawer lists the scene tabs of the parallel-scenes feature (one Blender
 * Scene + one agent chat each). Python owns the list
 * (`wm.mixar_scene_tabs`, `space_mixie_chat/ui/properties/scene_tabs_props.py`);
 * C paints it and turns clicks into the Python scene-tab operators.
 */

#pragma once

#include <cmath>
#include <string>
#include <unordered_map>
#include <vector>

#include "BLI_rect.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

struct GPUOffScreen;
struct GPUViewport;
struct wmTimer;

namespace blender {

/** Region type the Scenes drawer occupies on the 3D View. `TOOL_PROPS` is the
 * moodboard drawer; the navigation bar type is unused by View3D. */
#define VIEW3D_SCENES_DRAWER_REGION_TYPE RGN_TYPE_NAV_BAR

enum class ScenesDrawerTabStatus : int8_t {
  Idle = 0,
  Working = 1,
  Waiting = 2,
  Done = 3,
};

/** One painted scene card, cached by the draw pass for hit tests and QA. All
 * rects are WINDOW pixels, like the grip. */
struct ScenesDrawerCard {
  std::string scene_name;
  std::string session_id;
  std::string last_text;
  ScenesDrawerTabStatus status = ScenesDrawerTabStatus::Idle;
  int workers_done = 0;
  int workers_total = 0;
  bool is_active = false;
  bool attention = false;
  rcti rect = {};
  rcti close_rect = {};
  rcti thumb_rect = {};
};

/** A scene rendered into a small offscreen for its card (see
 * `view3d_scenes_drawer_thumbs.cc`). Owned by the region runtime. */
struct ScenesDrawerThumb {
  GPUOffScreen *offscreen = nullptr;
  GPUViewport *viewport = nullptr;
  bool has_render = false;
  bool render_failed = false;
  uint64_t update_count = 0;
  double last_render_time = 0.0;
  int draw_type = -1;
};

/** Last painted slide and layout, stored on the drawer region's `regiondata`. */
struct ScenesDrawerRuntime {
  float amount = 0.0f;
  /** Wall-clock start of the current ease; 0 while not time-animating. */
  double slide_started_at = 0.0;
  float slide_start_amount = 0.0f;
  /** True while the grip is dragging: update must not start an ease. */
  bool slide_held = false;
  /** TIMERNOTIFIER that tags this region; owned by the window manager. */
  wmTimer *tick_timer = nullptr;
  /** Layout of the last draw pass (window pixels). */
  std::vector<ScenesDrawerCard> cards;
  rcti new_rect = {};
  bool new_visible = false;
  /** Card the pointer rests on (index into `cards`), -1 for none. */
  int hover = -1;
  bool hover_close = false;
  bool hover_new = false;
  /** A card press in flight: the pressed card and, once dragged past the
   * threshold, the slot the pointer is over (an insertion line is drawn). */
  int drag_index = -1;
  int drag_target = -1;
  /** Thumbnails by scene name; entries for scenes no longer listed are freed. */
  std::unordered_map<std::string, ScenesDrawerThumb> thumbs;
};

/** Factory width fallback (unscaled UI units) before the first View3D layout
 * promotes to ``VIEW3D_SCENES_DRAWER_WIDTH_FRACTION``. Keep in lockstep with
 * the Python FloatProperty default on `mixar_scenes_drawer_width`. */
#define VIEW3D_SCENES_DRAWER_WIDTH 300
/** Fraction of the View3D area used on first open. */
#define VIEW3D_SCENES_DRAWER_WIDTH_FRACTION 0.26f
/** Pulls smaller than this settle closed; all larger widths stay put. */
#define VIEW3D_SCENES_DRAWER_MIN_WIDTH 160
/** Clickable/drawn width of the labeled Scenes tab. */
#define VIEW3D_SCENES_DRAWER_GRIP_WIDTH 22.0f
/** Vertical extent of the Scenes tab, centred in the area. */
#define VIEW3D_SCENES_DRAWER_GRIP_HEIGHT 120.0f
/** Corner radius of the panel chrome. */
#define VIEW3D_SCENES_DRAWER_RADIUS 14.0f
/** Inset of the rounded panel from the grip line. */
#define VIEW3D_SCENES_DRAWER_PAD 6.0f
/** Mouse travel, in pixels, past which a grip press counts as a drag. */
#define VIEW3D_SCENES_DRAWER_DRAG_THRESHOLD 4
/** Vertical travel, in pixels, past which a card press becomes a reorder drag. */
#define VIEW3D_SCENES_DRAWER_CARD_DRAG_THRESHOLD 6
/** Slide amount at which the cards accept clicks and QA targets attach. */
#define VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT 0.98f
/** Open/close ease duration (wall clock, not per tick). */
#define VIEW3D_SCENES_DRAWER_SLIDE_SECONDS 0.28f

inline float view3d_scenes_drawer_runtime_amount(const ARegion *region)
{
  if (region == nullptr) {
    return 0.0f;
  }
  const ScenesDrawerRuntime *runtime = static_cast<const ScenesDrawerRuntime *>(
      region->regiondata);
  return runtime != nullptr ? runtime->amount : 0.0f;
}

/** The drawer floats above the toolbar instead of stacking beside it. */
inline bool view3d_scenes_drawer_is_overlay(const ScrArea *area, const ARegion *region)
{
  return area->spacetype == SPACE_VIEW3D &&
         region->regiontype == VIEW3D_SCENES_DRAWER_REGION_TYPE && region->overlap;
}

inline bool view3d_scenes_drawer_grip_rect_for(const ScrArea *area,
                                               const ARegion *region,
                                               const float amount,
                                               rcti *r_rect)
{
  if (area == nullptr || region == nullptr || area->spacetype != SPACE_VIEW3D) {
    return false;
  }

  const float scale = UI_SCALE_FAC;
  const float grip_w = VIEW3D_SCENES_DRAWER_GRIP_WIDTH * scale;
  const float grip_h = VIEW3D_SCENES_DRAWER_GRIP_HEIGHT * scale;
  const float pad = VIEW3D_SCENES_DRAWER_PAD * scale;

  /* The grip protrudes to the RIGHT; its flat left edge joins the panel.
   * Paint, hit-test and QA all read these same animated edges. */
  const float open_right = float(region->winrct.xmax) - pad;
  const float shut_right = float(region->winrct.xmin) + grip_w;
  const float grip_right = shut_right + amount * (open_right - shut_right);
  const float centre_y = 0.5f * float(area->totrct.ymin + area->totrct.ymax);

  r_rect->xmin = int(std::lround(grip_right - grip_w));
  r_rect->xmax = int(std::lround(grip_right));
  r_rect->ymin = int(std::lround(centre_y - grip_h * 0.5f));
  r_rect->ymax = int(std::lround(centre_y + grip_h * 0.5f));
  return BLI_rcti_size_x(r_rect) > 0;
}

inline bool view3d_scenes_drawer_panel_rect_for(const ScrArea *area,
                                                const ARegion *region,
                                                const float amount,
                                                rcti *r_rect)
{
  rcti grip;
  if (amount <= 0.001f || !view3d_scenes_drawer_grip_rect_for(area, region, amount, &grip)) {
    return false;
  }
  *r_rect = region->winrct;
  r_rect->xmax = grip.xmin;
  return BLI_rcti_size_x(r_rect) > 2;
}

inline bool view3d_scenes_drawer_grip_contains_xy(const ScrArea *area,
                                                  const ARegion *region,
                                                  const int xy[2])
{
  rcti grip;
  if (!view3d_scenes_drawer_grip_rect_for(
          area, region, view3d_scenes_drawer_runtime_amount(region), &grip))
  {
    return false;
  }
  return BLI_rcti_isect_pt_v(&grip, xy);
}

/** A narrow sash around the open panel's leading (right) edge, excluding rounded ends. */
inline bool view3d_scenes_drawer_edge_rect_for(const ScrArea *area,
                                               const ARegion *region,
                                               const float amount,
                                               rcti *r_rect)
{
  if (amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT ||
      !view3d_scenes_drawer_panel_rect_for(area, region, amount, r_rect))
  {
    return false;
  }
  const int edge = r_rect->xmax;
  const int pad = int(std::lround(4.0f * UI_SCALE_FAC));
  r_rect->xmin = edge - pad;
  r_rect->xmax = edge + pad;
  r_rect->ymin += int(VIEW3D_SCENES_DRAWER_RADIUS * UI_SCALE_FAC);
  r_rect->ymax -= int(VIEW3D_SCENES_DRAWER_RADIUS * UI_SCALE_FAC);
  return BLI_rcti_size_y(r_rect) > 0;
}

inline bool view3d_scenes_drawer_resize_contains_xy(const ScrArea *area,
                                                    const ARegion *region,
                                                    const int xy[2])
{
  rcti edge;
  return view3d_scenes_drawer_grip_contains_xy(area, region, xy) ||
         (view3d_scenes_drawer_edge_rect_for(
              area, region, view3d_scenes_drawer_runtime_amount(region), &edge) &&
          BLI_rcti_isect_pt_v(&edge, xy));
}

/**
 * The region is a resizable overlay; only the grip, resize edge and painted panel
 * slice are interactive. The scissored remainder is the viewport behind.
 */
inline bool view3d_scenes_drawer_contains_xy(const ScrArea *area,
                                             const ARegion *region,
                                             const int xy[2])
{
  if (area == nullptr || region == nullptr || area->spacetype != SPACE_VIEW3D ||
      region->regiontype != VIEW3D_SCENES_DRAWER_REGION_TYPE)
  {
    return false;
  }
  if (!BLI_rcti_isect_pt_v(&region->winrct, xy)) {
    return false;
  }
  if (view3d_scenes_drawer_resize_contains_xy(area, region, xy)) {
    return true;
  }
  rcti panel;
  return view3d_scenes_drawer_panel_rect_for(
             area, region, view3d_scenes_drawer_runtime_amount(region), &panel) &&
         BLI_rcti_isect_pt_v(&panel, xy);
}

}  // namespace blender
