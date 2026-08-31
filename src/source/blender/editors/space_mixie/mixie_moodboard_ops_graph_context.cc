/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Resolving what a right-click landed on, and opening its menu.
 *
 * Split out of #mixie_moodboard_ops_graph.cc (500-line rule). Selection and
 * dragging answer "what am I manipulating"; this answers "what is under the
 * pointer, and what can it do" -- one pass down the same priority order the
 * canvas draws in, so the menu always belongs to the thing on top.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

namespace blender::ed::mixie {

static wmOperatorStatus graph_context_invoke(bContext *C,
                                             wmOperator * /*op*/,
                                             const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }
  float mouse_x, mouse_y;
  UI_view2d_region_to_view(&region->v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  if (RNA_struct_find_property(&scene_ptr, "mixie_moodboard_context_x")) {
    RNA_float_set(&scene_ptr, "mixie_moodboard_context_x", mouse_x);
    RNA_float_set(&scene_ptr, "mixie_moodboard_context_y", mouse_y);
  }

  moodboard_graph_clear_link_drop_anchor(&scene_ptr);

  rctf rect{};
  int index = moodboard_find_action_node_under_mouse(&scene_ptr, mouse_x, mouse_y, &rect);
  if (index >= 0) {
    moodboard_graph_select_node(&scene_ptr, GRAPH_ACTION, index, nullptr);
  }
  else {
    index = moodboard_find_asset_node_under_mouse(&scene_ptr, mouse_x, mouse_y, &rect);
    if (index >= 0) {
      moodboard_graph_select_node(&scene_ptr, GRAPH_ASSET, index, nullptr);
    }
    else {
      float x, y, scale, width, height;
      index = moodboard_find_image_under_mouse(
          &scene_ptr, mouse_x, mouse_y, &x, &y, &scale, &width, &height);
      if (index >= 0) {
        PropertyRNA *images = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
        PointerRNA image;
        RNA_property_collection_lookup_int(&scene_ptr, images, index, &image);
        if (!RNA_boolean_get(&image, "selected")) {
          moodboard_deselect_all(&scene_ptr);
          RNA_boolean_set(&image, "selected", true);
        }
        moodboard_graph_deselect_nodes(&scene_ptr);
      }
      else {
        index = moodboard_find_link_under_mouse(
            &scene_ptr, &region->v2d, event->mval[0], event->mval[1], 9.0f);
        if (index >= 0) {
          moodboard_graph_select_link(&scene_ptr, index);
        }
      }
    }
  }
  ED_area_tag_redraw(CTX_wm_area(C));

  wmOperatorType *menu_type = WM_operatortype_find("WM_OT_call_menu", false);
  if (!menu_type) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA props;
  WM_operator_properties_create_ptr(&props, menu_type);
  RNA_string_set(&props, "name", "MIXIE_MT_moodboard_context_menu");
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, menu_type, blender::wm::OpCallContext::InvokeRegionWin, &props, event);
  WM_operator_properties_free(&props);
  return status;
}

}  // namespace blender::ed::mixie

void MIXIE_OT_moodboard_context_menu(wmOperatorType *ot)
{
  ot->name = "Moodboard Context Menu";
  ot->idname = "MIXIE_OT_moodboard_context_menu";
  ot->description = "Resolve the node under the pointer and open its context menu";
  ot->invoke = blender::ed::mixie::graph_context_invoke;
  ot->poll = blender::ed::mixie::moodboard_poll;
}
