/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Native drawer hit testing for window-level Python modal handlers. */
#pragma once

#ifdef RNA_RUNTIME
#  include "BKE_screen.hh"
#  include "ED_moodboard_drawer.hh"
#endif

namespace blender {
#ifdef RNA_RUNTIME
static bool rna_Area_mixar_moodboard_contains(ScrArea *area, const int x, const int y)
{
  const int xy[2] = {x, y};
  if (area->spacetype != SPACE_VIEW3D) {
    return false;
  }
  for (ARegion &region : area->regionbase) {
    if (region.regiontype == RGN_TYPE_TOOL_PROPS && region.overlap &&
        region.runtime->visible && view3d_moodboard_drawer_contains_xy(area, &region, xy))
    {
      return true;
    }
  }
  return false;
}
#else
static void rna_def_area_mixar_moodboard(StructRNA *srna)
{
  FunctionRNA *func = RNA_def_function(
      srna, "mixar_moodboard_contains", "rna_Area_mixar_moodboard_contains");
  RNA_def_function_ui_description(
      func, "Test window pixel coordinates against the visible Moodboard drawer and grip");
  for (const char *axis : {"x", "y"}) {
    PropertyRNA *parm = RNA_def_int(
        func, axis, 0, INT_MIN, INT_MAX, axis, "Window pixel coordinate", INT_MIN, INT_MAX);
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  }
  PropertyRNA *parm = RNA_def_boolean(func, "contains", false, "Contains", "Point is on Moodboard");
  RNA_def_function_return(func, parm);
}
#endif
}  // namespace blender
