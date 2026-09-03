/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup RNA
 *
 * Mixar-specific extensions to the WindowManager RNA.
 *
 * Adds the ``Window.global_areas`` collection so Python can
 * iterate global areas (topbar, statusbar). Upstream Blender
 * intentionally hides these because they're "system" areas not
 * meant to be addressed by addons, but Mixar's onboarding tour
 * needs to tag the topbar's regions for redraw from a Python
 * timer so the highlight border appears on step entry instead of
 * on cursor hover.
 *
 * Structure mirrors upstream rna_*.cc files: helper functions
 * inside ``#ifdef RNA_RUNTIME`` (compiled into Blender runtime via
 * the generated gen files including this .cc), ``RNA_def_*``
 * inside the ``#else`` branch (compiled into the makesrna binary
 * which generates the runtime code).
 *
 * This file briefly also exposed a **report channel** on
 * ``WindowManager`` (``mixar_last_report`` / ``_type`` /
 * ``mixar_report_count``) for the agent island to paint inline; it was
 * removed because Blender's global report list carries unrelated app
 * activity — the agent's own sandboxed script execution above all — so
 * pane messages now come from a dedicated channel that only the pane's
 * own action writes (``agent_bubble/ui/properties/pane_message_props.py``).
 *
 * The table entry for this file is registered in Mixar's overlay
 * of ``makesrna.cc`` (right after ``rna_wm.cc``). That same overlay
 * also injects an extra ``#include "rna_wm_mixar.cc"`` into the
 * generated ``rna_wm_gen.cc`` so the helper functions below are
 * visible to the auto-generated property wrappers for Window
 * (which are emitted into rna_wm_gen.cc because Window itself was
 * registered in rna_wm.cc).
 */

#include <climits>

#include "RNA_define.hh"

#include "rna_internal.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "BLI_listbase.h"

#ifdef RNA_RUNTIME
#  include <cstring>
#  include <string>

#  include "BKE_global.hh"
#  include "BKE_report.hh"

#  include "../../editors/interface/interface_qa_inspect.hh"
#else
#  include "rna_internal_types.hh"
#endif

/* Mixar 5.2 port: namespace wrap. Every include stays ABOVE this line: the
 * generated ``rna_*_gen.cc`` files include this .cc at global scope, and a
 * header pulled in after the wrap opens would land in ``blender::blender``. */
namespace blender {

#ifdef RNA_RUNTIME

static void rna_Window_global_areas_begin(CollectionPropertyIterator *iter, PointerRNA *ptr)
{
  wmWindow *win = (wmWindow *)ptr->data;
  rna_iterator_listbase_begin(iter, ptr, &win->global_areas.areabase, nullptr);
}

/* QA widget-tree dump (see interface_qa_inspect.cc). RNA string reads call
 * ``length`` then ``get`` back-to-back on the same thread, so the length
 * callback serializes into this cache and ``get`` copies + consumes it —
 * every Python read returns a freshly serialized dump, and ``get`` never
 * re-serializes into a buffer ``length`` already sized. */
static std::string g_mixar_qa_ui_dump_cache;

static int rna_WindowManager_mixar_qa_ui_dump_length(PointerRNA *ptr)
{
  const wmWindowManager *wm = (const wmWindowManager *)ptr->data;
  g_mixar_qa_ui_dump_cache = Mixar_ui_qa_inspect_json(wm);
  return int(g_mixar_qa_ui_dump_cache.size());
}

static void rna_WindowManager_mixar_qa_ui_dump_get(PointerRNA * /*ptr*/, char *value)
{
  /* ``value`` is sized by the ``length`` callback above, which is what
   * serializes the dump. Never re-serialize here: the UI may have changed
   * since, and a longer dump would overrun the caller's buffer. A read that
   * somehow skipped ``length`` gets an empty string, not a heap overflow. */
  memcpy(value, g_mixar_qa_ui_dump_cache.c_str(), g_mixar_qa_ui_dump_cache.size() + 1);
  g_mixar_qa_ui_dump_cache.clear();
  g_mixar_qa_ui_dump_cache.shrink_to_fit();
}

/* Defined in windowmanager/intern/wm_event_system.cc (Mixar overlay). */
void Mixar_qa_simulate_file_drop(
    bContext *C, wmWindow *win, int x, int y, const char *filepath);

static void rna_Window_mixar_qa_drop_file(
    wmWindow *win, bContext *C, ReportList *reports, const char *filepath, int x, int y)
{
  if ((G.f & G_FLAG_EVENT_SIMULATE) == 0) {
    BKE_report(reports, RPT_ERROR, "Not running with '--enable-event-simulate' enabled");
    return;
  }
  Mixar_qa_simulate_file_drop(C, win, x, y, filepath);
}

#else /* RNA_RUNTIME */

void RNA_def_wm_mixar(BlenderRNA *brna)
{
  /* This file is part of the ``makesrna`` code generator, not the
   * runtime Blender binary, so ``RNA_struct_find`` (which queries
   * the runtime registry) isn't available here. Look up the
   * Window struct directly in ``brna->structs_map`` — the same
   * map used internally by the RNA define system (a
   * blender::Map<StringRef, StructRNA *> since 5.2). */
  if (brna == nullptr) {
    return;
  }
  StructRNA *srna = brna->structs_map.lookup_default("Window", nullptr);
  if (srna == nullptr) {
    /* Window struct must already be registered; runs after RNA_def_wm. */
    return;
  }

  PropertyRNA *prop = RNA_def_property(srna, "global_areas", PROP_COLLECTION, PROP_NONE);
  RNA_def_property_collection_funcs(prop,
                                    "rna_Window_global_areas_begin",
                                    "rna_iterator_listbase_next",
                                    "rna_iterator_listbase_end",
                                    "rna_iterator_listbase_get",
                                    nullptr,
                                    nullptr,
                                    nullptr,
                                    nullptr);
  RNA_def_property_struct_type(prop, "Area");
  RNA_def_property_clear_flag(prop, PROP_EDITABLE);
  RNA_def_property_ui_text(prop,
                           "Global Areas",
                           "Window-global areas (topbar, statusbar). Mixar extension — "
                           "exposed so onboarding can address the topbar for redraw.");

  /* QA harness: simulated OS file drop at a window coordinate — the one input
   * class ``event_simulate`` cannot express. */
  {
    FunctionRNA *func = RNA_def_function(
        srna, "mixar_qa_drop_file", "rna_Window_mixar_qa_drop_file");
    RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
    RNA_def_function_ui_description(
        func,
        "Simulate an OS file drop onto this window (QA harness; requires "
        "--enable-event-simulate)");
    PropertyRNA *parm = RNA_def_string_file_path(
        func, "filepath", nullptr, 1024, "", "File to drop");
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
    parm = RNA_def_int(func, "x", 0, INT_MIN, INT_MAX, "", "", INT_MIN, INT_MAX);
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
    parm = RNA_def_int(func, "y", 0, INT_MIN, INT_MAX, "", "", INT_MIN, INT_MAX);
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  }

  /* QA harness: JSON dump of every live widget across all windows (rects in
   * window pixels, ready for ``Window.event_simulate``). WindowManager was
   * also registered in rna_wm.cc, so its generated wrappers land in
   * rna_wm_gen.cc where the helpers above are visible via the same include
   * injection that serves ``Window.global_areas``. */
  StructRNA *srna_wm = brna->structs_map.lookup_default("WindowManager", nullptr);
  if (srna_wm != nullptr) {
    prop = RNA_def_property(srna_wm, "mixar_qa_ui_dump", PROP_STRING, PROP_NONE);
    RNA_def_property_string_funcs(prop,
                                  "rna_WindowManager_mixar_qa_ui_dump_get",
                                  "rna_WindowManager_mixar_qa_ui_dump_length",
                                  nullptr);
    RNA_def_property_clear_flag(prop, PROP_EDITABLE);
    RNA_def_property_ui_text(
        prop,
        "QA UI Dump",
        "JSON snapshot of all live UI widgets (labels, operators, properties, "
        "window-space rects, state) for the Mixar QA harness");
  }
}

#endif /* RNA_RUNTIME */

}  // namespace blender
