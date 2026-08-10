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

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"

namespace blender::ed::mixie {

struct ObjectPreviewDraw {
  Object *object;
  rcti rect;
};

static bool view_rect_to_region(View2D *v2d,
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

static void draw_floating_background(const rctf &rect)
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
    /* Always a plain manual number field (ButType::Num — click to type, drag to
     * nudge), never a slider, even when the catalog marks the param
     * widget="slider". A slider stretches the param's full range across the
     * button, which made Duration (catalog max 3000) unusable for a 30s cap and
     * the tiny image-count range fiddly. The node deliberately ignores the
     * slider widget hint for numerics. */
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
  if (!view_rect_to_region(v2d, region, node_rect, &node_region)) {
    return;
  }

  PointerRNA object_ptr = RNA_pointer_get(node, "preview_object");
  if (object_ptr.data) {
    rctf preview_rect = {node_rect.xmin + 6.0f,
                         node_rect.xmax - 6.0f,
                         node_rect.ymin + 6.0f,
                         node_rect.ymax - 6.0f};
    rcti preview_region;
    if (view_rect_to_region(v2d, region, preview_rect, &preview_region)) {
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

  /* Vertical control panel to the LEFT of the node. Each control occupies its
   * own full-width row so long labels ("Aspect Ratio", model names) stay
   * legible — the previous single horizontal strip forced every control to
   * panel_width / control_count and clipped the text once a handful of
   * parameters were present. A Reset row at the bottom restores catalog
   * defaults. */
  const int inset = 14;
  const int row_h = 32;
  const int gap = 6;
  const int reset_gap = 12;
  const int panel_width = 244;
  const int field_width = panel_width - inset * 2;
  const int panel_height =
      inset * 2 + control_count * row_h + (control_count - 1) * gap + reset_gap + row_h;

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
  draw_floating_background(panel_rect);

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

  if (!has_result || state == 0) {
    const int prompt_margin = std::max(14, BLI_rcti_size_x(&node_region) / 24);
    const int generate_h = 36;
    /* Make the prompt a tall multi-line text area: it spans from the top margin
     * down to just above the Generate button. Height comfortably exceeds
     * UI_UNIT_Y * 1.5 at any UI scale, which is what flips the native text
     * button into the word-wrapping, scrollable multi-line renderer
     * (ui_but_is_multiline_text). A fixed short band stayed single-line on
     * high-DPI displays where UI_UNIT_Y is large. */
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
      disable_while_submitted(prompt, generation_running);
    }

    char node_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));
    const char *button_label = generation_running ? "Generating..." : "Generate";
    uiBut *generate = uiDefButO(block,
                                ButType::But,
                                "MIXIE_OT_moodboard_run_action_node",
                                blender::wm::OpCallContext::ExecDefault,
                                button_label,
                                node_region.xmax - prompt_margin - 118,
                                node_region.ymin + prompt_margin,
                                118,
                                36,
                                nullptr);
    RNA_string_set(UI_but_operator_ptr_ensure(generate), "node_id", node_id);
    if (generation_running) {
      UI_but_disable(generate, "Generation is already running");
    }
  }
}

static void add_selected_media_toolbar(uiBlock *block,
                                       View2D *v2d,
                                       ARegion *region,
                                       PointerRNA *scene_ptr)
{
  PropertyRNA *images = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!images) {
    return;
  }
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, images, &iter);
  while (iter.valid) {
    PointerRNA media = iter.ptr;
    PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
    if (!RNA_boolean_get(&media, "selected") ||
        (embedded && RNA_property_string_length(&media, embedded) > 0))
    {
      RNA_property_collection_next(&iter);
      continue;
    }
    PointerRNA image_ptr = RNA_pointer_get(&media, "image");
    Image *image = static_cast<Image *>(image_ptr.data);
    if (!image) {
      RNA_property_collection_next(&iter);
      continue;
    }
    float aspect = 1.0f;
    void *lock = nullptr;
    ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
    if (ibuf && ibuf->x > 0) {
      aspect = float(ibuf->y) / float(ibuf->x);
    }
    BKE_image_release_ibuf(image, ibuf, lock);
    const float width = MOODBOARD_IMAGE_BASE_SIZE * RNA_float_get(&media, "scale");
    rctf media_rect;
    media_rect.xmin = RNA_float_get(&media, "position_x");
    media_rect.ymin = RNA_float_get(&media, "position_y");
    media_rect.xmax = media_rect.xmin + width;
    media_rect.ymax = media_rect.ymin + width * aspect;
    rcti media_region;
    if (view_rect_to_region(v2d, region, media_rect, &media_region)) {
      if (BLI_rcti_size_x(&media_region) < 180 || BLI_rcti_size_y(&media_region) < 120) {
        RNA_property_collection_next(&iter);
        continue;
      }
      const int bar_width = std::clamp(BLI_rcti_size_x(&media_region), 180, 420);
      const int bar_x = std::clamp(BLI_rcti_cent_x(&media_region) - bar_width / 2,
                                   8,
                                   std::max(8, region->winx - bar_width - 8));
      const int bar_y = std::clamp(media_region.ymax + 10, 8, std::max(8, region->winy - 54));
      rctf bar_rect = {float(bar_x), float(bar_x + bar_width), float(bar_y), float(bar_y + 44)};
      draw_floating_background(bar_rect);
      uiDefBut(block,
               ButType::Label,
               0,
               image->source == IMA_SRC_MOVIE ? "Video" : "Image",
               bar_x + 12,
               bar_y + 10,
               bar_width - 24,
               24,
               nullptr,
               0,
               0,
               nullptr);
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

void mixie_draw_moodboard_graph_controls(const bContext *C, View2D *v2d)
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
  add_selected_media_toolbar(block, v2d, region, &scene_ptr);

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
