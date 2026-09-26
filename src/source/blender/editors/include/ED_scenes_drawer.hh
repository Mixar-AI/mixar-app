/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edscr
 *
 * Hit geometry for the Zen Mode Scenes drawer, docked to the LEFT edge of the
 * 3D View. Unlike the moodboard drawer (`ED_moodboard_drawer.hh`, an overlay)
 * it is a normal region that pushes the viewport right as it opens; a toolbar
 * button toggles it. Lives in `editors/include` so screen event routing and
 * the View3D drawer share one expression without a screen → space_view3d
 * link.
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
struct wmTimer;
namespace blender::gpu {
class Texture;
}

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
 * rects are WINDOW pixels. */
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
  /** The last render, read back the moment it finished. The render runs from
   * a timer, outside any window frame; a GPU texture rendered there and read
   * by the card's blit in a later frame came up black on Metal from the
   * second render on. Pixels in memory have no such lifetime. */
  std::vector<unsigned char> pixels;
  int pixels_w = 0;
  int pixels_h = 0;
  /** `pixels` changed since `texture` was last uploaded (draw pass). */
  bool pixels_dirty = false;
  /** The card's texture, created and refreshed in the region's draw pass. */
  blender::gpu::Texture *texture = nullptr;
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
  /** TIMERNOTIFIER that tags this region; owned by the window manager. */
  wmTimer *tick_timer = nullptr;
  /** A thumbnail rendered during the last draw pass: the listener tags the
   * region again, since a redraw tagged from inside the pass is dropped. */
  bool redraw_pending = false;
  /** Layout of the last draw pass (window pixels). */
  std::vector<ScenesDrawerCard> cards;
  rcti new_rect = {};
  bool new_visible = false;
  /** Card list scroll, window pixels, 0 = top; `scroll_max` is measured by
   * the draw pass from the cards that did not fit. */
  float scroll = 0.0f;
  float scroll_max = 0.0f;
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
/** Half-width of the resize sash on the panel's right edge, unscaled px. */
#define VIEW3D_SCENES_DRAWER_EDGE_PAD 4.0f
/** Mouse travel, in pixels, past which an edge press counts as a drag. */
#define VIEW3D_SCENES_DRAWER_DRAG_THRESHOLD 4
/** Vertical travel, in pixels, past which a card press becomes a reorder drag. */
#define VIEW3D_SCENES_DRAWER_CARD_DRAG_THRESHOLD 6
/** Card thumbnail size (unscaled UI units), shared by draw and the refresh operator. */
#define VIEW3D_SCENES_DRAWER_THUMB_W 78.0f
#define VIEW3D_SCENES_DRAWER_THUMB_H 44.0f
/** One wheel notch scrolls the card list by one card pitch (unscaled). */
#define VIEW3D_SCENES_DRAWER_SCROLL_STEP 68.0f
/** Slide amount at which the cards accept clicks and QA targets attach. */
#define VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT 0.98f
/** Slide amount at or below which the region is hidden (zero width). */
#define VIEW3D_SCENES_DRAWER_SHUT_AMOUNT 0.01f
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

/**
 * The panel is the whole region: a normal (non-overlapping) left-aligned
 * region whose width is the open width times the slide amount, so the
 * viewport is pushed right as it opens. Shut, the region is hidden.
 */
inline bool view3d_scenes_drawer_panel_rect_for(const ScrArea *area,
                                                const ARegion *region,
                                                const float amount,
                                                rcti *r_rect)
{
  if (area == nullptr || region == nullptr || area->spacetype != SPACE_VIEW3D ||
      region->regiontype != VIEW3D_SCENES_DRAWER_REGION_TYPE ||
      (region->flag & RGN_FLAG_HIDDEN) || amount <= 0.001f)
  {
    return false;
  }
  *r_rect = region->winrct;
  return BLI_rcti_size_x(r_rect) > 2;
}

/** The resize sash: a narrow strip inside the open panel's right edge. */
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
  const int pad = int(std::lround(2.0f * VIEW3D_SCENES_DRAWER_EDGE_PAD * UI_SCALE_FAC));
  r_rect->xmin = r_rect->xmax - pad;
  return BLI_rcti_size_x(r_rect) > 0 && BLI_rcti_size_y(r_rect) > 0;
}

inline bool view3d_scenes_drawer_resize_contains_xy(const ScrArea *area,
                                                    const ARegion *region,
                                                    const int xy[2])
{
  rcti edge;
  return view3d_scenes_drawer_edge_rect_for(
             area, region, view3d_scenes_drawer_runtime_amount(region), &edge) &&
         BLI_rcti_isect_pt_v(&edge, xy);
}

/** True on the visible panel (the region's own pixels; nothing else is it). */
inline bool view3d_scenes_drawer_contains_xy(const ScrArea *area,
                                             const ARegion *region,
                                             const int xy[2])
{
  rcti panel;
  return view3d_scenes_drawer_panel_rect_for(
             area, region, view3d_scenes_drawer_runtime_amount(region), &panel) &&
         BLI_rcti_isect_pt_v(&panel, xy);
}

}  // namespace blender
