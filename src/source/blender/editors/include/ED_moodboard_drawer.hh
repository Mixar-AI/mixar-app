/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edscr
 *
 * Hit geometry for the Zen Mode moodboard drawer. Lives in `editors/include`
 * so screen event routing and the View3D drawer can share one expression
 * without a screen → space_view3d link.
 */

#pragma once

#include <cmath>

#include "BLI_rect.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

struct wmTimer;

namespace blender {

/** Last painted slide, stored on the drawer region's `regiondata`. */
struct MoodboardDrawerRuntime {
  float amount = 0.0f;
  /** Wall-clock start of the current ease; 0 while not time-animating. */
  double slide_started_at = 0.0;
  float slide_start_amount = 0.0f;
  /** True while the grip is dragging: update must not start an ease. */
  bool slide_held = false;
  /** TIMERNOTIFIER that tags this region; owned by the window manager. */
  wmTimer *tick_timer = nullptr;
};

/** Initial dock width in unscaled pixels. */
#define VIEW3D_MOODBOARD_DRAWER_WIDTH 340
/** Pulls smaller than this settle closed; all larger widths stay put. */
#define VIEW3D_MOODBOARD_DRAWER_MIN_WIDTH 120
/** Clickable/drawn width of the edge grip. */
#define VIEW3D_MOODBOARD_DRAWER_GRIP_WIDTH 18.0f
/** Vertical extent of the grip, centred in the area. */
#define VIEW3D_MOODBOARD_DRAWER_GRIP_HEIGHT 144.0f
/** Corner radius of the panel chrome. */
#define VIEW3D_MOODBOARD_DRAWER_RADIUS 14.0f
/** Inset of the rounded panel from the grip line. */
#define VIEW3D_MOODBOARD_DRAWER_PAD 6.0f
/** Mouse travel, in pixels, past which a grip press counts as a drag. */
#define VIEW3D_MOODBOARD_DRAWER_DRAG_THRESHOLD 4
/** Slide amount at which Mixie canvas handlers and QA media targets attach.
 * Keep in lockstep with `MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT`. */
#define VIEW3D_MOODBOARD_DRAWER_CANVAS_MIN_AMOUNT 0.98f
/** Open/close ease duration. Position is `f(wall clock)`, not a per-tick
 * fraction, so a bunched Python timer cannot jump the panel. */
#define VIEW3D_MOODBOARD_DRAWER_SLIDE_SECONDS 0.28f

inline float view3d_moodboard_drawer_runtime_amount(const ARegion *region)
{
  if (region == nullptr) {
    return 0.0f;
  }
  const MoodboardDrawerRuntime *runtime =
      static_cast<const MoodboardDrawerRuntime *>(region->regiondata);
  return runtime != nullptr ? runtime->amount : 0.0f;
}

inline bool view3d_moodboard_drawer_grip_rect_for(const ScrArea *area,
                                                  const ARegion *region,
                                                  const float amount,
                                                  rcti *r_rect)
{
  if (area == nullptr || region == nullptr || area->spacetype != SPACE_VIEW3D) {
    return false;
  }

  const float scale = UI_SCALE_FAC;
  const float grip_w = VIEW3D_MOODBOARD_DRAWER_GRIP_WIDTH * scale;
  const float grip_h = VIEW3D_MOODBOARD_DRAWER_GRIP_HEIGHT * scale;
  const float pad = VIEW3D_MOODBOARD_DRAWER_PAD * scale;

  /* The grip protrudes to the left; its flat right edge joins the panel.
   * Paint, hit-test and QA all read these same animated edges. */
  const float open_left = float(region->winrct.xmin) + pad;
  const float shut_left = float(region->winrct.xmax) - grip_w;
  const float grip_left = shut_left - amount * (shut_left - open_left);
  const float centre_y = 0.5f * float(area->totrct.ymin + area->totrct.ymax);

  r_rect->xmin = int(std::lround(grip_left));
  r_rect->xmax = int(std::lround(grip_left + grip_w));
  r_rect->ymin = int(std::lround(centre_y - grip_h * 0.5f));
  r_rect->ymax = int(std::lround(centre_y + grip_h * 0.5f));
  return BLI_rcti_size_x(r_rect) > 0;
}

inline bool view3d_moodboard_drawer_panel_rect_for(const ScrArea *area,
                                                   const ARegion *region,
                                                   const float amount,
                                                   rcti *r_rect)
{
  rcti grip;
  if (amount <= 0.001f ||
      !view3d_moodboard_drawer_grip_rect_for(area, region, amount, &grip))
  {
    return false;
  }
  *r_rect = region->winrct;
  r_rect->xmin = grip.xmax;
  return BLI_rcti_size_x(r_rect) > 2;
}

inline bool view3d_moodboard_drawer_grip_contains_xy(const ScrArea *area,
                                                     const ARegion *region,
                                                     const int xy[2])
{
  rcti grip;
  if (!view3d_moodboard_drawer_grip_rect_for(
          area, region, view3d_moodboard_drawer_runtime_amount(region), &grip))
  {
    return false;
  }
  return BLI_rcti_isect_pt_v(&grip, xy);
}

/**
 * The region is a resizable overlay; only the grip and the painted panel
 * slice are interactive. The scissored remainder is the viewport behind.
 */
inline bool view3d_moodboard_drawer_contains_xy(const ScrArea *area,
                                                const ARegion *region,
                                                const int xy[2])
{
  if (area == nullptr || region == nullptr || area->spacetype != SPACE_VIEW3D ||
      region->regiontype != RGN_TYPE_TOOL_PROPS)
  {
    return false;
  }
  if (!BLI_rcti_isect_pt_v(&region->winrct, xy)) {
    return false;
  }
  if (view3d_moodboard_drawer_grip_contains_xy(area, region, xy)) {
    return true;
  }
  rcti panel;
  return view3d_moodboard_drawer_panel_rect_for(
             area, region, view3d_moodboard_drawer_runtime_amount(region), &panel) &&
         BLI_rcti_isect_pt_v(&panel, xy);
}

}  // namespace blender
