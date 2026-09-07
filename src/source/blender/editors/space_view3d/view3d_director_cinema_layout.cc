/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Layout of the Cinema Mode surface: the design-unit scale and its fit to
 * the region, the wide/compact gate, the side margin, list windowing and the
 * stage frame between the columns.
 *
 * The design is a 1x window mock. Every painter multiplies design px by
 * #cinema_unit(), which #cinema_unit_begin resolves once per draw from the
 * viewport region: UI scale times the largest fit (never above 1) that keeps
 * the whole design inside the region. Below #CINEMA_SCALE_MIN the compact
 * rail draws instead (#cinema_surface_fits).
 */

#include <algorithm>

#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Scale
 * \{ */

namespace {
/* Resolved once per draw; every region draws on the main thread in sequence,
 * so one static is the whole book-keeping. */
float g_unit = 1.0f;

/** Design px the surface needs, before any scale. */
float cinema_need_w()
{
  return CINEMA_PANEL_W * 2.0f + CINEMA_MARGIN_MIN * 2.0f + CINEMA_GATE_MIN_W;
}

float cinema_need_h()
{
  /* DERIVED from the lowest content in either column rather than guessed:
   * #cinema_design_rect anchors on #CINEMA_VIEWPORT_TOP, so a shorter region
   * would push `rect.ymin` negative and lay those controls out below the
   * region. */
  const float content_bottom = cinema_content_bottom();
  return content_bottom - CINEMA_VIEWPORT_TOP;
}
}  // namespace

float cinema_content_bottom()
{
  /* The Speed card's foot and the Export button's. */
  return std::max(CINEMA_SPEED_CARD_Y + CINEMA_SPEED_CARD_H, CINEMA_EXPORT_Y + CINEMA_EXPORT_H);
}

float cinema_fit_scale(const ARegion *region)
{
  if (region == nullptr) {
    return 0.0f;
  }
  /* The design is a 1x window mock, so a design px IS a UI px before DPI. */
  const float avail_w = float(region->winx) / UI_SCALE_FAC;
  const float avail_h = float(region->winy) / UI_SCALE_FAC;
  const float fit = std::min(avail_w / cinema_need_w(), avail_h / cinema_need_h());
  return std::clamp(fit, 0.0f, 1.0f);
}

void cinema_unit_begin(const ARegion *main_region)
{
  const float fit = main_region ? cinema_fit_scale(main_region) : 1.0f;
  g_unit = UI_SCALE_FAC * std::max(fit, CINEMA_SCALE_MIN);
}

float cinema_unit()
{
  return g_unit;
}

float cinema_margin(const ARegion *region)
{
  const float avail = float(region->winx) / cinema_unit();
  const float slack = (avail - CINEMA_PANEL_W * 2.0f - CINEMA_GATE_MIN_W) * 0.5f;
  return std::clamp(slack, CINEMA_MARGIN_MIN, CINEMA_MARGIN);
}

rctf cinema_design_rect(
    const ARegion *region, const float x, const float y, const float w, const float h)
{
  const float u = cinema_unit();
  rctf rect;
  rect.xmin = x * u;
  rect.xmax = (x + w) * u;
  rect.ymax = float(region->winy) - (y - CINEMA_VIEWPORT_TOP) * u;
  rect.ymin = rect.ymax - h * u;
  return rect;
}

bool cinema_surface_fits(const ARegion *region)
{
  /* The surface shrinks to fit (see #cinema_unit_begin); only below the floor
   * does the compact rail take over. */
  return cinema_fit_scale(region) >= CINEMA_SCALE_MIN;
}

float cinema_list_row_h()
{
  return std::min(CINEMA_ROW_H, CINEMA_LIST_PITCH);
}

int cinema_list_window_start(const int count, const int active)
{
  /* The card only has room for #CINEMA_LIST_MAX_ROWS. Window the list around
   * the live entry rather than always showing the head: with the active shot
   * off the end no row highlighted at all, so "My Cameras" claimed none was
   * being directed. */
  if (count <= CINEMA_LIST_MAX_ROWS) {
    return 0;
  }
  const int centred = std::clamp(active, 0, count - 1) - CINEMA_LIST_MAX_ROWS / 2;
  return std::clamp(centred, 0, count - CINEMA_LIST_MAX_ROWS);
}

bool cinema_stage_rect(const bContext *C, const ARegion *region, rctf *r_rect)
{
  DirectorViewState state;
  if (region == nullptr || !view3d_director_state_read(CTX_data_scene(C), &state) ||
      !state.active)
  {
    return false;
  }
  cinema_unit_begin(region);
  if (!cinema_surface_fits(region)) {
    return false;
  }
  const float u = cinema_unit();
  const float margin = cinema_margin(region);
  const float inset = CINEMA_STAGE_INSET * u;
  r_rect->xmin = (margin + CINEMA_PANEL_W) * u + inset;
  r_rect->xmax = float(region->winx) - (margin + CINEMA_PANEL_W) * u - inset;
  /* Top-aligned with the columns, ending where their lowest content does. */
  const rctf span = cinema_design_rect(
      region, 0.0f, CINEMA_COLUMN_TOP, 0.0f, cinema_content_bottom() - CINEMA_COLUMN_TOP);
  r_rect->ymax = span.ymax;
  r_rect->ymin = span.ymin;
  return BLI_rctf_size_x(r_rect) > 0.0f && BLI_rctf_size_y(r_rect) > 0.0f;
}

void cinema_draw_stage(const ARegion *region)
{
  const float u = cinema_unit();
  const float margin = cinema_margin(region);
  const float inset = CINEMA_STAGE_INSET * u;
  rctf stage;
  stage.xmin = (margin + CINEMA_PANEL_W) * u + inset;
  stage.xmax = float(region->winx) - (margin + CINEMA_PANEL_W) * u - inset;
  const rctf span = cinema_design_rect(
      region, 0.0f, CINEMA_COLUMN_TOP, 0.0f, cinema_content_bottom() - CINEMA_COLUMN_TOP);
  stage.ymax = span.ymax;
  stage.ymin = span.ymin;
  if (BLI_rctf_size_x(&stage) <= 0.0f || BLI_rctf_size_y(&stage) <= 0.0f) {
    return;
  }
  const float fill[4] = CINEMA_COL_GATE_FILL;
  const float line[4] = CINEMA_COL_GATE_LINE;
  cinema_fill(stage, 18.5f * u, fill);
  cinema_outline(stage, 18.5f * u, line, u);
}

/** \} */

}  // namespace blender
