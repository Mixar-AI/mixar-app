/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The ONE definition of a moodboard resize handle.
 *
 * Every resizable thing on this canvas -- a reference image, a movie, a text
 * box, an inference card -- wears the same four corner squares and resizes by
 * the same rule: grab a corner, the OPPOSITE corner is anchored, and the
 * gesture is a uniform scale about that anchor. Draw, hit-test and drag all
 * resolve through here, so the squares the user aims at cannot drift away from
 * the region that responds, and the two surfaces cannot grow different
 * behaviour (which is exactly what happened: a card had a single bottom-right
 * wedge that only ever grew down-right, while a picture had eight handles).
 *
 * CORNERS ONLY. The four edge-midpoint handles are gone: on this canvas they
 * meant "stretch one axis", which for a picture or a generated result is a
 * distortion nobody asks for, and they crowded the corners that do the work.
 */

#include <cmath>

#include "BLI_rect.h"
#include "BLI_utildefines.h" /* ELEM */

#include "mixie_intern.hh"

namespace blender::ed::mixie {

void moodboard_resize_handle_positions(const rctf &rect,
                                       float r_pos[MOODBOARD_RESIZE_HANDLE_COUNT][2])
{
  /* Order matches the MOODBOARD_HANDLE_* indices, counter-clockwise from the
   * bottom-left. Anything that renumbers this has to renumber the anchor rule
   * with it -- the two are the whole contract. */
  r_pos[MOODBOARD_HANDLE_BOTTOM_LEFT][0] = rect.xmin;
  r_pos[MOODBOARD_HANDLE_BOTTOM_LEFT][1] = rect.ymin;
  r_pos[MOODBOARD_HANDLE_BOTTOM_RIGHT][0] = rect.xmax;
  r_pos[MOODBOARD_HANDLE_BOTTOM_RIGHT][1] = rect.ymin;
  r_pos[MOODBOARD_HANDLE_TOP_RIGHT][0] = rect.xmax;
  r_pos[MOODBOARD_HANDLE_TOP_RIGHT][1] = rect.ymax;
  r_pos[MOODBOARD_HANDLE_TOP_LEFT][0] = rect.xmin;
  r_pos[MOODBOARD_HANDLE_TOP_LEFT][1] = rect.ymax;
}

int moodboard_resize_handle_at(const rctf &rect,
                               const float local_x,
                               const float local_y,
                               const float tolerance)
{
  float pos[MOODBOARD_RESIZE_HANDLE_COUNT][2];
  moodboard_resize_handle_positions(rect, pos);
  for (int handle = 0; handle < MOODBOARD_RESIZE_HANDLE_COUNT; handle++) {
    const float dx = local_x - pos[handle][0];
    const float dy = local_y - pos[handle][1];
    if (dx * dx + dy * dy < tolerance * tolerance) {
      return handle;
    }
  }
  return -1;
}

void moodboard_resize_handle_anchor(const rctf &rect,
                                    const int handle,
                                    float *r_anchor_x,
                                    float *r_anchor_y)
{
  /* The corner diagonally opposite the one being dragged: it is the point the
   * user expects to stay put, and it is what makes the gesture reversible. */
  switch (handle) {
    case MOODBOARD_HANDLE_BOTTOM_LEFT:
      *r_anchor_x = rect.xmax;
      *r_anchor_y = rect.ymax;
      break;
    case MOODBOARD_HANDLE_BOTTOM_RIGHT:
      *r_anchor_x = rect.xmin;
      *r_anchor_y = rect.ymax;
      break;
    case MOODBOARD_HANDLE_TOP_RIGHT:
      *r_anchor_x = rect.xmin;
      *r_anchor_y = rect.ymin;
      break;
    case MOODBOARD_HANDLE_TOP_LEFT:
      *r_anchor_x = rect.xmax;
      *r_anchor_y = rect.ymin;
      break;
    default:
      *r_anchor_x = rect.xmin;
      *r_anchor_y = rect.ymin;
      break;
  }
}

float moodboard_resize_scale_factor(const rctf &rect,
                                    const int handle,
                                    const float local_x,
                                    const float local_y)
{
  /* Uniform scale measured along the DIAGONAL from the anchor: the ratio of
   * the cursor's distance to the anchor against the rect's own diagonal. One
   * number for both axes is what keeps the aspect locked, and taking it from
   * the diagonal (rather than from dx alone) means the handle tracks the
   * pointer in both directions at once. */
  float anchor_x, anchor_y;
  moodboard_resize_handle_anchor(rect, handle, &anchor_x, &anchor_y);
  const float width = BLI_rctf_size_x(&rect);
  const float height = BLI_rctf_size_y(&rect);
  const float diagonal = sqrtf(width * width + height * height);
  if (diagonal <= 0.001f) {
    return 1.0f;
  }
  const float dx = local_x - anchor_x;
  const float dy = local_y - anchor_y;
  return sqrtf(dx * dx + dy * dy) / diagonal;
}

void moodboard_resize_place(const rctf &rect,
                            const int handle,
                            const float new_width,
                            const float new_height,
                            rctf *r_rect)
{
  /* Grow or shrink away from the anchored corner. Derived from the INITIAL
   * rect plus the new size every frame -- never accumulated -- so a dropped
   * MOUSEMOVE cannot leave the rect out of step with the pointer.
   *
   * Which side the anchor is on comes from the HANDLE, not from comparing the
   * anchor against the rect's midpoint: on a degenerate (zero-width or
   * zero-height) rect that comparison has no correct answer. */
  const bool anchor_is_right = ELEM(
      handle, MOODBOARD_HANDLE_BOTTOM_LEFT, MOODBOARD_HANDLE_TOP_LEFT);
  const bool anchor_is_top = ELEM(
      handle, MOODBOARD_HANDLE_BOTTOM_LEFT, MOODBOARD_HANDLE_BOTTOM_RIGHT);
  float anchor_x, anchor_y;
  moodboard_resize_handle_anchor(rect, handle, &anchor_x, &anchor_y);
  r_rect->xmin = anchor_is_right ? anchor_x - new_width : anchor_x;
  r_rect->xmax = r_rect->xmin + new_width;
  r_rect->ymin = anchor_is_top ? anchor_y - new_height : anchor_y;
  r_rect->ymax = r_rect->ymin + new_height;
}

}  // namespace blender::ed::mixie
