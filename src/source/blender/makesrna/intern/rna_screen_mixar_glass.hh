/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Shared native glass for Python POST_PIXEL overlays. Included by rna_screen.cc. */
#pragma once

#ifdef RNA_RUNTIME
#  include "BKE_context.hh"
#  include "BKE_report.hh"
#  include "ED_mixar_glass.hh"
#  include "GPU_context.hh"
#endif

namespace blender {
#ifdef RNA_RUNTIME
static void rna_Region_mixar_draw_glass(ARegion *region,
                                      bContext *C,
                                      ReportList *reports,
                                      const int bounds[4],
                                      float radius,
                                      float alpha)
{
  if (CTX_wm_region(C) != region || !GPU_context_active_get()) {
    BKE_report(reports, RPT_ERROR, "Glass drawing requires the active region's draw callback");
    return;
  }
  const rcti rect = {bounds[0], bounds[2], bounds[1], bounds[3]};
  ui::MixarGlassStyle style;
  /* Notifications carry paragraphs over arbitrary viewport colors. The menu
   * material keeps their text readable even over a white scene background. */
  style.role = ui::MIXAR_GLASS_MENU;
  style.radius = radius;
  style.alpha = alpha;
  style.draw_shadow = true;
  ui::mixar_glass_draw(rect, style);
}
#else
static void rna_def_region_mixar_glass(StructRNA *srna)
{
  FunctionRNA *func = RNA_def_function(srna, "mixar_draw_glass", "rna_Region_mixar_draw_glass");
  RNA_def_function_ui_description(
      func, "Draw the shared neutral glass material during a POST_PIXEL draw callback");
  RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
  PropertyRNA *parm = RNA_def_int_vector(func, "bounds", 4, nullptr, INT_MIN, INT_MAX,
                                        "Bounds", "Region pixels: xmin, ymin, xmax, ymax",
                                        INT_MIN, INT_MAX);
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  RNA_def_float(func, "radius", 12.0f, 0.0f, 10000.0f, "Radius", "Corner radius in pixels",
                0.0f, 1000.0f);
  RNA_def_float(func, "alpha", 1.0f, 0.0f, 1.0f, "Opacity", "Fade the complete material",
                0.0f, 1.0f);
}
#endif
}  // namespace blender
