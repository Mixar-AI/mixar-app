/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Native Scenes drawer queries for Python: hit testing for window-level modal
 * handlers (the agent viewport lock lets presses on the drawer through
 * mid-turn), and which 3D View hosts the drawer (its header draws the toggle;
 * the tab switch snapshots its viewport). */
#pragma once

#ifdef RNA_RUNTIME
#  include "BKE_screen.hh"
#  include "ED_scenes_drawer.hh"
#endif

namespace blender {
#ifdef RNA_RUNTIME
static bool rna_Area_mixar_scenes_drawer_contains(ScrArea *area, const int x, const int y)
{
  const int xy[2] = {x, y};
  if (area->spacetype != SPACE_VIEW3D) {
    return false;
  }
  for (ARegion &region : area->regionbase) {
    if (region.regiontype == VIEW3D_SCENES_DRAWER_REGION_TYPE && region.runtime->visible &&
        !(region.flag & RGN_FLAG_HIDDEN) && view3d_scenes_drawer_contains_xy(area, &region, xy))
    {
      return true;
    }
  }
  return false;
}

static bool rna_Area_mixar_scenes_drawer_hosts(ScrArea *area)
{
  return view3d_scenes_drawer_area_hosts(area);
}
#else
static void rna_def_area_mixar_scenes_drawer(StructRNA *srna)
{
  FunctionRNA *func = RNA_def_function(
      srna, "mixar_scenes_drawer_contains", "rna_Area_mixar_scenes_drawer_contains");
  RNA_def_function_ui_description(
      func, "Test window pixel coordinates against the visible Scenes drawer panel");
  for (const char *axis : {"x", "y"}) {
    PropertyRNA *parm = RNA_def_int(
        func, axis, 0, INT_MIN, INT_MAX, axis, "Window pixel coordinate", INT_MIN, INT_MAX);
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  }
  PropertyRNA *parm = RNA_def_boolean(func, "contains", false, "Contains", "Point is on the Scenes drawer");
  RNA_def_function_return(func, parm);

  func = RNA_def_function(srna, "mixar_scenes_drawer_hosts", "rna_Area_mixar_scenes_drawer_hosts");
  RNA_def_function_ui_description(
      func, "This 3D View is the window's main one, which shows the Scenes drawer");
  parm = RNA_def_boolean(func, "hosts", false, "Hosts", "The Scenes drawer lives in this area");
  RNA_def_function_return(func, parm);
}
#endif
}  // namespace blender
