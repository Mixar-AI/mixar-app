/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 * User-owned drawer width. Only event/lifecycle callbacks request layout;
 * the overlap leaves the viewport's region and projection unchanged.
 */

#include <algorithm>
#include <cmath>

#include "BKE_context.hh"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "RNA_access.hh"

#include "view3d_moodboard_drawer.hh"

namespace blender {

static PropertyRNA *drawer_width_prop(wmWindowManager *wm, PointerRNA *ptr)
{
  *ptr = RNA_id_pointer_create(&wm->id);
  return RNA_struct_find_property(ptr, "mixar_moodboard_drawer_width");
}

float view3d_moodboard_drawer_width(wmWindowManager *wm)
{
  PointerRNA ptr;
  PropertyRNA *prop = drawer_width_prop(wm, &ptr);
  return prop ? RNA_property_float_get(&ptr, prop) : VIEW3D_MOODBOARD_DRAWER_WIDTH;
}

void view3d_moodboard_drawer_size_sync(wmWindowManager *wm, ScrArea *area, ARegion *region)
{
  float width = view3d_moodboard_drawer_width(wm);
  if (area) {
    width = std::min(width, float(BLI_rcti_size_x(&area->totrct) + 1) / UI_SCALE_FAC);
  }
  if (std::fabs(region->sizex - width) < 0.01f) {
    return;
  }
  /* Layout writes a rounded width back to sizex. Restore the requested width
   * to prevent cumulative DPI rounding across repeated layout passes. */
  region->sizex = width;
  if (area) {
    ED_area_tag_region_size_update(area, region);
  }
}

void view3d_moodboard_drawer_width_set(bContext *C, const float width)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  PointerRNA ptr;
  if (PropertyRNA *prop = drawer_width_prop(wm, &ptr)) {
    RNA_property_float_set(&ptr, prop, std::max(width, float(VIEW3D_MOODBOARD_DRAWER_MIN_WIDTH)));
  }
  if (ARegion *region = view3d_moodboard_drawer_region_find(CTX_wm_area(C))) {
    view3d_moodboard_drawer_size_sync(wm, CTX_wm_area(C), region);
  }
}

}  // namespace blender
