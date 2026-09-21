/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * The chat footer's agent model picker.
 *
 * The picker itself is Python's: the catalog projection, the preference
 * state, the menu rows and the PUT all live in the byok module, which mirrors
 * the resolved pick onto the WindowManager. This file reads that mirror and
 * draws ONE button that pops the menu — the same split the Agent island's
 * model chip uses, so both surfaces always agree.
 *
 * The mirror is absent until the Python half registers it (an older build, or
 * the deferred UI pass not having reached it yet). A missing property must
 * never take the footer down with it, so every read goes through
 * #RNA_struct_find_property first: RNA_string_get on a missing property is a
 * null dereference, not a default.
 */

#include <algorithm>
#include <string>

#include "MEM_guardedalloc.h"

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/**
 * Read the picker's WindowManager mirror.
 *
 * \return false when the Python half has not registered it; the caller then
 * draws no model control at all, rather than a button over a menu that does
 * not exist.
 */
bool model_picker_read(const bContext *C, std::string *r_label, bool *r_byok_active)
{
  *r_byok_active = false;
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *label_prop = RNA_struct_find_property(&wm_ptr, "mixar_agent_model_label");
  if (!label_prop || RNA_property_type(label_prop) != PROP_STRING) {
    return false;
  }

  char fixed[256];
  int len = 0;
  char *value = RNA_property_string_get_alloc(&wm_ptr, label_prop, fixed, sizeof(fixed), &len);
  /* No pick made yet still gets a control — "Model" is how it is found. */
  *r_label = (value && value[0]) ? value : "Model";
  if (value && value != fixed) {
    MEM_delete(value);
  }

  PropertyRNA *byok_prop = RNA_struct_find_property(&wm_ptr, "mixar_agent_model_byok_active");
  if (byok_prop && RNA_property_type(byok_prop) == PROP_BOOLEAN) {
    *r_byok_active = RNA_property_boolean_get(&wm_ptr, byok_prop);
  }
  return true;
}

}  // namespace

int footer_model_picker_add(const bContext *C,
                            ui::Block *block,
                            const FooterElementPositions &pos,
                            const int model_x,
                            const int reserved_right,
                            const float scale)
{
  std::string label;
  bool byok_active = false;
  if (!block || !model_picker_read(C, &label, &byok_active)) {
    return model_x;
  }

  /* Narrow footer: clamp to whatever room is left before the attach /
   * screenshot / send buttons, and let the widget elide its own label into
   * that. Below FOOTER_MODEL_BUTTON_MIN_BASE nothing readable survives, so
   * the control is dropped entirely and the attach button keeps its slot —
   * the Agent island still carries a model chip, and the menu is reachable
   * from there. */
  const int spacing = int(FOOTER_BUTTON_SPACING_BASE * scale);
  const int width = std::min(pos.model_dropdown_width,
                             pos.send_btn_x - spacing - reserved_right - model_x);
  if (width < pos.model_dropdown_min_width) {
    return model_x;
  }

  /* Padded like the mode dropdown beside it, so the two read as one rhythm. */
  const std::string padded = " " + label + " ";
  ui::Button *but = ui::uiDefButO(block,
                                  ui::ButtonType::But,
                                  "wm.call_menu",
                                  blender::wm::OpCallContext::InvokeDefault,
                                  padded.c_str(),
                                  model_x,
                                  pos.buttons_y,
                                  short(width),
                                  short(pos.button_row_height),
                                  byok_active ?
                                      "Your own API key is in use, and it decides the "
                                      "model. Open this menu and pick \"Change or remove "
                                      "my API key\" to choose a hosted model again" :
                                      "Choose which model the agent runs on");
  if (but) {
    PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "name", "MIXIE_CHAT_MT_agent_model");
    /* Deliberately NOT disabled while a key is in use. The menu's own rows are
     * greyed by `core/model_menu.build_rows`, but its LAST row opens the AI
     * Provider Settings dialog — and since PR #1562 removed that entry from
     * the account card and the topbar menu, this is the only way to reach it.
     * Disabling the button here would lock a BYOK user out of clearing the
     * key that is disabling their picker. The label paints dim instead, so it
     * still reads as "your pick is not what runs". */
  }

  return model_x + width + spacing;
}

}  // namespace blender
