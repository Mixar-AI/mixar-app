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
 * The table entry for this file is registered in Mixar's overlay
 * of ``makesrna.cc`` (right after ``rna_wm.cc``). That same overlay
 * also injects an extra ``#include "rna_wm_mixar.cc"`` into the
 * generated ``rna_wm_gen.cc`` so the helper functions below are
 * visible to the auto-generated property wrappers for Window
 * (which are emitted into rna_wm_gen.cc because Window itself was
 * registered in rna_wm.cc).
 */

#include "RNA_define.hh"

#include "rna_internal.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "BLI_listbase.h"

#ifdef RNA_RUNTIME

#  include <cstring>
#  include <string>

#  include "../../editors/interface/interface_qa_inspect.hh"

static void rna_Window_global_areas_begin(CollectionPropertyIterator *iter, PointerRNA *ptr)
{
  wmWindow *win = (wmWindow *)ptr->data;
  rna_iterator_listbase_begin(iter, ptr, &win->global_areas.areabase, nullptr);
}

/* QA widget-tree dump (see interface_qa_inspect.cc). RNA string reads call
 * ``length`` then ``get`` back-to-back on the same thread, so the length
 * callback serializes into this cache and ``get`` copies + consumes it —
 * every Python read returns a freshly serialized dump. */
static std::string g_mixar_qa_ui_dump_cache;

static int rna_WindowManager_mixar_qa_ui_dump_length(PointerRNA *ptr)
{
  const wmWindowManager *wm = (const wmWindowManager *)ptr->data;
  g_mixar_qa_ui_dump_cache = Mixar_ui_qa_inspect_json(wm);
  return int(g_mixar_qa_ui_dump_cache.size());
}

static void rna_WindowManager_mixar_qa_ui_dump_get(PointerRNA *ptr, char *value)
{
  if (g_mixar_qa_ui_dump_cache.empty()) {
    const wmWindowManager *wm = (const wmWindowManager *)ptr->data;
    g_mixar_qa_ui_dump_cache = Mixar_ui_qa_inspect_json(wm);
  }
  memcpy(value, g_mixar_qa_ui_dump_cache.c_str(), g_mixar_qa_ui_dump_cache.size() + 1);
  g_mixar_qa_ui_dump_cache.clear();
  g_mixar_qa_ui_dump_cache.shrink_to_fit();
}

#else /* RNA_RUNTIME */

#  include "rna_internal_types.hh"

#  include "BLI_ghash.h"

void RNA_def_wm_mixar(BlenderRNA *brna)
{
  /* This file is part of the ``makesrna`` code generator, not the
   * runtime Blender binary, so ``RNA_struct_find`` (which queries
   * the runtime registry) isn't available here. Look up the
   * Window struct directly in ``brna->structs_map`` — the same
   * GHash used internally by the RNA define system. */
  if (brna == nullptr || brna->structs_map == nullptr) {
    return;
  }
  StructRNA *srna = static_cast<StructRNA *>(
      BLI_ghash_lookup(brna->structs_map, "Window"));
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

  /* QA harness: JSON dump of every live widget across all windows (rects in
   * window pixels, ready for ``Window.event_simulate``). WindowManager was
   * also registered in rna_wm.cc, so its generated wrappers land in
   * rna_wm_gen.cc where the helpers above are visible via the same include
   * injection that serves ``Window.global_areas``. */
  StructRNA *srna_wm = static_cast<StructRNA *>(
      BLI_ghash_lookup(brna->structs_map, "WindowManager"));
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
