/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Read-only RNA property readers for the island's state gather
 * (agent_ui_state.cc). Each returns an empty/false value when the property
 * is missing or of another type, so a scene saved before Python registered
 * the property reads as the default.
 */

#pragma once

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "RNA_access.hh"

namespace blender::agent_ui_rna {

inline void read_string_prop(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy,
                             const bool tail = false)
{
  out[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  char fixed[512];
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), &len);
  if (value) {
    const char *start = value;
    if (tail && len >= out_maxncpy) {
      start += len - out_maxncpy + 1;
      while ((*start & 0xc0) == 0x80) {
        start++;
      }
    }
    BLI_strncpy_utf8(out, start, out_maxncpy);
    if (value != fixed) {
      MEM_delete(value);
    }
  }
}

inline bool read_bool_prop(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return (prop && RNA_property_type(prop) == PROP_BOOLEAN) ?
             RNA_property_boolean_get(ptr, prop) :
             false;
}

/** The enum item's UI name — the label the property itself already carries. */
inline void read_enum_name(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy)
{
  out[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return;
  }
  const int value = RNA_property_enum_get(ptr, prop);
  const char *label = nullptr;
  if (RNA_property_enum_name_gettexted(nullptr, ptr, prop, value, &label) && label) {
    BLI_strncpy(out, label, out_maxncpy);
  }
}

inline bool enum_is(PointerRNA *ptr, const char *name, const char *identifier)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return false;
  }
  const int value = RNA_property_enum_get(ptr, prop);
  const char *ident = nullptr;
  if (RNA_property_enum_identifier(nullptr, ptr, prop, value, &ident) && ident) {
    return STREQ(ident, identifier);
  }
  return false;
}

}  // namespace blender::agent_ui_rna
