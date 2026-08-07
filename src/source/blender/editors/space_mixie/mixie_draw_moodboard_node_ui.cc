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
  char widget[MIXIE_GRAPH_WIDGET_BUF];
  mixie_rna_string_get_clamped(parameter, "label", label, sizeof(label));
  mixie_rna_string_get_clamped(parameter, "widget", widget, sizeof(widget));
  const int parameter_type = RNA_enum_get(parameter, "parameter_type");
  const char *value_property = "value_string";
  ButType button_type = ButType::Text;
  float minimum = 0.0f;
  float maximum = 0.0f;
  if (parameter_type == 1) {
    value_property = "value_integer";
    button_type = STREQ(widget, "slider") ? ButType::NumSlider : ButType::Num;
    minimum = RNA_float_get(parameter, "minimum");
    maximum = RNA_float_get(parameter, "maximum");
  }
  else if (parameter_type == 2) {
    value_property = "value_float";
    button_type = STREQ(widget, "slider") ? ButType::NumSlider : ButType::Num;
    minimum = RNA_float_get(parameter, "minimum");
    maximum = RNA_float_get(parameter, "maximum");
  }
  else if (parameter_type == 3) {
    value_property = "value_boolean";
    button_type = ButType::Checkbox;
  }
  else if (parameter_type == 4) {
    value_property = "value_enum";
    button_type = ButType::Menu;
  }
  return screen_prop_button(block,
                            parameter,
                            value_property,
                            label,
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
  const int panel_width = std::clamp(
      24 + control_count * 132, 420, std::min(900, std::max(420, region->winx - 16)));
  const int panel_height = 58;
  const int panel_x = std::clamp(BLI_rcti_cent_x(&node_region) - panel_width / 2,
                                 8,
                                 std::max(8, region->winx - panel_width - 8));
  const int desired_y = node_region.ymax + 10;
  const int panel_y = std::clamp(desired_y, 8, std::max(8, region->winy - panel_height - 8));
  rctf panel_rect = {float(panel_x),
                     float(panel_x + panel_width),
                     float(panel_y),
                     float(panel_y + panel_height)};
  draw_floating_background(panel_rect);

  const int inset = 12;
  const int gap = 6;
  const int content_x = panel_x + inset;
  const int content_width = panel_width - inset * 2;
  const int field_width = (content_width - gap * (control_count - 1)) / control_count;
  int x = content_x;
  if (show_mode) {
    uiBut *mode = screen_prop_button(
        block, node, "service_key", "Mode", ButType::Menu, x, panel_y + 12, field_width, 34);
    disable_while_submitted(mode, generation_running);
    x += field_width + gap;
  }
  uiBut *model = screen_prop_button(
      block, node, "model", "Model", ButType::Menu, x, panel_y + 12, field_width, 34);
  disable_while_submitted(model, generation_running);
  x += field_width + gap;

  if (parameters) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(node, parameters, &iter);
    while (iter.valid) {
      if (RNA_boolean_get(&iter.ptr, "visible")) {
        uiBut *parameter = add_parameter_button(
            block, &iter.ptr, x, panel_y + 12, field_width, 34);
        disable_while_submitted(parameter, generation_running);
        x += field_width + gap;
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  if (!has_result || state == 0) {
    const int prompt_margin = std::max(14, BLI_rcti_size_x(&node_region) / 24);
    const int prompt_height = 46;
    const int prompt_y = node_region.ymax - prompt_margin - prompt_height;
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
