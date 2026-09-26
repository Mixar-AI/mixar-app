/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Sliding Scenes drawer: the WindowManager-owned state accessors. Mirror of
 * `view3d_moodboard_drawer_state.cc` on the `mixar_scenes_drawer_*` properties
 * Python registers in `space_mixie_chat/ui/properties/scene_tabs_props.py`.
 */

#include <algorithm>

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "ED_scenes_drawer.hh"

#include "view3d_scenes_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static PropertyRNA *drawer_prop(const bContext *C, PointerRNA *r_wm_ptr, const char *name)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return nullptr;
  }
  *r_wm_ptr = RNA_id_pointer_create(&wm->id);
  return RNA_struct_find_property(r_wm_ptr, name);
}

static float drawer_float_get(const bContext *C, const char *name, const float fallback)
{
  PointerRNA wm_ptr;
  PropertyRNA *prop = drawer_prop(C, &wm_ptr, name);
  return prop != nullptr ? RNA_property_float_get(&wm_ptr, prop) : fallback;
}

static int drawer_int_get(const bContext *C, const char *name, const int fallback)
{
  PointerRNA wm_ptr;
  PropertyRNA *prop = drawer_prop(C, &wm_ptr, name);
  return prop != nullptr ? RNA_property_int_get(&wm_ptr, prop) : fallback;
}

static void drawer_float_set(const bContext *C, const char *name, const float value)
{
  PointerRNA wm_ptr;
  PropertyRNA *prop = drawer_prop(C, &wm_ptr, name);
  if (prop != nullptr) {
    RNA_property_float_set(&wm_ptr, prop, value);
  }
}

static void drawer_int_set(const bContext *C, const char *name, const int value)
{
  PointerRNA wm_ptr;
  PropertyRNA *prop = drawer_prop(C, &wm_ptr, name);
  if (prop != nullptr) {
    RNA_property_int_set(&wm_ptr, prop, value);
  }
}

float view3d_scenes_drawer_amount(const bContext *C)
{
  return drawer_float_get(C, "mixar_scenes_drawer_amount", 0.0f);
}

void view3d_scenes_drawer_amount_set(bContext *C, const float amount)
{
  const float clamped = std::clamp(amount, 0.0f, 1.0f);
  drawer_float_set(C, "mixar_scenes_drawer_amount", clamped);
  if (ARegion *region = view3d_scenes_drawer_region_from_context(C)) {
    if (ScenesDrawerRuntime *runtime = static_cast<ScenesDrawerRuntime *>(region->regiondata)) {
      runtime->amount = clamped;
    }
  }
  /* The region's width IS the amount: the viewport is pushed as it opens. */
  view3d_scenes_drawer_layout_sync(C);
}

int view3d_scenes_drawer_target(const bContext *C)
{
  return drawer_int_get(C, "mixar_scenes_drawer_target", 0);
}

void view3d_scenes_drawer_target_set(bContext *C, const int target)
{
  drawer_int_set(C, "mixar_scenes_drawer_target", target != 0 ? 1 : 0);
}

float view3d_scenes_drawer_amount_wm(const wmWindowManager *wm)
{
  if (wm == nullptr) {
    return 0.0f;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&const_cast<wmWindowManager *>(wm)->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixar_scenes_drawer_amount");
  return prop != nullptr ? RNA_property_float_get(&wm_ptr, prop) : 0.0f;
}

}  // namespace blender
