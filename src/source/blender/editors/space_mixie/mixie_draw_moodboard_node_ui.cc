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
#include "UI_interface_layout.hh"

namespace blender::ed::mixie {

struct ObjectPreviewDraw {
  Object *object;
  rcti rect;
};

/* A mask node's thumbnail, drawn (screen-space) below its resolved control
 * stack after the block is drawn, so it can never overlap the controls. */
struct MaskThumbDraw {
  Image *image;
  rctf bounds;
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

static void draw_floating_background(const rctf &rect)
{
  const float background[4] = {0.14f, 0.14f, 0.15f, 0.98f};
  const float border[4] = {0.34f, 0.35f, 0.38f, 0.88f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, true, 16.0f, background);
  UI_draw_roundbox_4fv(&rect, false, 16.0f, border);
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

static bool node_is_mask_detail(PointerRNA *node)
{
  PropertyRNA *prop = RNA_struct_find_property(node, "action_type");
  if (!prop) {
    return false;
  }
  const char *identifier = nullptr;
  RNA_property_enum_identifier(nullptr, node, prop, RNA_property_enum_get(node, prop), &identifier);
  return identifier && STREQ(identifier, "MASK_DETAIL");
}

static const char *mask_param_value_property(const int parameter_type)
{
  switch (parameter_type) {
    case 1:
      return "value_integer";
    case 2:
      return "value_float";
    case 3:
      return "value_boolean";
    case 4:
      return "value_enum";
    default:
      return "value_string";
  }
}

/* Every inference node's controls are drawn with Blender's real layout engine
 * (the same one the sidebar N-panel uses), so widgets get proper labels,
 * spacing and styling instead of hand-placed buttons. Controls flow from the
 * top of the card. Mask nodes always show their controls (their outputs go to
 * separate nodes, so the card never fills with a result); other node types show
 * controls while selected and still editable, otherwise the result tile fills
 * the card (mask nodes additionally reserve the bottom MOODBOARD_MASK_THUMB_FRACTION
 * band for the mask thumbnail painted by the graph draw pass). */
static void add_action_node_panel(uiBlock *block,
                                  View2D *v2d,
                                  ARegion *region,
                                  PointerRNA *node,
                                  blender::Vector<ObjectPreviewDraw> &object_previews,
                                  blender::Vector<MaskThumbDraw> &mask_thumbs)
{
  rctf node_rect;
  node_rect.xmin = RNA_float_get(node, "position_x");
  node_rect.ymin = RNA_float_get(node, "position_y");
  node_rect.xmax = node_rect.xmin + RNA_float_get(node, "width");
  node_rect.ymax = node_rect.ymin + RNA_float_get(node, "height");
  rcti nr;
  if (!view_rect_to_region(v2d, region, node_rect, &nr)) {
    return;
  }

  const bool is_mask = node_is_mask_detail(node);

  /* Collect the 3D result preview; it is drawn as an icon after the block. */
  PointerRNA object_ptr = RNA_pointer_get(node, "preview_object");
  if (object_ptr.data) {
    rctf preview_rect = {
        node_rect.xmin + 6.0f, node_rect.xmax - 6.0f, node_rect.ymin + 6.0f, node_rect.ymax - 6.0f};
    rcti preview_region;
    if (view_rect_to_region(v2d, region, preview_rect, &preview_region)) {
      object_previews.append({static_cast<Object *>(object_ptr.data), preview_region});
    }
  }

  const int state = RNA_enum_get(node, "state");
  const bool running = ELEM(state, 1, 2);
  PointerRNA preview_ptr = RNA_pointer_get(node, "preview_image");
  const bool has_result = preview_ptr.data || object_ptr.data;

  /* Controls render whenever the node is still editable (draft or has no
   * result yet) — not gated on selection, so every configurable node shows its
   * UI. A finished result node lets its result tile fill the card instead. */
  const bool draw_controls = is_mask || state == 0 || !has_result;
  if (!draw_controls) {
    return;
  }
  /* The control panel is a FIXED screen size — it must not grow or shrink as the
   * canvas is zoomed (only the node card, which is canvas content, scales). The
   * block is built in region space with DPI-sized rows, so the one zoom-varying
   * input was the width; pinning it keeps the whole panel static. Hidden when
   * the card is too small on screen to hold it. */
  const int margin = 14;
  const int panel_width = MOODBOARD_NODE_UI_WIDTH;
  if (BLI_rcti_size_x(&nr) < panel_width + margin * 2 || BLI_rcti_size_y(&nr) < 220) {
    return;
  }
  const int x = nr.xmin + std::max(margin, (BLI_rcti_size_x(&nr) - panel_width) / 2);
  const int y = nr.ymax - margin;
  const int width = panel_width;

  uiLayout &layout = blender::ui::block_layout(block,
                                               blender::ui::LayoutDirection::Vertical,
                                               blender::ui::LayoutType::Panel,
                                               x,
                                               y,
                                               width,
                                               0,
                                               0,
                                               UI_style_get_dpi());
  if (running) {
    layout.enabled_set(false);
  }

  layout.prop(node, "prompt", UI_ITEM_NONE, std::nullopt, ICON_NONE);
  if (RNA_boolean_get(node, "show_mode")) {
    layout.prop(node, "service_key", UI_ITEM_NONE, std::nullopt, ICON_NONE);
  }
  layout.prop(node, "model", UI_ITEM_NONE, std::nullopt, ICON_NONE);
  if (is_mask) {
    layout.prop(node, "views_per_component", UI_ITEM_NONE, std::nullopt, ICON_NONE);
    layout.prop(node, "include_full_context", UI_ITEM_NONE, std::nullopt, ICON_NONE);
  }

  PropertyRNA *parameters = RNA_struct_find_property(node, "parameters");
  if (parameters) {
    CollectionPropertyIterator param_iter{};
    RNA_property_collection_begin(node, parameters, &param_iter);
    while (param_iter.valid) {
      if (RNA_boolean_get(&param_iter.ptr, "visible")) {
        char label[MIXIE_GRAPH_LABEL_BUF];
        mixie_rna_string_get_clamped(&param_iter.ptr, "label", label, sizeof(label));
        const char *value_property =
            mask_param_value_property(RNA_enum_get(&param_iter.ptr, "parameter_type"));
        layout.prop(&param_iter.ptr, value_property, UI_ITEM_NONE, label, ICON_NONE);
      }
      RNA_property_collection_next(&param_iter);
    }
    RNA_property_collection_end(&param_iter);
  }

  layout.separator();
  char node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));
  PointerRNA op_ptr = layout.op(
      "mixie.moodboard_run_action_node", running ? "Generating..." : "Generate", ICON_NONE);
  RNA_string_set(&op_ptr, "node_id", node_id);

  const blender::int2 controls_end = blender::ui::block_layout_resolve(block);

  /* Mask nodes show their mask cutout (or the generated result, if one is
   * embedded) in the card BELOW the resolved control stack. Drawing it here —
   * after resolve, in screen space, from the controls' real bottom edge down to
   * the card bottom — guarantees it never overlaps the controls regardless of
   * how many parameters the model exposes or the zoom level. */
  if (is_mask) {
    PointerRNA prev_ptr = RNA_pointer_get(node, "preview_image");
    PointerRNA mask_ptr = RNA_pointer_get(node, "mask_preview");
    Image *thumb = static_cast<Image *>(prev_ptr.data ? prev_ptr.data : mask_ptr.data);
    const int thumb_top = controls_end.y - 10;
    const int thumb_bottom = nr.ymin + margin;
    if (thumb && thumb_top - thumb_bottom > 48) {
      rctf bounds = {float(nr.xmin + margin),
                     float(nr.xmax - margin),
                     float(thumb_bottom),
                     float(thumb_top)};
      mask_thumbs.append({thumb, bounds});
    }
  }
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
  blender::Vector<MaskThumbDraw> mask_thumbs;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, actions, &iter);
  while (iter.valid) {
    add_action_node_panel(block, v2d, region, &iter.ptr, object_previews, mask_thumbs);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);

  /* 3D asset (result) nodes render their object preview as an icon, same as an
   * action node's 3D result. Collect them for the post-block icon pass. */
  PropertyRNA *asset_nodes = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_asset_nodes");
  if (asset_nodes) {
    CollectionPropertyIterator asset_iter{};
    RNA_property_collection_begin(&scene_ptr, asset_nodes, &asset_iter);
    while (asset_iter.valid) {
      PointerRNA object_ptr = RNA_pointer_get(&asset_iter.ptr, "preview_object");
      if (object_ptr.data) {
        rctf node_rect;
        node_rect.xmin = RNA_float_get(&asset_iter.ptr, "position_x");
        node_rect.ymin = RNA_float_get(&asset_iter.ptr, "position_y");
        node_rect.xmax = node_rect.xmin + RNA_float_get(&asset_iter.ptr, "width");
        node_rect.ymax = node_rect.ymin + RNA_float_get(&asset_iter.ptr, "height");
        rctf preview_rect = {node_rect.xmin + 8.0f,
                             node_rect.xmax - 8.0f,
                             node_rect.ymin + 8.0f,
                             node_rect.ymax - 44.0f};
        rcti preview_region;
        if (view_rect_to_region(v2d, region, preview_rect, &preview_region)) {
          object_previews.append(
              {static_cast<Object *>(object_ptr.data), preview_region});
        }
      }
      RNA_property_collection_next(&asset_iter);
    }
    RNA_property_collection_end(&asset_iter);
  }

  add_selected_media_toolbar(block, v2d, region, &scene_ptr);

  UI_block_end(C, block);
  UI_block_draw(C, block);
  for (const MaskThumbDraw &thumb : mask_thumbs) {
    mixie_draw_moodboard_media_preview(thumb.image, thumb.bounds);
  }
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
