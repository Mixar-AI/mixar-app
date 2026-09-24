/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The camera-move math the Director's two native movers share, and the one
 * question both of them have to answer the same way — whose the pointer is;
 * see `view3d_director_camera_move.hh` for why it is one copy.
 */

#include "BLI_math_vector.hh"
#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"

#include "ED_screen.hh"

#include "UI_interface_c.hh"

#include "WM_types.hh"

#include "view3d_director.hh"
#include "view3d_director_camera_move.hh"
#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {
/** Blender ships 3.0 m/s; an unset preference must not stop the camera. */
constexpr float DEFAULT_WALK_SPEED = 3.0f;
}  // namespace

/** Key -> direction, the SAME mapping `keymap.py` binds. */
int director_move_from_key(const int event_type)
{
  switch (event_type) {
    case EVT_WKEY:
      return DIRECTOR_MOVE_FORWARD;
    case EVT_SKEY:
      return DIRECTOR_MOVE_BACK;
    case EVT_AKEY:
      return DIRECTOR_MOVE_LEFT;
    case EVT_DKEY:
      return DIRECTOR_MOVE_RIGHT;
    case EVT_EKEY:
      return DIRECTOR_MOVE_UP;
    case EVT_QKEY:
      return DIRECTOR_MOVE_DOWN;
    default:
      return -1;
  }
}

unsigned int director_move_bit(const int direction)
{
  return 1u << unsigned(direction);
}

/** The active shot's camera; `r_locked` reports the take's LOCKED state. */
Object *director_move_camera(Scene *scene, bool *r_locked)
{
  /* One resolver for every native camera writer (nudge, aerial map, its
   * placement modal), so they can never disagree on which object moves. */
  return view3d_director_shot_camera(scene, r_locked);
}

float director_walk_speed()
{
  const float speed = U.walk_navigation.walk_speed;
  return speed > 0.0f ? speed : DEFAULT_WALK_SPEED;
}

/**
 * Unit world-space direction for every held key. W/S and A/D ride the
 * camera's own axes — forward is its local -Z, the way walk flies with
 * gravity off — while Q/E move on world Z. The SUM is normalised so a
 * diagonal (two keys held) travels at walk speed rather than faster.
 */
float3 director_move_vector(const float4x4 &matrix, const unsigned int held)
{
  const float3 right = math::normalize(matrix.x_axis());
  const float3 forward = -math::normalize(matrix.z_axis());
  const float3 up(0.0f, 0.0f, 1.0f);

  float3 sum(0.0f);
  if (held & director_move_bit(DIRECTOR_MOVE_FORWARD)) {
    sum += forward;
  }
  if (held & director_move_bit(DIRECTOR_MOVE_BACK)) {
    sum -= forward;
  }
  if (held & director_move_bit(DIRECTOR_MOVE_RIGHT)) {
    sum += right;
  }
  if (held & director_move_bit(DIRECTOR_MOVE_LEFT)) {
    sum -= right;
  }
  if (held & director_move_bit(DIRECTOR_MOVE_UP)) {
    sum += up;
  }
  if (held & director_move_bit(DIRECTOR_MOVE_DOWN)) {
    sum -= up;
  }
  /* Opposed keys cancel; a diagonal is normalised back to walk speed. */
  return math::normalize(sum);
}

/**
 * Is the pointer over the free STAGE of the Cinema viewport — the part with
 * nothing painted on it?
 *
 * The walk is a window-level modal handler, so it sees every event before any
 * region does. Claiming them all is what made the surface unclickable while
 * walking: the cards, the dock and the header are all still live UI, and a
 * click on one of them is not a look-drag.
 *
 * Three questions, cheapest first:
 *
 * - The pointer is inside this View3D's own window region. `event->xy` is
 *   window space and `region->winrct` is the region's box in the same space,
 *   so this is one rect test — and it is asked of `winrct` rather than of the
 *   modal context, which resolves the region differently depending on where
 *   the pointer went.
 * - No real button is under it. #region_but_find_rect_over is geometric, not
 *   a hover state, so it answers on the very first press rather than after a
 *   motion event has activated something.
 * - No painted Cinema control is under it either. Those DO lay real buttons
 *   over their pixels, so the previous test covers them; this one is the
 *   belt-and-braces for chrome that publishes a rect before its button
 *   exists, and it costs a walk over a list that is a few dozen entries long.
 */
bool director_pointer_on_stage(bContext *C, const wmEvent *event)
{
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  if (!area || area->spacetype != SPACE_VIEW3D || !region ||
      region->regiontype != RGN_TYPE_WINDOW)
  {
    return false;
  }
  if (!BLI_rcti_isect_pt(&region->winrct, event->xy[0], event->xy[1])) {
    return false;
  }
  /* The region Blender itself would hand this event to. A header, tool
   * header or sidebar laid OVER the viewport sits inside the viewport's own
   * rect — Zen Mode floats the View3D header and tool header this way — so
   * the rect test alone let the walk take presses meant for their buttons,
   * and the options row above the stage could not be clicked while walking.
   * Asking the same question event dispatch asks
   * (`wm_event_do_handlers_area_regions`) keeps every region that is not the
   * viewport its own. */
  if (ED_area_find_region_xy_visual(area, RGN_TYPE_ANY, event->xy) != region) {
    return false;
  }
  const int x = event->xy[0] - region->winrct.xmin;
  const int y = event->xy[1] - region->winrct.ymin;
  const rcti point = {x, x + 1, y, y + 1};
  if (ui::region_but_find_rect_over(region, &point) != nullptr) {
    return false;
  }
  const float fx = float(x);
  const float fy = float(y);
  for (const CinemaQARecord &record : cinema_qa_records()) {
    if (record.region == region && BLI_rctf_isect_pt(&record.rect, fx, fy)) {
      return false;
    }
  }
  return true;
}

}  // namespace blender
