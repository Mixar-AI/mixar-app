/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 * User-owned Scenes drawer width, and the region size that follows the slide:
 * the drawer is a normal left-aligned region, so its width pushes the
 * viewport right. Every writer of amount or width ends in
 * `view3d_scenes_drawer_layout_sync`; the draw pass never lays out.
 */

#include <algorithm>
#include <cmath>

#include "BKE_context.hh"
#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "UI_interface.hh"
#include "RNA_access.hh"

#include "view3d_scenes_drawer.hh"

namespace blender {

static PointerRNA drawer_wm_ptr(wmWindowManager *wm)
{
  return RNA_id_pointer_create(&wm->id);
}

static PropertyRNA *drawer_width_prop(wmWindowManager *wm, PointerRNA *ptr)
{
  *ptr = drawer_wm_ptr(wm);
  return RNA_struct_find_property(ptr, "mixar_scenes_drawer_width");
}

static bool drawer_width_ready(wmWindowManager *wm)
{
  PointerRNA ptr = drawer_wm_ptr(wm);
  PropertyRNA *prop = RNA_struct_find_property(&ptr, "mixar_scenes_drawer_width_ready");
  return prop != nullptr && RNA_property_boolean_get(&ptr, prop);
}

static void drawer_width_ready_set(wmWindowManager *wm, const bool ready)
{
  PointerRNA ptr = drawer_wm_ptr(wm);
  if (PropertyRNA *prop = RNA_struct_find_property(&ptr, "mixar_scenes_drawer_width_ready")) {
    RNA_property_boolean_set(&ptr, prop, ready);
  }
}

float view3d_scenes_drawer_width(wmWindowManager *wm)
{
  PointerRNA ptr;
  PropertyRNA *prop = drawer_width_prop(wm, &ptr);
  return prop ? RNA_property_float_get(&ptr, prop) : VIEW3D_SCENES_DRAWER_WIDTH;
}

float view3d_scenes_drawer_open_width(wmWindowManager *wm, const ScrArea *area)
{
  float width = view3d_scenes_drawer_width(wm);
  if (area == nullptr) {
    return width;
  }
  const float area_width = float(BLI_rcti_size_x(&area->totrct) + 1) / UI_SCALE_FAC;
  if (!drawer_width_ready(wm)) {
    width = std::max(float(VIEW3D_SCENES_DRAWER_MIN_WIDTH),
                     area_width * VIEW3D_SCENES_DRAWER_WIDTH_FRACTION);
    PointerRNA ptr;
    if (PropertyRNA *prop = drawer_width_prop(wm, &ptr)) {
      RNA_property_float_set(&ptr, prop, width);
    }
    drawer_width_ready_set(wm, true);
  }
  /* Never wider than the area, or the viewport would have no width left. */
  return std::min(width, std::max(area_width - float(VIEW3D_SCENES_DRAWER_MIN_WIDTH), 1.0f));
}

void view3d_scenes_drawer_size_sync(wmWindowManager *wm, ScrArea *area, ARegion *region)
{
  const float width = view3d_scenes_drawer_open_width(wm, area);
  const float amount = std::clamp(view3d_scenes_drawer_amount_wm(wm), 0.0f, 1.0f);
  const bool shut = amount <= VIEW3D_SCENES_DRAWER_SHUT_AMOUNT;
  /* `ARegion.sizex` <= 1 means "use the type's preferred size" to the layout,
   * so a barely open drawer is at least 2 units wide. */
  const int sizex = shut ? 0 : std::max(int(std::lround(width * amount)), 2);
  bool changed = false;
  if (shut != bool(region->flag & RGN_FLAG_HIDDEN)) {
    region->flag ^= RGN_FLAG_HIDDEN;
    changed = true;
  }
  if (region->sizex != sizex) {
    region->sizex = short(sizex);
    changed = true;
  }
  if (changed && area) {
    ED_area_tag_region_size_update(area, region);
  }
}

void view3d_scenes_drawer_layout_sync(bContext *C)
{
  ScrArea *area = view3d_scenes_drawer_area_find(C);
  ARegion *region = view3d_scenes_drawer_region_find(area);
  if (area == nullptr || region == nullptr) {
    return;
  }
  const bool was_hidden = (region->flag & RGN_FLAG_HIDDEN) != 0;
  view3d_scenes_drawer_size_sync(CTX_wm_manager(C), area, region);
  if (was_hidden != ((region->flag & RGN_FLAG_HIDDEN) != 0)) {
    /* Hidden ↔ visible is a real visibility change: handlers, UI blocks and
     * the region init follow it, exactly as `screen.region_toggle` does. The
     * in-between frames of a slide only change the width, which
     * `AREA_FLAG_REGION_SIZE_UPDATE` (tagged above) re-lays out before the
     * next draw (`wm_draw.cc` → `ED_area_update_region_sizes`). */
    ED_region_visibility_change_update(C, area, region);
  }
}

void view3d_scenes_drawer_width_set(bContext *C, const float width)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  PointerRNA ptr;
  if (PropertyRNA *prop = drawer_width_prop(wm, &ptr)) {
    RNA_property_float_set(&ptr, prop, std::max(width, float(VIEW3D_SCENES_DRAWER_MIN_WIDTH)));
  }
  drawer_width_ready_set(wm, true);
  view3d_scenes_drawer_layout_sync(C);
}

}  // namespace blender
