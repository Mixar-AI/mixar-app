/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Native fields shared by moodboard card composers.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_node_layout.hh"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "BLT_translation.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"

namespace blender::ed::mixie {

ui::Button *moodboard_screen_prop_button(ui::Block *block,
                                         PointerRNA *ptr,
                                         const char *property,
                                         const char *label,
                                         const ui::ButtonType type,
                                         const int x,
                                         const int y,
                                         const int width,
                                         const int height,
                                         const float minimum,
                                         const float maximum)
{
  if (!RNA_struct_find_property(ptr, property)) {
    return nullptr;
  }
  ui::Button *button = ui::uiDefButR(block,
                                     type,
                                     label,
                                     x,
                                     y,
                                     short(width),
                                     short(height),
                                     ptr,
                                     property,
                                     -1,
                                     minimum,
                                     maximum,
                                     nullptr);
  const ui::MixarComponent component = type == ui::ButtonType::Menu ?
                                           ui::MixarComponent::Dropdown :
                                       type == ui::ButtonType::Checkbox ?
                                           ui::MixarComponent::Toggle :
                                       ELEM(type, ui::ButtonType::Num, ui::ButtonType::NumSlider) ?
                                           ui::MixarComponent::Number :
                                           ui::MixarComponent::Input;
  ui::mixar_style_button(button, component, ui::MixarVariant::Primary, UI_SCALE_FAC * 0.65f);
  return button;
}

static void settings_button(ui::Block *block,
                                   const char *node_id,
                                   const char *label,
                                   int x, int y, int width, int height)
{
  ui::Button *button = ui::uiDefIconTextButO(block, ui::ButtonType::But,
      "MIXIE_OT_moodboard_node_settings", wm::OpCallContext::InvokeDefault,
      ICON_PREFERENCES, label, x, y, width, height,
      "All node settings, parameter help and reset");
  ui::mixar_style_button(button, ui::MixarComponent::Action,
                        ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
  RNA_string_set(ui::button_operator_ptr_ensure(button), "node_id", node_id);
}

void moodboard_add_node_settings(ui::Block *block,
                                PointerRNA *node,
                                rcti &controls,
                                const bool running,
                                const char *node_id)
{
  const auto metrics = ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC);
  const int margin = int(metrics.padding), gap = int(metrics.gap);
  const int height = int(metrics.control_height);
  const int left = controls.xmin + margin;
  const int width = BLI_rcti_size_x(&controls) - 2 * margin;
  const int top = controls.ymax - margin;
  const int action = RNA_enum_get(node, "action_type");
  /* ASSEMBLE is local and has per-part controls, not a model. */
  if (action == 11) {
    settings_button(block, node_id, "Attachment settings", left, top - height, width, height);
    controls.ymax = top - height - gap;
    return;
  }
  char model[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(node, "model_label", model, sizeof(model));
  const int settings_width = height;
  ui::Button *model_button = moodboard_screen_prop_button(block, node, "model",
      model[0] ? model : IFACE_("Model unavailable"), ui::ButtonType::Menu,
      left, top - height, width - settings_width - gap, height);
  moodboard_set_node_tooltip(model_button, "Model\n\nChoose this node's model directly. Changing models restores that model's parameter defaults.");
  if (running || !model[0]) {
    ui::button_disable(model_button, running ? "Settings are locked while generating" :
                                              "No compatible model is available");
  }
  settings_button(block, node_id, "", left + width - settings_width,
                  top - height, settings_width, height);
  controls.ymax = top - height - gap;
}

}  // namespace blender::ed::mixie
