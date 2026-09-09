/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Canvas-space control panel for the selected moodboard node.
 *
 * The separated dropdown card docked to the LEFT of a selected inference node,
 * plus that node's in-tile prompt / Generate / Cancel, are laid out and drawn
 * in the View2D ortho projection, so they scale and pan with the canvas zoom
 * exactly like the node card they belong to. Metrics are canvas units (one
 * canvas unit is one pixel at zoom 1, so the panel is unchanged at zoom 1 and
 * grows/shrinks from there). The 3D-result preview icons (pixel blits) and the
 * floating media label bar stay in SCREEN space as fixed-size overlays, drawn
 * from their own block after pixel space is restored.
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
  uiBut *button = screen_prop_button(block,
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
  /* The field shows its VALUE, not its name, so without this there is nothing
   * on screen saying what "1K" or "1:1" configures. It cannot come from RNA:
   * every parameter shares one set of value properties, so the property's own
   * description is the same generic text on every field of every node. */
  moodboard_set_parameter_tooltip(button, parameter);
  return button;
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
  const bool node_on_screen = moodboard_view_rect_to_region(
      v2d, region, node_rect, &node_region);

  PointerRNA object_ptr = RNA_pointer_get(node, "preview_object");
  if (node_on_screen && object_ptr.data) {
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
  /* No on-screen-size gate. The panel is canvas content now (see the file
   * header), so at extreme zoom-out it simply shrinks with the card it belongs
   * to instead of vanishing — a fixed-size panel dwarfing a zoomed-out card is
   * the only thing the old minimum-on-screen-size gate existed to prevent, and
   * that cannot happen now. `moodboard_view_rect_to_region` above already
   * culled nodes that are entirely off-screen, and the graph pass's
   * `controls_visible` must stay in lockstep with this: it is now `selected`
   * alone, so exactly one of the panel and the centered draft hint draws. */

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

  /* A finished node shows its RESULT. Its one affordance is a floating Edit
   * toggle over the card's top-right corner; the settings panel and the in-tile
   * prompt fold away until that is on. Everything below this point is the edit
   * surface, so a finished node that is not being edited returns here. */
  char node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));
  const bool finished_with_result = has_result && ELEM(state, 3, 4, 5);
  const bool edit_mode = RNA_boolean_get(node, "edit_mode");
  if (finished_with_result) {
    /* Export needs MEDIA specifically: `has_result` is also true for a 3D
     * result, which is an object in the scene rather than a board item the
     * moodboard exporter can write. */
    moodboard_add_node_card_actions(
        block, node_rect, edit_mode, preview_ptr.data != nullptr, node_id);
    if (!edit_mode) {
      return;
    }
  }

  /* Vertical control panel to the LEFT of the node. Each control occupies its
   * own full-width row so long labels ("Aspect Ratio", model names) stay
   * legible — the previous single horizontal strip forced every control to
   * panel_width / control_count and clipped the text once a handful of
   * parameters were present. A Reset row at the bottom restores catalog
   * defaults.
   *
   * Metrics are CANVAS units: one canvas unit is one pixel at zoom 1, so these
   * are the same numbers the old screen-space panel used and the panel is
   * pixel-identical at zoom 1 — it now grows and shrinks from there with the
   * card. They still scale with UI_SCALE_FAC, which is the DPI/UI factor and
   * orthogonal to zoom: labels render at UI_SCALE_FAC, so fixed rows clipped
   * every label on high-DPI. */
  const float ui_scale = UI_SCALE_FAC;
  const int inset = int(14 * ui_scale);
  const int gap = int(6 * ui_scale);
  const int reset_gap = int(12 * ui_scale);
  /* Width is HALF THE CARD's, not a DPI-scaled constant. The card is a plain
   * canvas rectangle and does not scale with UI_SCALE_FAC, so a fixed
   * `244 * ui_scale` panel crept up on the card's own width as the UI factor
   * rose — on a high-DPI display the "settings" card was nearly as wide as the
   * node it configures. Tying it to the card keeps the proportion fixed at
   * every DPI and makes the resize grip scale the panel with the node.
   *
   * The floor exists because text does NOT scale with the card: its size comes
   * from the style × UI_SCALE_FAC, so at the card's minimum width half of it is
   * too narrow for a model name and the panel stops shrinking rather than
   * clipping labels. Insets and gaps stay purely DPI-driven for the same
   * reason; only the row height is negotiated against the card (below). */
  const int panel_width = std::max(
      int(BLI_rctf_size_x(&node_rect) * MOODBOARD_NODE_PANEL_WIDTH_RATIO),
      int(MOODBOARD_NODE_PANEL_MIN_TEXT_W * ui_scale));
  const int field_width = panel_width - inset * 2;

  /* Height follows the card the same way the width does. The rows are sized to
   * land on the target rather than the panel being stretched or clipped to it:
   * the fixed chrome (insets, the gaps between controls, the Reset separator)
   * comes off the top, and what is left is shared between the control rows and
   * the Reset row. Clamped at both ends -- never taller than the natural row
   * height (a two-control panel should not have enormous rows) and never below
   * what a line of text needs, so a node with many parameters overflows the
   * target instead of crushing its rows into illegibility. */
  const int rows = control_count + 1; /* the controls, plus Reset */
  const int chrome = inset * 2 + (control_count - 1) * gap + reset_gap;
  const int target_height = int(BLI_rctf_size_y(&node_rect) *
                                MOODBOARD_NODE_PANEL_HEIGHT_RATIO);
  const int row_h = std::clamp((target_height - chrome) / std::max(rows, 1),
                               int(MOODBOARD_NODE_PANEL_MIN_ROW_H * ui_scale),
                               int(32 * ui_scale));
  const int panel_height = chrome + rows * row_h;

  /* Always dock the panel to the LEFT of the node — never flip sides. A
   * side-dependent fallback made image and video nodes disagree on where their
   * controls appeared. The old screen-space clamp into the region is gone with
   * the screen-space layout: the panel is part of the graph now, so a node
   * pushed against the viewport edge takes its controls off-screen with it and
   * panning brings both back, exactly like a node editor. */
  const int panel_x = int(node_rect.xmin) - int(12 * ui_scale) - panel_width;
  const int panel_y = int(node_rect.ymax) - panel_height;
  rctf panel_rect = {float(panel_x),
                     float(panel_x + panel_width),
                     float(panel_y),
                     float(panel_y + panel_height)};
  /* Cull on the PANEL's own footprint as well as the card's. The panel is
   * docked to the LEFT of the card, so a node pushed just past the right edge
   * of the viewport can still have its controls fully on screen — culling on
   * the card alone made them pop out early. */
  rcti panel_region;
  if (!node_on_screen &&
      !moodboard_view_rect_to_region(v2d, region, panel_rect, &panel_region))
  {
    return;
  }
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
    /* Like the parameter fields, this draws the SELECTED value rather than the
     * word "Mode", so the tooltip carries the field's identity. */
    std::string mode_tip = "Mode\n\nGeneration service this node runs on.";
    if (mode_label[0]) {
      mode_tip += "\nCurrently: ";
      mode_tip += mode_label;
    }
    moodboard_set_node_tooltip(mode, mode_tip.c_str());
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
  std::string model_tip = "Model\n\nThe model this node generates with.";
  if (model_label[0]) {
    model_tip += "\nCurrently: ";
    model_tip += model_label;
  }
  moodboard_set_node_tooltip(model, model_tip.c_str());
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
  RNA_string_set(UI_but_operator_ptr_ensure(reset), "node_id", node_id);
  disable_while_submitted(reset, generation_running);

  /* Controls drawn INSIDE the tile (prompt / Generate, or Cancel while a
   * generation is in flight) live in their own unit — see
   * mixie_draw_moodboard_node_tile_controls.cc. */
  moodboard_add_node_tile_controls(
      block, node, node_rect, generation_running, has_result, state, edit_mode, node_id);
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

  /* Node control panels are CANVAS content. We are called from the graph pass,
   * which is already inside the View2D ortho projection, and we deliberately do
   * NOT restore pixel space here: UI_block_begin captures the current (zoomed)
   * projection into block->winmat, so the widgets scale and pan with the canvas
   * like a node editor's do — and, because hit-testing inverts that same
   * matrix, clicks land on them at every zoom. */
  uiBlock *block = UI_block_begin(
      C, region, "moodboard_node_controls", blender::ui::EmbossType::Emboss);
  blender::Vector<ObjectPreviewDraw> object_previews;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, actions, &iter);
  while (iter.valid) {
    add_action_toolbar(block, v2d, region, &iter.ptr, object_previews);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  UI_block_end(C, block);
  UI_block_draw(C, block);

  /* Screen-space pass. Icon previews are pixel blits and a selected media's
   * name is painted at a fixed point size, so both stay a constant screen size
   * — they are NOT part of the canvas block above. Restore pixel space for
   * them, then put back the View2D ortho our caller expects on return. */
  UI_view2d_view_restore(C);
  for (const ObjectPreviewDraw &preview : object_previews) {
    PreviewImage *preview_image = BKE_previewimg_id_ensure(&preview.object->id);
    const int icon_id = BKE_icon_preview_ensure(&preview.object->id, preview_image);
    const int size = std::max(
        16, std::min(BLI_rcti_size_x(&preview.rect), BLI_rcti_size_y(&preview.rect)));
    UI_icon_draw_preview(
        preview.rect.xmin, preview.rect.ymin, icon_id, 1.0f, 1.0f, size);
  }
  /* moodboard_media_labels: painted text, so no uiBlock of its own. */
  mixie_draw_moodboard_selected_media_labels(v2d, region, &scene_ptr, cache);
  UI_view2d_view_ortho(v2d);
}

}  // namespace blender::ed::mixie
