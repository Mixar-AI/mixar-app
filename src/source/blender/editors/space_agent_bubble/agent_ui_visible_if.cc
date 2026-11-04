/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * RNA wrapper around the catalog `visible_if` table. Draw paths call
 * #pane_schema_param_visible; missing metadata fails open so older groups
 * still show every chip.
 */

#include <algorithm>
#include <optional>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_utildefines.h"

#include "RNA_access.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_visible_if.hh"

namespace blender {

namespace {

std::optional<std::string> rna_py_str(PointerRNA *group, const char *prop_id)
{
  if (!group || !prop_id || STREQ(prop_id, PANE_VISIBLE_IF_MISSING)) {
    return std::nullopt;
  }
  PropertyRNA *prop = RNA_struct_find_property(group, prop_id);
  if (!prop) {
    return std::nullopt;
  }
  switch (RNA_property_type(prop)) {
    case PROP_ENUM: {
      const int value = RNA_property_enum_get(group, prop);
      const char *ident = nullptr;
      if (RNA_property_enum_identifier(nullptr, group, prop, value, &ident) && ident) {
        return std::string(ident);
      }
      return std::nullopt;
    }
    case PROP_BOOLEAN:
      return RNA_property_boolean_get(group, prop) ? std::string("True") : std::string("False");
    case PROP_INT:
      return std::to_string(RNA_property_int_get(group, prop));
    case PROP_FLOAT:
      return visible_if_detail::float_string(RNA_property_float_get(group, prop));
    case PROP_STRING: {
      char stack[256];
      int len = 0;
      char *buf = RNA_property_string_get_alloc(group, prop, stack, sizeof(stack), &len);
      if (buf == nullptr) {
        return std::nullopt;
      }
      std::string out(buf, size_t(std::max(len, 0)));
      if (buf != stack) {
        MEM_delete(buf);
      }
      return out;
    }
    default:
      return std::nullopt;
  }
}

}  // namespace

bool pane_schema_param_visible(PointerRNA *group, const char *prop_id)
{
  if (!group || !prop_id) {
    return true;
  }
  PropertyRNA *meta = RNA_struct_find_property(group, PANE_VISIBLE_IF_ATTR);
  if (!meta || RNA_property_type(meta) != PROP_STRING) {
    return true;
  }
  char stack[1024];
  int len = 0;
  char *buf = RNA_property_string_get_alloc(group, meta, stack, sizeof(stack), &len);
  if (buf == nullptr) {
    return true;
  }
  const std::string json(buf, size_t(std::max(len, 0)));
  if (buf != stack) {
    MEM_delete(buf);
  }

  MixarVisibleIfTable table;
  if (!pane_visible_if_parse(json, table)) {
    return true;
  }
  return pane_visible_if_matches(table, prop_id, [group](const std::string_view other) {
    return rna_py_str(group, std::string(other).c_str());
  });
}

}  // namespace blender
