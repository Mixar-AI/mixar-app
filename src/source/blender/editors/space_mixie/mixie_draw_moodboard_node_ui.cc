/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Screen-space floating controls for selected moodboard nodes.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_node_layout.hh"

#include "BKE_icons.hh"
#include "BKE_preview_image.hh"

#include "BLI_string.h"
#include "BLI_vector.hh"

#include "DNA_object_types.h"
#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar.hh"

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

  rcti controls;
  if (!moodboard_node_controls_rect(C, v2d, node, &controls)) {
    return;
  }
  PointerRNA preview_ptr = RNA_pointer_get(node, "preview_image");
  const bool has_result = preview_ptr.data || object_ptr.data;
  const int state = RNA_enum_get(node, "state");
  const bool generation_running = ELEM(state, 1, 2);
  rcti panel;
  const bool expanded = moodboard_node_settings_rect(C, node, node_region, &panel);
  char reset_node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(node, "node_id", reset_node_id, sizeof(reset_node_id));
  if (expanded) {
    moodboard_draw_node_settings(block, node, panel);
  }
  else {
    const int margin = int(8 * UI_SCALE_FAC);
    const int height = int(28 * UI_SCALE_FAC);
    ui::Button *settings = ui::uiDefButO(block,
                                         ui::ButtonType::But,
                                         "MIXIE_OT_moodboard_node_settings",
                                         blender::wm::OpCallContext::InvokeDefault,
                                         "Settings",
                                         controls.xmin + margin,
                                         controls.ymax - margin - height,
                                         BLI_rcti_size_x(&controls) - 2 * margin,
                                         height,
                                         nullptr);
    ui::mixar_style_button(
        settings, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
    RNA_string_set(ui::button_operator_ptr_ensure(settings), "node_id", reset_node_id);
    controls.ymax -= height + margin;
  }
  /* Tile controls use the visible intersection, never an off-canvas edge. */
  node_region = controls;
  if (generation_running) {
    /* The tile already carries the Queued/Generating hint and the glow; the
     * prompt and Generate would draw disabled straight over that text. The
     * one action that makes sense mid-flight is stopping it. */
    const int prompt_margin = int(8 * UI_SCALE_FAC);
    const int cancel_h = int(36 * UI_SCALE_FAC);
    const int cancel_w = int(118 * UI_SCALE_FAC);
    ui::Button *cancel = ui::uiDefButO(block,
                                       ui::ButtonType::But,
                                       "MIXIE_OT_moodboard_cancel_action_node",
                                       blender::wm::OpCallContext::ExecDefault,
                                       "Cancel",
                                       node_region.xmax - prompt_margin - cancel_w,
                                       node_region.ymin + prompt_margin,
                                       cancel_w,
                                       cancel_h,
                                       nullptr);
    ui::mixar_style_button(
        cancel, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
    RNA_string_set(ui::button_operator_ptr_ensure(cancel), "node_id", reset_node_id);
  }
  else if (!has_result || state == 0) {
    const int prompt_margin = int(8 * UI_SCALE_FAC);
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
      const int prompt_bottom = node_region.ymin + prompt_margin + generate_h +
                                int(6 * UI_SCALE_FAC);
      const int prompt_height = prompt_top - prompt_bottom;
      const int prompt_y = prompt_top - prompt_height;
      ui::Button *prompt = moodboard_screen_prop_button(block,
                                                        node,
                                                        "prompt",
                                                        "",
                                                        ui::ButtonType::Text,
                                                        node_region.xmin + prompt_margin,
                                                        prompt_y,
                                                        BLI_rcti_size_x(&node_region) -
                                                            prompt_margin * 2,
                                                        prompt_height);
      if (prompt) {
        ui::button_placeholder_set(prompt, "Describe your idea…");
        ui::button_flag_enable(prompt, ui::BUT_TEXTEDIT_UPDATE);
      }
    }

    char node_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(node, "node_id", node_id, sizeof(node_id));
    ui::Button *generate = ui::uiDefButO(block,
                                         ui::ButtonType::But,
                                         "MIXIE_OT_moodboard_run_action_node",
                                         blender::wm::OpCallContext::ExecDefault,
                                         "Generate",
                                         node_region.xmax - prompt_margin - generate_w,
                                         node_region.ymin + prompt_margin,
                                         generate_w,
                                         generate_h,
                                         nullptr);
    ui::mixar_style_button(generate, ui::MixarComponent::Action, ui::MixarVariant::Primary);
    RNA_string_set(ui::button_operator_ptr_ensure(generate), "node_id", node_id);
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
  blender::Vector<ObjectPreviewDraw> object_previews;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, actions, &iter);
  while (iter.valid) {
    add_action_toolbar(C, block, v2d, region, &iter.ptr, object_previews);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  mixie_draw_moodboard_selected_media_labels(C, block, v2d, region, &scene_ptr, cache);

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
  ui::view2d_view_ortho(v2d);
}

}  // namespace blender::ed::mixie
