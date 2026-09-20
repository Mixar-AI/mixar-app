/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Screen-space floating controls for selected moodboard nodes.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_node_layout.hh"

#include "BLI_string.h"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"

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
  ui::mixar_style_button(button, component);
  return button;
}

void moodboard_draw_floating_background(const rctf &rect)
{
  moodboard_draw_glass_pane(rect, 16.0f);
}

static ui::Button *add_parameter_button(ui::Block *block,
                                        PointerRNA *parameter,
                                        const int x,
                                        const int y,
                                        const int width,
                                        const int height)
{
  char label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(parameter, "label", label, sizeof(label));
  ui::uiDefBut(block,
               ui::ButtonType::Label,
               label,
               x,
               y + height,
               width,
               int(18 * UI_SCALE_FAC),
               nullptr,
               0,
               0,
               nullptr);
  const int parameter_type = RNA_enum_get(parameter, "parameter_type");
  const char *value_property = "value_string";
  ui::ButtonType button_type = ui::ButtonType::Text;
  float minimum = 0.0f;
  float maximum = 0.0f;
  if (parameter_type == 1 || parameter_type == 2) {
    value_property = parameter_type == 1 ? "value_integer" : "value_float";
    minimum = RNA_float_get(parameter, "minimum");
    maximum = RNA_float_get(parameter, "maximum");
    /* Plain manual number field (click to type, drag to nudge), clamped to the
     * catalog range. NOT a slider even when the catalog marks widget="slider":
     * a slider's drag range comes from the shared value_integer/value_float RNA
     * property (which has no per-param range, so ~±INT_MAX), while the catalog
     * min/max only clamp on release — the slider dragged to huge values and
     * snapped back. A correct slider needs a per-param property range (as the
     * N-panel engine builds); the node deliberately uses Num until then. */
    button_type = ui::ButtonType::Num;
  }
  else if (parameter_type == 3) {
    value_property = "value_boolean";
    button_type = ui::ButtonType::Checkbox;
  }
  else if (parameter_type == 4) {
    value_property = "value_enum";
    button_type = ui::ButtonType::Menu;
  }
  /* Show the VALUE, not the param name. The enum can't self-display (it stores
   * a fragile index; a null label blanks the menu), so the current choice's
   * human label is cached in ``value_label`` (moodboard_graph_properties) and
   * shown here, falling back to the param name only if it isn't populated yet.
   * Captions above every field retain the catalog meaning of bare values. */
  char value_label[MIXIE_GRAPH_LABEL_BUF];
  const char *display_label = "";
  if (button_type == ui::ButtonType::Menu) {
    mixie_rna_string_get_clamped(parameter, "value_label", value_label, sizeof(value_label));
    display_label = value_label[0] ? value_label : label;
  }
  else if (ELEM(button_type, ui::ButtonType::Num, ui::ButtonType::NumSlider, ui::ButtonType::Text))
  {
    display_label = "";
  }
  return moodboard_screen_prop_button(block,
                                      parameter,
                                      value_property,
                                      display_label,
                                      button_type,
                                      x,
                                      y,
                                      width,
                                      height,
                                      minimum,
                                      maximum);
}

static void disable_while_submitted(ui::Button *button, const bool submitted)
{
  if (button && submitted) {
    ui::button_disable(button, "Settings are locked while this generation is running");
  }
}

void moodboard_draw_node_settings(ui::Block *block, PointerRNA *node, const rcti &panel)
{
  const float ui_scale = UI_SCALE_FAC;
  const int inset = int(14 * ui_scale);
  const int row_h = int(32 * ui_scale);
  const int caption_h = int(18 * ui_scale);
  const int gap = int(6 * ui_scale);
  const int reset_gap = int(12 * ui_scale);
  const int panel_x = panel.xmin, panel_y = panel.ymin;
  const int panel_height = BLI_rcti_size_y(&panel);
  const int field_width = BLI_rcti_size_x(&panel) - inset * 2;
  const int state = RNA_enum_get(node, "state");
  const bool generation_running = ELEM(state, 1, 2);
  const bool show_mode = RNA_boolean_get(node, "show_mode");
  const bool has_result = RNA_pointer_get(node, "preview_image").data ||
                          RNA_pointer_get(node, "preview_object").data;
  const bool show_rerun = has_result && ELEM(state, 3, 4, 5);
  PropertyRNA *parameters = RNA_struct_find_property(node, "parameters");
  rctf pane = {float(panel.xmin), float(panel.xmax), float(panel.ymin), float(panel.ymax)};
  moodboard_draw_floating_background(pane);
  const int content_x = panel_x + inset;
  /* Rows are laid out top-down; y tracks the bottom edge of the next control.
   */
  int y = panel_y + panel_height - inset - row_h - caption_h;
  /* The Mode/Model menus show the SELECTED service/model name from the cached
   * labels (the dynamic enums can't self-display); fall back to the static word
   * only until the catalog populates them. */
  if (show_mode) {
    ui::uiDefBut(block,
                 ui::ButtonType::Label,
                 "Mode",
                 content_x,
                 y + row_h,
                 field_width,
                 caption_h,
                 nullptr,
                 0,
                 0,
                 nullptr);
    char mode_label[MIXIE_GRAPH_LABEL_BUF];
    mixie_rna_string_get_clamped(node, "service_label", mode_label, sizeof(mode_label));
    ui::Button *mode = moodboard_screen_prop_button(block,
                                                    node,
                                                    "service_key",
                                                    mode_label[0] ? mode_label : "Mode",
                                                    ui::ButtonType::Menu,
                                                    content_x,
                                                    y,
                                                    field_width,
                                                    row_h);
    disable_while_submitted(mode, generation_running);
    y -= row_h + caption_h + gap;
  }
  ui::uiDefBut(block,
               ui::ButtonType::Label,
               "Model",
               content_x,
               y + row_h,
               field_width,
               caption_h,
               nullptr,
               0,
               0,
               nullptr);
  char model_label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(node, "model_label", model_label, sizeof(model_label));
  ui::Button *model = moodboard_screen_prop_button(block,
                                                   node,
                                                   "model",
                                                   model_label[0] ? model_label : "Model",
                                                   ui::ButtonType::Menu,
                                                   content_x,
                                                   y,
                                                   field_width,
                                                   row_h);
  disable_while_submitted(model, generation_running);
  y -= row_h + caption_h + gap;

  if (parameters) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(node, parameters, &iter);
    while (iter.valid) {
      if (RNA_boolean_get(&iter.ptr, "visible")) {
        ui::Button *parameter = add_parameter_button(
            block, &iter.ptr, content_x, y, field_width, row_h);
        disable_while_submitted(parameter, generation_running);
        y -= row_h + caption_h + gap;
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  y += caption_h - (reset_gap - gap);
  char reset_node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(node, "node_id", reset_node_id, sizeof(reset_node_id));
  if (show_rerun) {
    /* Same action as the context menu's "Edit & Run Again": back to DRAFT with
     * the prompt editable — discoverable from the node itself, not only from
     * a right-click. */
    ui::Button *rerun = ui::uiDefButO(block,
                                      ui::ButtonType::But,
                                      "MIXIE_OT_moodboard_run_action_node",
                                      blender::wm::OpCallContext::ExecDefault,
                                      "Edit & Run Again",
                                      content_x,
                                      y,
                                      field_width,
                                      row_h,
                                      nullptr);
    ui::mixar_style_button(
        rerun, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
    RNA_string_set(ui::button_operator_ptr_ensure(rerun), "node_id", reset_node_id);
    RNA_boolean_set(ui::button_operator_ptr_ensure(rerun), "edit_before_run", true);
    y -= row_h + gap;
  }
  ui::Button *reset = ui::uiDefButO(block,
                                    ui::ButtonType::But,
                                    "MIXIE_OT_moodboard_reset_node_params",
                                    blender::wm::OpCallContext::ExecDefault,
                                    "Reset Settings",
                                    content_x,
                                    y,
                                    field_width,
                                    row_h,
                                    nullptr);
  ui::mixar_style_button(
      reset, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
  RNA_string_set(ui::button_operator_ptr_ensure(reset), "node_id", reset_node_id);
  disable_while_submitted(reset, generation_running);
}

}  // namespace blender::ed::mixie
