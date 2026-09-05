/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Screen-space floating controls for selected moodboard nodes.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BKE_icons.h"
#include "BKE_preview_image.hh"

#include "BLI_string.h"
#include "BLI_vector.hh"

#include "DNA_object_types.h"
#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"

namespace blender::ed::mixie {

struct ObjectPreviewDraw {
  Object *object;
  rcti rect;
};

bool moodboard_view_rect_to_region(View2D *v2d,
                                   ARegion *region,
                                   const rctf &view_rect,
                                   rcti *r_region_rect)
{
  UI_view2d_view_to_region(
      v2d, view_rect.xmin, view_rect.ymin, &r_region_rect->xmin, &r_region_rect->ymin);
  UI_view2d_view_to_region(
      v2d, view_rect.xmax, view_rect.ymax, &r_region_rect->xmax, &r_region_rect->ymax);
  return r_region_rect->xmax > 0 && r_region_rect->xmin < region->winx &&
         r_region_rect->ymax > 0 && r_region_rect->ymin < region->winy &&
         r_region_rect->xmax > r_region_rect->xmin &&
         r_region_rect->ymax > r_region_rect->ymin;
}

static uiBut *screen_prop_button(uiBlock *block,
                                 PointerRNA *ptr,
                                 const char *property,
                                 const char *label,
                                 const ButType type,
                                 const int x,
                                 const int y,
                                 const int width,
                                 const int height,
                                 const float minimum = 0.0f,
                                 const float maximum = 0.0f)
{
  if (!RNA_struct_find_property(ptr, property)) {
    return nullptr;
  }
  return uiDefButR(block,
                   type,
                   0,
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
}

void moodboard_draw_floating_background(const rctf &rect)
{
  const float background[4] = {0.14f, 0.14f, 0.15f, 0.98f};
  const float border[4] = {0.34f, 0.35f, 0.38f, 0.88f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, true, 16.0f, background);
  UI_draw_roundbox_4fv(&rect, false, 16.0f, border);
}

static uiBut *add_parameter_button(uiBlock *block,
                                   PointerRNA *parameter,
                                   const int x,
                                   const int y,
                                   const int width,
                                   const int height)
{
  char label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(parameter, "label", label, sizeof(label));
  const int parameter_type = RNA_enum_get(parameter, "parameter_type");
  const char *value_property = "value_string";
  ButType button_type = ButType::Text;
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
    button_type = ButType::Num;
  }
  else if (parameter_type == 3) {
    value_property = "value_boolean";
    button_type = ButType::Checkbox;
  }
  else if (parameter_type == 4) {
    value_property = "value_enum";
    button_type = ButType::Menu;
  }
  /* Show the VALUE, not the param name. The enum can't self-display (it stores
   * a fragile index; a null label blanks the menu), so the current choice's
   * human label is cached in ``value_label`` (moodboard_graph_properties) and
   * shown here, falling back to the param name only if it isn't populated yet.
   * Numeric/text fields draw the bare value with an empty label. Checkboxes
   * keep their label — a lone tick is meaningless. */
  char value_label[MIXIE_GRAPH_LABEL_BUF];
  const char *display_label = label;
  if (button_type == ButType::Menu) {
    mixie_rna_string_get_clamped(parameter, "value_label", value_label, sizeof(value_label));
    display_label = value_label[0] ? value_label : label;
  }
  else if (ELEM(button_type, ButType::Num, ButType::NumSlider, ButType::Text)) {
    display_label = "";
  }
  return screen_prop_button(block,
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

static void disable_while_submitted(uiBut *button, const bool submitted)
{
  if (button && submitted) {
    UI_but_disable(button, "Settings are locked while this generation is running");
  }
}

static void add_action_toolbar(uiBlock *block,
                               View2D *v2d,
                               ARegion *region,
                               PointerRNA *node,
                               blender::Vector<ObjectPreviewDraw> &object_previews)
{
  rctf node_rect;
  node_rect.xmin = RNA_float_get(node, "position_x");
  node_rect.ymin = RNA_float_get(node, "position_y");
  node_rect.xmax = node_rect.xmin + RNA_float_get(node, "width");
  node_rect.ymax = node_rect.ymin + RNA_float_get(node, "height");
  rcti node_region;
  if (!moodboard_view_rect_to_region(v2d, region, node_rect, &node_region)) {
    return;
  }

  PointerRNA object_ptr = RNA_pointer_get(node, "preview_object");
  if (object_ptr.data) {
    rctf preview_rect = {node_rect.xmin + 6.0f,
                         node_rect.xmax - 6.0f,
                         node_rect.ymin + 6.0f,
                         node_rect.ymax - 6.0f};
    rcti preview_region;
    if (moodboard_view_rect_to_region(v2d, region, preview_rect, &preview_region)) {
      object_previews.append({static_cast<Object *>(object_ptr.data), preview_region});
    }
  }

  if (!RNA_boolean_get(node, "selected")) {
    return;
  }
  /* The toolbar is intentionally screen-sized, like Flora's contextual
   * strip. Hide it before it becomes visually larger than its zoomed tile. */
  if (BLI_rcti_size_x(&node_region) < MOODBOARD_GRAPH_CONTROLS_MIN_PX_X ||
      BLI_rcti_size_y(&node_region) < MOODBOARD_GRAPH_CONTROLS_MIN_PX_Y)
  {
    return;
  }

  PointerRNA preview_ptr = RNA_pointer_get(node, "preview_image");
  const bool has_result = preview_ptr.data || object_ptr.data;
  const int state = RNA_enum_get(node, "state");
  const bool generation_running = ELEM(state, 1, 2);
  PropertyRNA *parameters = RNA_struct_find_property(node, "parameters");
  int parameter_count = 0;
  if (parameters) {
    CollectionPropertyIterator count_iter{};
    RNA_property_collection_begin(node, parameters, &count_iter);
    while (count_iter.valid) {
      parameter_count += RNA_boolean_get(&count_iter.ptr, "visible") ? 1 : 0;
      RNA_property_collection_next(&count_iter);
    }
    RNA_property_collection_end(&count_iter);
  }
  const bool show_mode = RNA_boolean_get(node, "show_mode");
  const int control_count = 1 + (show_mode ? 1 : 0) + parameter_count;
  /* A finished/failed/cancelled node that shows its result hides the tile's
   * prompt + Generate, so the panel carries the way back into the flow. */
  const bool show_rerun = has_result && ELEM(state, 3, 4, 5);

  /* Vertical control panel to the LEFT of the node. Each control occupies its
   * own full-width row so long labels ("Aspect Ratio", model names) stay
   * legible — the previous single horizontal strip forced every control to
   * panel_width / control_count and clipped the text once a handful of
   * parameters were present. A Reset row at the bottom restores catalog
   * defaults. All metrics scale with the UI factor: labels render at
   * UI_SCALE_FAC, so fixed pixel rows clipped every label on high-DPI. */
  const float ui_scale = UI_SCALE_FAC;
  const int inset = int(14 * ui_scale);
  const int row_h = int(32 * ui_scale);
  const int gap = int(6 * ui_scale);
  const int reset_gap = int(12 * ui_scale);
  const int panel_width = int(244 * ui_scale);
  const int field_width = panel_width - inset * 2;
  const int panel_height = inset * 2 + control_count * row_h + (control_count - 1) * gap +
                           (show_rerun ? row_h + gap : 0) + reset_gap + row_h;

  /* Always dock the panel to the LEFT of the node — never flip sides. A
   * side-dependent fallback made image and video nodes disagree on where their
   * controls appeared; clamping (rather than flipping) keeps it reachable when
   * the node is panned against the left edge. */
  const int panel_x = std::clamp(node_region.xmin - 12 - panel_width,
                                 8,
                                 std::max(8, region->winx - panel_width - 8));
  const int panel_y = std::clamp(
      node_region.ymax - panel_height, 8, std::max(8, region->winy - panel_height - 8));
  rctf panel_rect = {float(panel_x),
                     float(panel_x + panel_width),
                     float(panel_y),
                     float(panel_y + panel_height)};
  moodboard_draw_floating_background(panel_rect);

  const int content_x = panel_x + inset;
  /* Rows are laid out top-down; y tracks the bottom edge of the next control. */
  int y = panel_y + panel_height - inset - row_h;
  /* The Mode/Model menus show the SELECTED service/model name from the cached
   * labels (the dynamic enums can't self-display); fall back to the static word
   * only until the catalog populates them. */
  if (show_mode) {
    char mode_label[MIXIE_GRAPH_LABEL_BUF];
    mixie_rna_string_get_clamped(node, "service_label", mode_label, sizeof(mode_label));
    uiBut *mode = screen_prop_button(block,
                                     node,
                                     "service_key",
                                     mode_label[0] ? mode_label : "Mode",
                                     ButType::Menu,
                                     content_x,
                                     y,
                                     field_width,
                                     row_h);
    disable_while_submitted(mode, generation_running);
    y -= row_h + gap;
  }
  char model_label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(node, "model_label", model_label, sizeof(model_label));
  uiBut *model = screen_prop_button(block,
                                    node,
                                    "model",
                                    model_label[0] ? model_label : "Model",
                                    ButType::Menu,
                                    content_x,
                                    y,
                                    field_width,
                                    row_h);
  disable_while_submitted(model, generation_running);
  y -= row_h + gap;

  if (parameters) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(node, parameters, &iter);
    while (iter.valid) {
      if (RNA_boolean_get(&iter.ptr, "visible")) {
        uiBut *parameter = add_parameter_button(
            block, &iter.ptr, content_x, y, field_width, row_h);
        disable_while_submitted(parameter, generation_running);
        y -= row_h + gap;
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  y -= reset_gap - gap;
  char reset_node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(node, "node_id", reset_node_id, sizeof(reset_node_id));
  if (show_rerun) {
    /* Same action as the context menu's "Edit & Run Again": back to DRAFT with
     * the prompt editable — discoverable from the node itself, not only from
     * a right-click. */
    uiBut *rerun = uiDefButO(block,
                             ButType::But,
                             "MIXIE_OT_moodboard_run_action_node",
                             blender::wm::OpCallContext::ExecDefault,
                             "Edit & Run Again",
                             content_x,
                             y,
                             field_width,
                             row_h,
                             nullptr);
    PointerRNA *rerun_props = UI_but_operator_ptr_ensure(rerun);
    RNA_string_set(rerun_props, "node_id", reset_node_id);
    RNA_boolean_set(rerun_props, "edit_before_run", true);
    y -= row_h + gap;
  }
  uiBut *reset = uiDefButO(block,
                           ButType::But,
                           "MIXIE_OT_moodboard_reset_node_params",
                           blender::wm::OpCallContext::ExecDefault,
                           "Reset",
                           content_x,
                           y,
                           field_width,
                           row_h,
                           nullptr);
  RNA_string_set(UI_but_operator_ptr_ensure(reset), "node_id", reset_node_id);
  disable_while_submitted(reset, generation_running);

  if (generation_running) {
    /* The tile already carries the Queued/Generating hint and the glow; the
     * prompt and Generate would draw disabled straight over that text. The
     * one action that makes sense mid-flight is stopping it. */
    const int prompt_margin = std::max(14, BLI_rcti_size_x(&node_region) / 24);
    const int cancel_h = int(36 * UI_SCALE_FAC);
    const int cancel_w = int(118 * UI_SCALE_FAC);
    uiBut *cancel = uiDefButO(block,
                              ButType::But,
                              "MIXIE_OT_moodboard_cancel_action_node",
                              blender::wm::OpCallContext::ExecDefault,
                              "Cancel",
                              node_region.xmax - prompt_margin - cancel_w,
                              node_region.ymin + prompt_margin,
                              cancel_w,
                              cancel_h,
                              nullptr);
    RNA_string_set(UI_but_operator_ptr_ensure(cancel), "node_id", reset_node_id);
  }
  else if (!has_result || state == 0) {
    const int prompt_margin = std::max(14, BLI_rcti_size_x(&node_region) / 24);
    /* UI-factor sized like the left panel: the label renders at UI_SCALE_FAC,
     * so a fixed 118px clipped "Generate" to "Gener..." at high UI scale. */
    const int generate_h = int(36 * UI_SCALE_FAC);
    const int generate_w = int(118 * UI_SCALE_FAC);
    /* Make the prompt a tall multi-line text area: it spans from the top margin
     * down to just above the Generate button. Height comfortably exceeds
     * UI_UNIT_Y * 1.5 at any UI scale, which is what flips the native text
     * button into the word-wrapping, scrollable multi-line renderer
     * (ui_but_is_multiline_text). A fixed short band stayed single-line on
     * high-DPI displays where UI_UNIT_Y is large. */
    /* Mesh-only nodes (Retopology / Mesh Segmentation / Auto Rig) take no text
     * guidance, so they hide the prompt field entirely; the Generate button
     * below is still drawn. */
    if (RNA_boolean_get(node, "show_prompt")) {
      const int prompt_top = node_region.ymax - prompt_margin;
      const int prompt_bottom = node_region.ymin + prompt_margin + generate_h + 12;
      const int prompt_height = std::max(46, prompt_top - prompt_bottom);
      const int prompt_y = prompt_top - prompt_height;
      uiBut *prompt = screen_prop_button(block,
                                         node,
                                         "prompt",
                                         "",
                                         ButType::Text,
                                         node_region.xmin + prompt_margin,
                                         prompt_y,
                                         BLI_rcti_size_x(&node_region) - prompt_margin * 2,
                                         prompt_height);
      if (prompt) {
        UI_but_placeholder_set(prompt, "Describe what you want to create...");
        UI_but_flag_enable(prompt, UI_BUT_TEXTEDIT_UPDATE);
      }
    }

    char node_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));
    uiBut *generate = uiDefButO(block,
                                ButType::But,
                                "MIXIE_OT_moodboard_run_action_node",
                                blender::wm::OpCallContext::ExecDefault,
                                "Generate",
                                node_region.xmax - prompt_margin - generate_w,
                                node_region.ymin + prompt_margin,
                                generate_w,
                                generate_h,
                                nullptr);
    RNA_string_set(UI_but_operator_ptr_ensure(generate), "node_id", node_id);
  }
}

void mixie_draw_moodboard_graph_controls(const bContext *C,
                                         View2D *v2d,
                                         const MoodboardGraphCache *cache)
{
  ARegion *region = CTX_wm_region(C);
  Scene *scene = CTX_data_scene(C);
  if (!region || !scene) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *actions = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_action_nodes");
  if (!actions) {
    return;
  }

  UI_view2d_view_restore(C);
  uiBlock *block = UI_block_begin(
      C, region, "moodboard_floating_node_controls", blender::ui::EmbossType::Emboss);
  blender::Vector<ObjectPreviewDraw> object_previews;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, actions, &iter);
  while (iter.valid) {
    add_action_toolbar(block, v2d, region, &iter.ptr, object_previews);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  mixie_draw_moodboard_selected_media_labels(block, v2d, region, &scene_ptr, cache);

  UI_block_end(C, block);
  UI_block_draw(C, block);
  for (const ObjectPreviewDraw &preview : object_previews) {
    PreviewImage *preview_image = BKE_previewimg_id_ensure(&preview.object->id);
    const int icon_id = BKE_icon_preview_ensure(&preview.object->id, preview_image);
    const int size = std::max(
        16, std::min(BLI_rcti_size_x(&preview.rect), BLI_rcti_size_y(&preview.rect)));
    UI_icon_draw_preview(
        preview.rect.xmin, preview.rect.ymin, icon_id, 1.0f, 1.0f, size);
  }
  UI_view2d_view_ortho(v2d);
}

}  // namespace blender::ed::mixie
