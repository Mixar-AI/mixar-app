/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup RNA
 *
 * Mixar per-tab undo: the ``WindowManager`` extension (``mixar_undo_history``,
 * ``mixar_per_tab_undo``, ``mixar_last_undo_document``, ``mixar_undo_push``).
 * Split from ``rna_wm_mixar.cc`` and wired the same way: ``makesrna.cc`` lists
 * it after ``rna_wm_mixar.cc`` and ``#include``s it into ``rna_wm_gen.cc``
 * (the extension owns no struct of its own).
 */

#include <cstring>
#include <string>

#include "RNA_define.hh"

#include "rna_internal.hh"

#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"
#include "BKE_undo_tabs.hh"

#include "ED_mixar_undo.hh"
#include "ED_undo.hh"

#ifdef RNA_RUNTIME

/* Per-tab undo (BKE_undo_tabs.hh): the undo stack as JSON, newest first, with
 * each step's tab and owner-map summary. Same length/get pairing as the QA dump. */
static std::string g_mixar_undo_history_cache;

static int rna_WindowManager_mixar_undo_history_length(PointerRNA *ptr)
{
  const wmWindowManager *wm = (const wmWindowManager *)ptr->data;
  g_mixar_undo_history_cache = blender::BKE_undo_tabs_history_json(wm);
  return int(g_mixar_undo_history_cache.size());
}

static void rna_WindowManager_mixar_undo_history_get(PointerRNA * /*ptr*/, char *value)
{
  memcpy(value, g_mixar_undo_history_cache.c_str(), g_mixar_undo_history_cache.size() + 1);
  g_mixar_undo_history_cache.clear();
  g_mixar_undo_history_cache.shrink_to_fit();
}

static bool rna_WindowManager_mixar_per_tab_undo_get(PointerRNA * /*ptr*/)
{
  return blender::BKE_undo_tabs_enabled();
}

/* M5: the runtime kill switch (the chat module's config key at startup, a
 * developer toggle otherwise). */
static void rna_WindowManager_mixar_per_tab_undo_set(PointerRNA * /*ptr*/, const bool value)
{
  blender::BKE_undo_tabs_set_enabled(value);
}

static bool rna_WindowManager_mixar_last_undo_document_get(PointerRNA * /*ptr*/)
{
  return blender::BKE_undo_tabs_last_walk_was_document();
}

/* A checkpoint pushed on behalf of a scene tab. The agent executor's pushes
 * land from timers while the window shows whatever the user looks at, and a
 * Python `scene=` override is dropped once a window is overridden (and a
 * `view_layer=` one crashes the post-operator update), so the tab is passed
 * explicitly: a one-shot override consumed by BKE_undo_step_tab_annotate. No
 * operator poll: ED_undo_push itself needs no window. */
static bool rna_WindowManager_mixar_undo_push(wmWindowManager * /*wm*/,
                                              bContext *C,
                                              const char *message,
                                              Scene *scene)
{
  if (C == nullptr || message == nullptr) {
    return false;
  }
  const uint32_t tab = (scene != nullptr) ?
                           blender::BKE_undo_tab_uid_for_scene(CTX_data_main(C), scene) :
                           blender::UNDO_TAB_DOCUMENT;
  blender::BKE_undo_tabs_push_override_set(tab);
  /* The tab's checkpoint is a memfile step whatever the window shows; the
   * return value says whether a step was really added (undo steps at zero,
   * no stack in background mode). */
  const bool pushed = blender::ED_undo_push_memfile(C, message);
  blender::BKE_undo_tabs_push_override_set(blender::UNDO_TAB_DOCUMENT);
  return pushed;
}

#else /* RNA_RUNTIME */

void RNA_def_wm_mixar_undo(BlenderRNA *brna)
{
  if (brna == nullptr) {
    return;
  }
  /* Runs after RNA_def_wm: the WindowManager struct is registered. */
  StructRNA *srna_wm = brna->structs_map.lookup_default("WindowManager", nullptr);
  if (srna_wm == nullptr) {
    return;
  }
  PropertyRNA *prop;
    prop = RNA_def_property(srna_wm, "mixar_undo_history", PROP_STRING, PROP_NONE);
    RNA_def_property_string_funcs(prop,
                                  "rna_WindowManager_mixar_undo_history_get",
                                  "rna_WindowManager_mixar_undo_history_length",
                                  nullptr);
    RNA_def_property_clear_flag(prop, PROP_EDITABLE);
    RNA_def_property_ui_text(prop,
                             "Undo History (per-tab)",
                             "JSON of the undo stack, newest first: each step's name, type, "
                             "tab (scene session_uid) and owner-map summary (Mixar per-tab undo)");

    {
      FunctionRNA *func = RNA_def_function(
          srna_wm, "mixar_undo_push", "rna_WindowManager_mixar_undo_push");
      RNA_def_function_flag(func, FUNC_USE_CONTEXT);
      RNA_def_function_ui_description(
          func,
          "Push an undo checkpoint on behalf of a scene tab (Mixar per-tab undo): the step is "
          "tagged with that tab whatever the window shows. Needs no window in the context");
      PropertyRNA *parm = RNA_def_string(func, "message", nullptr, 0, "", "Step name");
      RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
      RNA_def_pointer(func, "scene", "Scene", "", "The tab's scene (None = document)");
      parm = RNA_def_boolean(func, "ok", false, "", "A step was pushed");
      RNA_def_function_return(func, parm);
    }

    prop = RNA_def_property(srna_wm, "mixar_last_undo_document", PROP_BOOLEAN, PROP_NONE);
    RNA_def_property_boolean_funcs(prop, "rna_WindowManager_mixar_last_undo_document_get", nullptr);
    RNA_def_property_clear_flag(prop, PROP_EDITABLE);
    RNA_def_property_ui_text(
        prop, "Last Undo Was Document-Wide", "The undo or redo that ran last walked every tab, not one");

    prop = RNA_def_property(srna_wm, "mixar_per_tab_undo", PROP_BOOLEAN, PROP_NONE);
    RNA_def_property_boolean_funcs(
        prop, "rna_WindowManager_mixar_per_tab_undo_get", "rna_WindowManager_mixar_per_tab_undo_set");
    RNA_def_property_ui_text(
        prop,
        "Per-tab Undo",
        "Undo, redo and the history walk the shown scene tab only (on by default; "
        "MIXAR_PER_TAB_UNDO=0 or the config key per_tab_undo: false turns it off)");
}

#endif /* RNA_RUNTIME */
