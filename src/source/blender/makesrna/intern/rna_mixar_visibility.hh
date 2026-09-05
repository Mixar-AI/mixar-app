/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#ifdef RNA_RUNTIME
#  include "RE_mixar_visibility.hh"

/* RNA obtains the length before copying. Keep that same snapshot even if a render worker
 * updates the capture between those two calls. */
static thread_local std::string visible_objects_snapshot;

static void rna_RenderSettings_visible_objects_get(PointerRNA *ptr, char *value)
{
  UNUSED_VARS(ptr);
  memcpy(value, visible_objects_snapshot.c_str(), visible_objects_snapshot.size() + 1);
}

static int rna_RenderSettings_visible_objects_length(PointerRNA *ptr)
{
  visible_objects_snapshot = RE_mixar_visibility_json(reinterpret_cast<Scene *>(ptr->owner_id));
  return int(visible_objects_snapshot.size());
}
#else
static void rna_def_mixar_visibility(StructRNA *srna)
{
  PropertyRNA *prop = RNA_def_property(srna, "visible_objects_json", PROP_STRING, PROP_NONE);
  RNA_def_property_clear_flag(prop, PROP_EDITABLE);
  RNA_def_property_string_funcs(prop,
                                "rna_RenderSettings_visible_objects_get",
                                "rna_RenderSettings_visible_objects_length",
                                nullptr);
  RNA_def_property_ui_text(prop,
                           "Visible Objects",
                           "Session-local result of the latest render visibility capture");
}
#endif
