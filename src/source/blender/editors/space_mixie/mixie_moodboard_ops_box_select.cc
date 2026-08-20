/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard box select operator
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Moodboard Box Select Operator
 * \{ */

/**
 * Helper to check if an AABB intersects with the selection box.
 */
static bool box_intersects_aabb(float box_min_x,
                                float box_min_y,
                                float box_max_x,
                                float box_max_y,
                                float obj_min_x,
                                float obj_min_y,
                                float obj_max_x,
                                float obj_max_y)
{
  return !(obj_max_x < box_min_x || obj_min_x > box_max_x || obj_max_y < box_min_y ||
           obj_min_y > box_max_y);
}

/**
 * Apply selection state based on select mode.
 * Returns true if the selection state changed.
 */
static bool apply_selection_mode(PointerRNA *item_ptr,
                                 PropertyRNA *selected_prop,
                                 int select_mode,
                                 bool intersects)
{
  bool current_selected = RNA_property_boolean_get(item_ptr, selected_prop);
  bool new_selected = current_selected;

  if (intersects) {
    switch (select_mode) {
      case SEL_OP_SET:
      case SEL_OP_ADD:
        new_selected = true;
        break;
      case SEL_OP_SUB:
        new_selected = false;
        break;
      case SEL_OP_XOR:
        new_selected = !current_selected;
        break;
    }
  }
  else if (select_mode == SEL_OP_SET) {
    /* SEL_OP_SET deselects items outside the box */
    new_selected = false;
  }

  if (new_selected != current_selected) {
    RNA_property_boolean_set(item_ptr, selected_prop, new_selected);
    return true;
  }
  return false;
}

static bool select_rect_items(PointerRNA *scene_ptr,
                              const char *collection_name,
                              const int select_mode,
                              const float box_min_x,
                              const float box_min_y,
                              const float box_max_x,
                              const float box_max_y)
{
  PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
  if (!collection) {
    return false;
  }

  bool changed = false;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, collection, &iter);
  while (iter.valid) {
    PropertyRNA *selected = RNA_struct_find_property(&iter.ptr, "selected");
    PropertyRNA *position_x = RNA_struct_find_property(&iter.ptr, "position_x");
    PropertyRNA *position_y = RNA_struct_find_property(&iter.ptr, "position_y");
    PropertyRNA *width = RNA_struct_find_property(&iter.ptr, "width");
    PropertyRNA *height = RNA_struct_find_property(&iter.ptr, "height");
    if (selected && position_x && position_y && width && height) {
      const float x = RNA_property_float_get(&iter.ptr, position_x);
      const float y = RNA_property_float_get(&iter.ptr, position_y);
      const bool intersects = box_intersects_aabb(box_min_x,
                                                  box_min_y,
                                                  box_max_x,
                                                  box_max_y,
                                                  x,
                                                  y,
                                                  x + RNA_property_float_get(&iter.ptr, width),
                                                  y + RNA_property_float_get(&iter.ptr, height));
      changed |= apply_selection_mode(&iter.ptr, selected, select_mode, intersects);
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  return changed;
}

static wmOperatorStatus moodboard_box_select_exec(bContext *C, wmOperator *op)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);

  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }

  rcti rect;
  WM_operator_properties_border_to_rcti(op, &rect);

  int select_mode = RNA_enum_get(op->ptr, "mode");

  /* Calculate box dimensions */
  int box_width = std::abs(rect.xmax - rect.xmin);
  int box_height = std::abs(rect.ymax - rect.ymin);
  const int CLICK_THRESHOLD = 10;

  /* Handle click (tiny box) as deselect all */
  if (box_width <= CLICK_THRESHOLD && box_height <= CLICK_THRESHOLD) {
    if (select_mode == SEL_OP_SET) {
      PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
      moodboard_deselect_all(&scene_ptr);
      ED_area_tag_redraw(CTX_wm_area(C));
    }
    return OPERATOR_FINISHED;
  }

  View2D *v2d = &region->v2d;

  /* Convert region coordinates to view coordinates */
  float view_x1, view_y1, view_x2, view_y2;
  ui::view2d_region_to_view(v2d, rect.xmin, rect.ymin, &view_x1, &view_y1);
  ui::view2d_region_to_view(v2d, rect.xmax, rect.ymax, &view_x2, &view_y2);

  /* Normalize box bounds (handle any drag direction) */
  float box_min_x = std::min(view_x1, view_x2);
  float box_max_x = std::max(view_x1, view_x2);
  float box_min_y = std::min(view_y1, view_y2);
  float box_max_y = std::max(view_y1, view_y2);

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  bool changed = false;

  /* Process images */
  PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (img_prop) {
    int image_count = RNA_property_collection_length(&scene_ptr, img_prop);

    for (int i = 0; i < image_count; i++) {
      PointerRNA item_ptr;
      RNA_property_collection_lookup_int(&scene_ptr, img_prop, i, &item_ptr);

      PropertyRNA *embedded_prop = RNA_struct_find_property(&item_ptr, "embedded_node_id");
      if (embedded_prop && RNA_property_string_length(&item_ptr, embedded_prop) > 0) {
        continue;
      }

      PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
      PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
      PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
      PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");
      PropertyRNA *selected_prop = RNA_struct_find_property(&item_ptr, "selected");

      if (!image_prop || !pos_x_prop || !pos_y_prop || !scale_prop || !selected_prop) {
        continue;
      }

      PointerRNA image_ptr = RNA_property_pointer_get(&item_ptr, image_prop);
      if (!image_ptr.data) {
        continue;
      }

      Image *image = static_cast<Image *>(image_ptr.data);
      float pos_x = RNA_property_float_get(&item_ptr, pos_x_prop);
      float pos_y = RNA_property_float_get(&item_ptr, pos_y_prop);
      float scale = RNA_property_float_get(&item_ptr, scale_prop);

      /* Calculate image bounds */
      void *lock;
      ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
      float img_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
      float img_height = (ibuf && ibuf->x > 0 && ibuf->y > 0) ?
                             (MOODBOARD_IMAGE_BASE_SIZE * float(ibuf->y) / float(ibuf->x)) * scale :
                             MOODBOARD_IMAGE_BASE_SIZE * scale;
      BKE_image_release_ibuf(image, ibuf, lock);

      bool intersects = box_intersects_aabb(
          box_min_x, box_min_y, box_max_x, box_max_y, pos_x, pos_y, pos_x + img_width, pos_y + img_height);

      if (apply_selection_mode(&item_ptr, selected_prop, select_mode, intersects)) {
        changed = true;
      }
    }
  }

  /* Text boxes and graph nodes all expose the same rectangular canvas contract. */
  for (const char *collection_name : {"mixie_moodboard_textboxes",
                                      "mixie_moodboard_action_nodes",
                                      "mixie_moodboard_asset_nodes"})
  {
    changed |= select_rect_items(&scene_ptr,
                                 collection_name,
                                 select_mode,
                                 box_min_x,
                                 box_min_y,
                                 box_max_x,
                                 box_max_y);
  }

  /* A box may select multiple nodes, so no single graph node remains active. */
  if (RNA_struct_find_property(&scene_ptr, "mixie_moodboard_active_node_id")) {
    RNA_string_set(&scene_ptr, "mixie_moodboard_active_node_id", "");
  }

  if (changed) {
    WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
    ED_area_tag_redraw(CTX_wm_area(C));
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus moodboard_box_select_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  return WM_gesture_box_invoke(C, op, event);
}

static wmOperatorStatus moodboard_box_select_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  /* Explicitly handle mouse release to ensure gesture ends properly.
   * This is needed because when the box select is invoked from another operator
   * (moodboard_select_image), the gesture modal may not receive the release event correctly. */
  if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
    /* Execute the selection with current gesture state */
    wmOperatorStatus exec_status = moodboard_box_select_exec(C, op);
    WM_gesture_box_cancel(C, op);
    return (exec_status == OPERATOR_FINISHED) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
  }

  return WM_gesture_box_modal(C, op, event);
}

static void moodboard_box_select_cancel(bContext *C, wmOperator *op)
{
  WM_gesture_box_cancel(C, op);
}

/** \} */

}  // namespace blender::ed::mixie


/* Mixar 5.2 port: operator registrations live in namespace blender. */
namespace blender {
/* -------------------------------------------------------------------- */
/** \name Operator Registration (C linkage)
 * \{ */

void MIXIE_OT_moodboard_box_select(wmOperatorType *ot)
{
  ot->name = "Box Select";
  ot->idname = "MIXIE_OT_moodboard_box_select";
  ot->description = "Select multiple moodboard items using box selection";

  ot->invoke = blender::ed::mixie::moodboard_box_select_invoke;
  ot->exec = blender::ed::mixie::moodboard_box_select_exec;
  ot->modal = blender::ed::mixie::moodboard_box_select_modal;
  ot->cancel = blender::ed::mixie::moodboard_box_select_cancel;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_BLOCKING;

  WM_operator_properties_gesture_box(ot);
  WM_operator_properties_select_operation_simple(ot);
}

/** \} */
}  // namespace blender
