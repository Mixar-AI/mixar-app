/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar: the draw-derived hit-rects of the Mixar category tab strip.
 *
 * It used to be neither bounded nor validated. The map gained an entry per
 * region that ever drew the strip and lost none, so opening, closing and
 * splitting the Mixie sidebar (or loading files with different layouts) leaked
 * a vector each time. Worse, the key is a raw ARegion pointer: the allocator
 * hands a freed region's address to a new one, and a click arriving before
 * that region's first draw then reads the DEAD region's tab idnames and
 * switches to a category that may not exist. Recording the region's winrct
 * alongside catches exactly that recycled-pointer case.
 *
 * See interface_mixar_tab_rects.hh for why dropping entries is always safe.
 */

#include <utility>

#include "BLI_map.hh"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "DNA_screen_types.h"

#include "interface_mixar_section.hh"
#include "interface_mixar_tab_rects.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

struct MixarCategoryTabs {
  /* The region's own rect when these were recorded: a recycled ARegion pointer
   * almost never reproduces it, and a resize invalidates the rects anyway. */
  rcti winrct;
  Vector<MixarCategoryTabRect> tabs;
};

/* Regions that can draw the strip at once are a handful; this only has to stop
 * unbounded growth, and clearing is free because the cache is rebuilt on draw. */
static constexpr int MIXAR_TAB_RECT_MAX_REGIONS = 64;

static Map<const ARegion *, MixarCategoryTabs> &mixar_category_tab_rects()
{
  static Map<const ARegion *, MixarCategoryTabs> map;
  return map;
}

/* The entry recorded for this exact region, or null when it is absent or was
 * recorded for a region that no longer has this geometry. */
static const Vector<MixarCategoryTabRect> *mixar_category_tabs_for(const ARegion *region)
{
  const MixarCategoryTabs *entry = mixar_category_tab_rects().lookup_ptr(region);
  if (entry == nullptr || region == nullptr) {
    return nullptr;
  }
  if (!BLI_rcti_compare(&entry->winrct, &region->winrct)) {
    return nullptr;
  }
  return &entry->tabs;
}

const char *UI_mixar_panel_category_find_at(const ARegion *region, const int mval[2])
{
  const Vector<MixarCategoryTabRect> *tabs = mixar_category_tabs_for(region);
  if (tabs == nullptr) {
    return nullptr;
  }
  for (const MixarCategoryTabRect &tab : *tabs) {
    if (BLI_rcti_isect_pt(&tab.rect, mval[0], mval[1])) {
      return tab.idname;
    }
  }
  return nullptr;
}

bool UI_mixar_panel_category_tab_rect_get(const ARegion *region,
                                          const char *idname,
                                          rcti *r_rect)
{
  const Vector<MixarCategoryTabRect> *tabs = mixar_category_tabs_for(region);
  if (tabs == nullptr) {
    return false;
  }
  for (const MixarCategoryTabRect &tab : *tabs) {
    if (STREQ(tab.idname, idname)) {
      *r_rect = tab.rect;
      return true;
    }
  }
  return false;
}

void mixar_category_tabs_store(const ARegion *region, Vector<MixarCategoryTabRect> &&tabs)
{
  Map<const ARegion *, MixarCategoryTabs> &rect_map = mixar_category_tab_rects();
  if (rect_map.size() >= MIXAR_TAB_RECT_MAX_REGIONS && !rect_map.contains(region)) {
    /* Safe at any moment: every live strip re-records itself on its next draw. */
    rect_map.clear();
  }
  rect_map.add_overwrite(region, MixarCategoryTabs{region->winrct, std::move(tabs)});
}

}  // namespace blender::ui
