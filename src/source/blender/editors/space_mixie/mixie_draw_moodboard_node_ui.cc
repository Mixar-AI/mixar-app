/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Screen-space floating controls for selected moodboard nodes.
 *
 * Shared screen-space model/settings, prompt and action controls.
 * Direct model selection and an anchored settings overlay preserve the prompt.
 * Both hosts use the same content bounds and native widgets.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_node_layout.hh"

#include "BKE_icons.hh"
#include "BKE_preview_image.hh"
#include "BKE_scene.hh"

#include <array>
#include <cmath>

#include "BLI_math_geom.h"
#include "BLI_math_vector_types.hh"
#include "BLI_string.h"
#include "../interface/interface_intern.hh"
#include "BLI_vector.hh"

#include "BLT_translation.hh"

#include "DNA_object_types.h"
#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "GPU_state.hh"

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
  ui::view2d_view_to_region(
      v2d, view_rect.xmin, view_rect.ymin, &r_region_rect->xmin, &r_region_rect->ymin);
  ui::view2d_view_to_region(
      v2d, view_rect.xmax, view_rect.ymax, &r_region_rect->xmax, &r_region_rect->ymax);
  return r_region_rect->xmax > 0 && r_region_rect->xmin < region->winx &&
         r_region_rect->ymax > 0 && r_region_rect->ymin < region->winy &&
         r_region_rect->xmax > r_region_rect->xmin && r_region_rect->ymax > r_region_rect->ymin;
}

static void add_action_toolbar(const bContext *C,
                               ui::Block *block,
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
  rcti controls;
  const bool controls_visible = moodboard_node_controls_rect(C, v2d, node, &controls);
  PointerRNA object_ptr = RNA_pointer_get(node, "preview_object");
  PointerRNA preview_ptr = RNA_pointer_get(node, "preview_image");
  const bool has_result = preview_ptr.data || object_ptr.data;
  const int state = RNA_enum_get(node, "state");
  const float header_actions = controls_visible && has_result && ELEM(state, 3, 4, 5) ?
                                   moodboard_node_card_actions_width(preview_ptr.data != nullptr) :
                                   0.0f;
  rctf header_card;
  BLI_rctf_rcti_copy(&header_card, &node_region);
  moodboard_draw_node_header(
      node, header_card, RNA_boolean_get(node, "selected"), header_actions);

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

  if (!controls_visible) {
    return;
  }
  const bool generation_running = ELEM(state, 1, 2);
  char node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));

  /* A finished node shows its RESULT. Its one affordance is the action row
   * floating over the card's top edge; the settings panel and the in-tile
   * prompt fold away until Edit is on. Everything below this point is the edit
   * surface, so a finished node that is not being edited returns here.
   *
   * Export needs MEDIA specifically: `has_result` is also true for a 3D
   * result, which is an object in the scene rather than a board item the
   * moodboard exporter can write. */
  const bool edit_mode = RNA_boolean_get(node, "edit_mode");
  if (has_result && ELEM(state, 3, 4, 5)) {
    moodboard_add_node_card_actions(block,
                                    node_region,
                                    edit_mode,
                                    preview_ptr.data != nullptr,
                                    node_id);
    if (!edit_mode) {
      return;
    }
  }

  moodboard_add_node_settings(block, node, controls, generation_running, node_id);
  /* All controls remain anchored to the full card, including off-canvas edges. */
  moodboard_add_node_tile_controls(
      block, node, controls, generation_running, has_result, state, edit_mode, node_id);
}

static void add_asset_preview(const bContext *C,
                              View2D *v2d,
                              ARegion *region,
                              ui::Block *block,
                              PointerRNA *node,
                              blender::Vector<ObjectPreviewDraw> &object_previews)
{
  rctf rect;
  rect.xmin = RNA_float_get(node, "position_x");
  rect.ymin = RNA_float_get(node, "position_y");
  rect.xmax = rect.xmin + RNA_float_get(node, "width");
  rect.ymax = rect.ymin + RNA_float_get(node, "height");
  rcti card;
  if (!moodboard_view_rect_to_region(v2d, region, rect, &card)) {
    return;
  }
  rctf card_float;
  BLI_rctf_rcti_copy(&card_float, &card);
  moodboard_draw_node_header(node, card_float, RNA_boolean_get(node, "selected"));

  const auto metrics = ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC);
  BLI_rcti_pad(&card, -int(metrics.padding), -int(metrics.padding));
  if (BLI_rcti_size_x(&card) <= 0 || BLI_rcti_size_y(&card) <= 0) {
    return;
  }
  PointerRNA object_ptr = RNA_pointer_get(node, "preview_object");
  if (RNA_boolean_get(node, "scene_mesh_reference")) {
    /* Viewport Delete unlinks the object; this reference can keep its ID alive.
     * Preserve the pointer for Undo, but never paint the orphan as a live mesh. */
    if (object_ptr.data &&
        !BKE_scene_object_find(*CTX_data_main(C), CTX_data_scene(C),
                              static_cast<Object *>(object_ptr.data)))
    {
      object_ptr.data = nullptr;
    }
    /* Same gate as the action toolbar: a button on every card consumes the
     * press before card select/drag, including the centre of an empty card. */
    rcti controls;
    const bool picker_visible = moodboard_node_controls_rect(C, v2d, node, &controls);
    const int height = int(metrics.control_height);
    const int width = std::min(BLI_rcti_size_x(&card), int(200 * UI_SCALE_FAC));
    if (picker_visible && width > 0 && BLI_rcti_size_y(&card) >= height) {
      char node_id[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));
      ui::Button *picker = ui::uiDefIconTextButO(
          block, ui::ButtonType::But, "MIXIE_OT_moodboard_select_mesh",
          wm::OpCallContext::InvokeDefault, ICON_OUTLINER_OB_MESH,
          object_ptr.data ? IFACE_("Change Mesh") : IFACE_("Select Mesh"),
          BLI_rcti_cent_x(&card) - width / 2,
          object_ptr.data ? card.ymin : BLI_rcti_cent_y(&card) - height / 2,
          width, height, TIP_("Choose a mesh from this scene for the Moodboard node"));
      ui::mixar_style_button(picker, ui::MixarComponent::Action,
                            ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
      RNA_string_set(ui::button_operator_ptr_ensure(picker), "node_id", node_id);
      if (object_ptr.data) {
        card.ymin += height + int(metrics.gap);
      }
      else {
        char names[MIXIE_GRAPH_NAMES_BUF];
        mixie_rna_string_get_clamped(node, "object_names", names, sizeof(names));
        const auto style = ui::mixar_text_style(ui::MixarTextRole::Caption, UI_SCALE_FAC);
        const std::string label = ui::mixar_fit_text(
            names[0] ? IFACE_("Mesh removed from scene") : IFACE_("Choose a scene mesh"),
            width, style);
        ui::mixar_label_center(label.c_str(), BLI_rcti_cent_x(&card),
                              BLI_rcti_cent_y(&card) + height + metrics.gap,
                              style, ui::mixar_tokens::mixar_zen().secondary);
      }
    }
    else if (!object_ptr.data) {
      char names[MIXIE_GRAPH_NAMES_BUF];
      mixie_rna_string_get_clamped(node, "object_names", names, sizeof(names));
      const auto style = ui::mixar_text_style(ui::MixarTextRole::Caption, UI_SCALE_FAC);
      const std::string label = ui::mixar_fit_text(
          names[0] ? IFACE_("Mesh removed from scene") : IFACE_("Choose a scene mesh"),
          BLI_rcti_size_x(&card), style);
      ui::mixar_label_center(label.c_str(), BLI_rcti_cent_x(&card), BLI_rcti_cent_y(&card),
                            style, ui::mixar_tokens::mixar_zen().secondary);
    }
    if (!object_ptr.data) {
      return;
    }
  }
  if (object_ptr.data) {
    /* Preview icons are square; centre them inside the same padded card. */
    const int side = std::min(BLI_rcti_size_x(&card), BLI_rcti_size_y(&card));
    if (side < 16) {
      return;
    }
    card.xmin += (BLI_rcti_size_x(&card) - side) / 2;
    card.ymin += (BLI_rcti_size_y(&card) - side) / 2;
    card.xmax = card.xmin + side;
    card.ymax = card.ymin + side;
    object_previews.append({static_cast<Object *>(object_ptr.data), card});
  }
  else {
    const auto style = ui::mixar_text_style(ui::MixarTextRole::Caption, UI_SCALE_FAC);
    const char *message = RNA_boolean_get(node, "scene_mesh_reference") ?
                              IFACE_("Mesh unavailable") : IFACE_("3D asset");
    const std::string label = ui::mixar_fit_text(message, BLI_rcti_size_x(&card), style);
    ui::mixar_label_center(label.c_str(), BLI_rcti_cent_x(&card), BLI_rcti_cent_y(&card),
                           style, ui::mixar_tokens::mixar_zen().secondary);
  }
}

/** The text pass paints after native card controls. Snapshot its rotated
 * footprints so hidden controls cannot consume clicks meant for that text. */
static void exclude_text_overlays(ui::Block *block, PointerRNA *scene, View2D *v2d)
{
  PropertyRNA *boxes = RNA_struct_find_property(scene, "mixie_moodboard_textboxes");
  if (!boxes) {
    return;
  }
  Vector<std::array<float2, 4>> footprints;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene, boxes, &iter);
  while (iter.valid) {
    const float x = RNA_float_get(&iter.ptr, "position_x");
    const float y = RNA_float_get(&iter.ptr, "position_y");
    const float w = RNA_float_get(&iter.ptr, "width");
    const float h = RNA_float_get(&iter.ptr, "height");
    const float angle = RNA_float_get(&iter.ptr, "rotation") * (M_PI / 180.0f);
    const float cosine = std::cos(angle), sine = std::sin(angle);
    std::array<float2, 4> corners = {float2(-w/2, -h/2), float2(w/2, -h/2),
                                     float2(w/2, h/2), float2(-w/2, h/2)};
    for (float2 &p : corners) {
      const float px = x + w/2 + p.x * cosine - p.y * sine;
      const float py = y + h/2 + p.x * sine + p.y * cosine;
      ui::view2d_view_to_region_fl(v2d, px, py, &p.x, &p.y);
    }
    footprints.append(corners);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  if (!footprints.is_empty()) {
    block->mixar_point_is_occluded = [footprints = std::move(footprints)](float x, float y) {
      const float2 point(x, y);
      for (const auto &quad : footprints) {
        if (isect_point_quad_v2(point, quad[0], quad[1], quad[2], quad[3])) {
          return true;
        }
      }
      return false;
    };
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

  ui::view2d_view_restore(C);
  ui::Block *block = ui::block_begin(
      C, region, "moodboard_floating_node_controls", blender::ui::EmbossType::Emboss);
  const rcti canvas = moodboard_canvas_controls_rect(C);
  rctf clip;
  BLI_rctf_rcti_copy(&clip, &canvas);
  ui::mixar_block_clip_set(block, clip);
  int previous_scissor[4];
  GPU_scissor_get(previous_scissor);
  ui::mixar_block_clip_apply(region, block);
  blender::Vector<ObjectPreviewDraw> object_previews;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, actions, &iter);
  while (iter.valid) {
    add_action_toolbar(C, block, v2d, region, &iter.ptr, object_previews);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  PropertyRNA *assets = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_asset_nodes");
  if (assets) {
    RNA_property_collection_begin(&scene_ptr, assets, &iter);
    while (iter.valid) {
      add_asset_preview(C, v2d, region, block, &iter.ptr, object_previews);
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }
  /* A selected FRAME gets its pencil + More row (or its name field) on this
   * same block, so it scales and hit-tests exactly like a card's
   * (mixie_draw_moodboard_frame_actions.cc). */
  moodboard_add_selected_frame_actions(C, block, v2d, region, &scene_ptr);
  /* A selected reference image or movie gets its own Rename / Preview / Export
   * row on this same block, so it scales and hit-tests exactly like a card's
   * (mixie_draw_moodboard_media_actions.cc). */
  moodboard_add_selected_media_actions(C, block, v2d, region, &scene_ptr, cache);

  exclude_text_overlays(block, &scene_ptr, v2d);
  ui::block_end(C, block);
  for (const ObjectPreviewDraw &preview : object_previews) {
    PreviewImage *preview_image = BKE_previewimg_id_ensure(&preview.object->id);
    const int icon_id = BKE_icon_preview_ensure(&preview.object->id, preview_image);
    const int size = std::max(
        16, std::min(BLI_rcti_size_x(&preview.rect), BLI_rcti_size_y(&preview.rect)));
    ui::icon_draw_preview(preview.rect.xmin, preview.rect.ymin, icon_id, 1.0f, 1.0f, size);
  }
  /* Compact Settings and retry controls occupy the tile itself. Keep native
   * controls above mesh thumbnails, just as they are above image previews. */
  ui::block_draw(C, block);
  /* moodboard_media_labels: painted text, so it takes no block of its own and
   * has to run while pixel space is still restored. */
  mixie_draw_moodboard_selected_media_labels(C, v2d, region, &scene_ptr, cache);
  /* Frame names are painted here rather than in the frame pass so that a
   * member drawn inside a frame can never cover the frame's own name. */
  mixie_draw_moodboard_frame_labels(v2d, region, &scene_ptr);
  GPU_scissor(previous_scissor[0], previous_scissor[1],
              previous_scissor[2], previous_scissor[3]);
  ui::view2d_view_ortho(v2d);
}

}  // namespace blender::ed::mixie
