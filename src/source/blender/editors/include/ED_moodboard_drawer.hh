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

/** Factory width fallback (unscaled UI units) before the first View3D layout
 * promotes to ``VIEW3D_MOODBOARD_DRAWER_WIDTH_FRACTION``. Keep in lockstep with
 * the Python FloatProperty default on `mixar_moodboard_drawer_width`. */
#define VIEW3D_MOODBOARD_DRAWER_WIDTH 340
/** Fraction of the View3D area used on first open (~35% coverage). */
#define VIEW3D_MOODBOARD_DRAWER_WIDTH_FRACTION 0.35f
/** Pulls smaller than this settle closed; all larger widths stay put. */
#define VIEW3D_MOODBOARD_DRAWER_MIN_WIDTH 120
/** Clickable/drawn width of the labeled Moodboard tab. */
#define VIEW3D_MOODBOARD_DRAWER_GRIP_WIDTH 22.0f
/** Vertical extent of the Moodboard tab, centred in the area. */
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

/** The drawer floats above sidebars instead of stacking beside them. */
inline bool view3d_moodboard_drawer_is_overlay(const ScrArea *area, const ARegion *region)
{
  return area->spacetype == SPACE_VIEW3D && region->regiontype == RGN_TYPE_TOOL_PROPS &&
         region->overlap;
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

/** A narrow sash around the open panel's leading edge, excluding rounded ends. */
inline bool view3d_moodboard_drawer_edge_rect_for(const ScrArea *area,
                                                const ARegion *region,
                                                const float amount,
                                                rcti *r_rect)
{
  if (amount < VIEW3D_MOODBOARD_DRAWER_CANVAS_MIN_AMOUNT ||
      !view3d_moodboard_drawer_panel_rect_for(area, region, amount, r_rect))
  {
    return false;
  }
  const int edge = r_rect->xmin;
  const int pad = int(std::lround(4.0f * UI_SCALE_FAC));
  r_rect->xmin = edge - pad;
  r_rect->xmax = edge + pad;
  r_rect->ymin += int(VIEW3D_MOODBOARD_DRAWER_RADIUS * UI_SCALE_FAC);
  r_rect->ymax -= int(VIEW3D_MOODBOARD_DRAWER_RADIUS * UI_SCALE_FAC);
  return BLI_rcti_size_y(r_rect) > 0;
}

inline bool view3d_moodboard_drawer_resize_contains_xy(const ScrArea *area,
                                                     const ARegion *region,
                                                     const int xy[2])
{
  rcti edge;
  return view3d_moodboard_drawer_grip_contains_xy(area, region, xy) ||
         (view3d_moodboard_drawer_edge_rect_for(
              area, region, view3d_moodboard_drawer_runtime_amount(region), &edge) &&
          BLI_rcti_isect_pt_v(&edge, xy));
}

/**
 * The region is a resizable overlay; only the grip, resize edge and painted panel
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
  if (view3d_moodboard_drawer_resize_contains_xy(area, region, xy)) {
    return true;
  }
  rcti panel;
  return view3d_moodboard_drawer_panel_rect_for(
             area, region, view3d_moodboard_drawer_runtime_amount(region), &panel) &&
         BLI_rcti_isect_pt_v(&panel, xy);
}

}  // namespace blender
