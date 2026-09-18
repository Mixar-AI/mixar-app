/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Tooltips for a moodboard node's controls.
 *
 * The node panel's fields draw their VALUE under a caption — a dropdown reads
 * "1K" or "1:1" and a number field just "1" — so the catalog's description and
 * the bounds a plain number field cannot show have nowhere else to go.
 *
 * They cannot come from RNA. Every catalog parameter shares one set of value
 * properties (`value_string`, `value_integer`, …), so `ui::uiDefButR`'s fallback
 * to the property's own description would give every field on every node the
 * same text. The per-parameter label/description/range published by the catalog
 * live in the parameter's own RNA and are composed here instead.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BLI_string.h"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

namespace blender::ed::mixie {

/* The catalog can leave a parameter unbounded, in which case the min/max carry
 * these sentinels (see moodboard_graph_properties.py) and there is no range
 * worth quoting. Compared against a wide margin rather than for equality: the
 * value has been through a float round-trip. */
static const float TOOLTIP_UNBOUNDED = 1.0e17f;

static std::string node_tooltip_func(bContext * /*C*/, void *argN, const StringRef tip)
{
  std::string text = static_cast<const char *>(argN);
  if (!tip.is_empty()) {
    text += '\n';
    text += tip;
  }
  return text;
}

void moodboard_set_node_tooltip(ui::Button *but, const char *text)
{
  if (!but || !text || text[0] == '\0') {
    return;
  }
  /* The button takes ownership of the copy and frees it with the block, which
   * is what makes this safe where a bare `tip` StringRef is not. */
  const size_t size = strlen(text) + 1;
  char *owned = static_cast<char *>(MEM_new_uninitialized(size, __func__));
  memcpy(owned, text, size);
  ui::button_func_tooltip_set(but, node_tooltip_func, owned, MEM_delete_void);
}

/* Trim a trailing zero-tail off a float so an integral bound reads "4", not
 * "4.000000" — catalog bounds are whole numbers far more often than not. */
static void append_number(std::string &text, const float value)
{
  char buffer[64];
  if (value == float(int(value))) {
    BLI_snprintf(buffer, sizeof(buffer), "%d", int(value));
  }
  else {
    BLI_snprintf(buffer, sizeof(buffer), "%g", double(value));
  }
  text += buffer;
}

void moodboard_set_parameter_tooltip(ui::Button *but, PointerRNA *parameter)
{
  if (!but || !parameter) {
    return;
  }
  char label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(parameter, "label", label, sizeof(label));
  char description[MIXIE_GRAPH_DESCRIPTION_BUF];
  mixie_rna_string_get_clamped(parameter, "description", description, sizeof(description));

  std::string text = label;
  if (description[0] != '\0') {
    if (!text.empty()) {
      text += "\n\n";
    }
    text += description;
  }

  /* The value fields are plain number entries whose drag range comes from the
   * shared RNA property, so the catalog's real bounds are invisible until the
   * user overshoots them and the value snaps back. Say them up front. */
  const int parameter_type = RNA_enum_get(parameter, "parameter_type");
  if (ELEM(parameter_type, 1, 2)) {
    const float minimum = RNA_float_get(parameter, "minimum");
    const float maximum = RNA_float_get(parameter, "maximum");
    if (minimum > -TOOLTIP_UNBOUNDED && maximum < TOOLTIP_UNBOUNDED) {
      if (!text.empty()) {
        text += "\n\n";
      }
      text += "Range: ";
      append_number(text, minimum);
      text += " to ";
      append_number(text, maximum);
    }
  }

  if (RNA_boolean_get(parameter, "required")) {
    if (!text.empty()) {
      text += '\n';
    }
    text += "Required";
  }
  moodboard_set_node_tooltip(but, text.c_str());
}

}  // namespace blender::ed::mixie
