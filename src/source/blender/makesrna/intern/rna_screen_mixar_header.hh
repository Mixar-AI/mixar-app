/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Overlapping-header hit testing for window-level Python modal handlers. */
#pragma once

#ifdef RNA_RUNTIME
#  include "BKE_screen.hh"
#  include "ED_screen.hh"
#endif

namespace blender {
#ifdef RNA_RUNTIME
/* True when Blender would route an event at window `x, y` to one of the area's
 * visible overlapping headers (the Zen scene toolbar). Uses the event system's
 * own query, so empty header space between controls stays canvas. */
static bool rna_Area_mixar_header_contains(ScrArea *area, const int x, const int y)
{
  const int xy[2] = {x, y};
  for (ARegion &region : area->regionbase) {
    if (ELEM(region.regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOL_HEADER) && region.overlap &&
        region.runtime->visible && ED_region_contains_xy(&region, xy))
    {
      return true;
    }
  }
  return false;
}
#else
static void rna_def_area_mixar_header(StructRNA *srna)
{
  FunctionRNA *func = RNA_def_function(
      srna, "mixar_header_contains", "rna_Area_mixar_header_contains");
  RNA_def_function_ui_description(
      func, "Test window pixel coordinates against the controls of a visible overlapping header");
  for (const char *axis : {"x", "y"}) {
    PropertyRNA *parm = RNA_def_int(
        func, axis, 0, INT_MIN, INT_MAX, axis, "Window pixel coordinate", INT_MIN, INT_MAX);
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  }
  PropertyRNA *parm = RNA_def_boolean(
      func, "contains", false, "Contains", "Point is on an overlapping header control");
  RNA_def_function_return(func, parm);
}
#endif
}  // namespace blender
