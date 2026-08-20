/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard select and move operator
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Selection Helper Functions
 * \{ */

/**
 * Gather all selection state into a context struct.
 * Returns a fully populated MoodboardSelectionContext for the clicked element.
 */
static MoodboardSelectionContext get_selection_context(PointerRNA *scene_ptr,
                                                        int clicked_index,
                                                        MoodboardElementType element_type,
                                                        const wmEvent *event,
                                                        wmOperator *op)
{
  MoodboardSelectionContext ctx = {};
  ctx.scene_ptr = scene_ptr;
  ctx.clicked_index = clicked_index;
  ctx.element_type = element_type;
  ctx.extend_mode = RNA_boolean_get(op->ptr, "extend");
  ctx.is_double_click = (event->val == KM_DBL_CLICK);
  ctx.group_index = -1;
  ctx.is_image_selected = false;
  ctx.is_group_selected = false;
  ctx.sel_prop = nullptr;

  const char *collection_name = (element_type == MOODBOARD_ELEMENT_TEXTBOX) ?
                                    "mixie_moodboard_textboxes" :
                                    "mixie_moodboard_images";
  PropertyRNA *collection_prop = RNA_struct_find_property(scene_ptr, collection_name);
  if (!collection_prop) {
    return ctx;
  }

  RNA_property_collection_lookup_int(scene_ptr, collection_prop, clicked_index, &ctx.item_ptr);
  ctx.sel_prop = RNA_struct_find_property(&ctx.item_ptr, "selected");

  if (ctx.sel_prop) {
    ctx.is_image_selected = RNA_property_boolean_get(&ctx.item_ptr, ctx.sel_prop);
  }

  /* Check group membership and selection for images */
  if (element_type == MOODBOARD_ELEMENT_IMAGE) {
    PropertyRNA *group_idx_prop = RNA_struct_find_property(&ctx.item_ptr, "group_index");
    if (group_idx_prop) {
      ctx.group_index = RNA_property_int_get(&ctx.item_ptr, group_idx_prop);

      if (ctx.group_index >= 0) {
        PropertyRNA *groups_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_groups");
        if (groups_prop) {
          PointerRNA group_ptr;
          RNA_property_collection_lookup_int(scene_ptr, groups_prop, ctx.group_index, &group_ptr);
          PropertyRNA *group_sel_prop = RNA_struct_find_property(&group_ptr, "selected");
          if (group_sel_prop) {
            ctx.is_group_selected = RNA_property_boolean_get(&group_ptr, group_sel_prop);
          }
        }
      }
    }
  }

  return ctx;
}

/** Double-click on image in selected group: deselect group, select individual image */
static void handle_double_click_grouped_image(MoodboardSelectionContext &ctx)
{
  PropertyRNA *groups_prop = RNA_struct_find_property(ctx.scene_ptr, "mixie_moodboard_groups");
  if (groups_prop) {
    PointerRNA group_ptr;
    RNA_property_collection_lookup_int(ctx.scene_ptr, groups_prop, ctx.group_index, &group_ptr);
    PropertyRNA *group_sel_prop = RNA_struct_find_property(&group_ptr, "selected");
    if (group_sel_prop) {
      RNA_property_boolean_set(&group_ptr, group_sel_prop, false);
    }
  }

  if (ctx.sel_prop) {
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, true);
  }
}

/** Double-click on individually selected image: deselect it */
static void handle_double_click_selected_image(MoodboardSelectionContext &ctx)
{
  if (ctx.sel_prop) {
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, false);
  }
}

/** Double-click on non-grouped unselected image: deselect all, select this image */
static void handle_double_click_ungrouped_image(MoodboardSelectionContext &ctx)
{
  moodboard_deselect_all(ctx.scene_ptr);
  if (ctx.sel_prop) {
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, true);
  }
}

/** Extend mode (Shift+click) on ungrouped item: toggle selection */
static void handle_extend_click_ungrouped(MoodboardSelectionContext &ctx)
{
  if (ctx.sel_prop) {
    bool current_state = RNA_property_boolean_get(&ctx.item_ptr, ctx.sel_prop);
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, !current_state);
  }
}

/** Single click on grouped image: deselect all, select the group */
static void handle_click_select_group(MoodboardSelectionContext &ctx)
{
  moodboard_deselect_all(ctx.scene_ptr);

  PropertyRNA *groups_prop = RNA_struct_find_property(ctx.scene_ptr, "mixie_moodboard_groups");
  if (groups_prop) {
    PointerRNA group_ptr;
    RNA_property_collection_lookup_int(ctx.scene_ptr, groups_prop, ctx.group_index, &group_ptr);
    PropertyRNA *group_sel_prop = RNA_struct_find_property(&group_ptr, "selected");
    if (group_sel_prop) {
      RNA_property_boolean_set(&group_ptr, group_sel_prop, true);
    }
  }
}

/** Single click on non-grouped image: deselect all, select this image */
static void handle_click_select_image(MoodboardSelectionContext &ctx)
{
  moodboard_deselect_all(ctx.scene_ptr);
  if (ctx.sel_prop) {
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, true);
  }
}

/**
 * Main dispatch function for moodboard selection.
 * Handles all selection logic based on the context.
 */
static void update_moodboard_selection(MoodboardSelectionContext &ctx)
{
  /* Group handles - already selected, nothing to do */
  if (ctx.element_type == MOODBOARD_ELEMENT_GROUP) {
    return;
  }

  /* Double-click actions */
  if (ctx.is_double_click) {
    if (ctx.group_index >= 0 && ctx.is_group_selected && !ctx.is_image_selected) {
      handle_double_click_grouped_image(ctx);
    }
    else if (ctx.is_image_selected) {
      handle_double_click_selected_image(ctx);
    }
    else if (ctx.group_index < 0) {
      handle_double_click_ungrouped_image(ctx);
    }
    return;
  }

  /* Extend mode (Shift+click) */
  if (ctx.extend_mode) {
    if (ctx.group_index < 0) {
      handle_extend_click_ungrouped(ctx);
    }
    /* Grouped items: do nothing on extend */
    return;
  }

  /* Normal single click - if already selected, do nothing (allow drag) */
  if (ctx.is_image_selected || ctx.is_group_selected) {
    return;
  }

  /* Select based on group membership */
  if (ctx.group_index >= 0) {
    handle_click_select_group(ctx);
  }
  else {
    handle_click_select_image(ctx);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Select and Move Image Operator
 * \{ */

static wmOperatorStatus moodboard_select_image_invoke(bContext *C,
                                                      wmOperator *op,
                                                      const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);

  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }

  View2D *v2d = &region->v2d;

  float mouse_x, mouse_y;
  ui::view2d_region_to_view(v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  float clicked_pos_x, clicked_pos_y, clicked_scale, clicked_width, clicked_height;
  int clicked_index = -1;
  MoodboardElementType element_type = MOODBOARD_ELEMENT_IMAGE;
  int clicked_handle = -1;

  /* FIRST: Check if click is on a resize handle of any selected element.
   * This must be done before checking for elements under mouse, because
   * handles extend outside the element bounds. */
  float handle_tolerance = MOODBOARD_HANDLE_TOLERANCE_PX / ui::view2d_scale_get_x(v2d);
  clicked_handle = moodboard_find_resize_handle_at_mouse(&scene_ptr,
                                                          mouse_x,
                                                          mouse_y,
                                                          handle_tolerance,
                                                          &clicked_index,
                                                          &element_type,
                                                          &clicked_pos_x,
                                                          &clicked_pos_y,
                                                          &clicked_scale,
                                                          &clicked_width,
                                                          &clicked_height);

  /* If no handle was clicked, check for elements under the mouse */
  if (clicked_handle == -1) {
    int clicked_textbox_index = moodboard_find_textbox_under_mouse(
        &scene_ptr, mouse_x, mouse_y, &clicked_pos_x, &clicked_pos_y, &clicked_width, &clicked_height);

    if (clicked_textbox_index != -1) {
      clicked_index = clicked_textbox_index;
      element_type = MOODBOARD_ELEMENT_TEXTBOX;
      clicked_scale = 1.0f;
    }
    else {
      clicked_index = moodboard_find_image_under_mouse(&scene_ptr,
                                                       mouse_x,
                                                       mouse_y,
                                                       &clicked_pos_x,
                                                       &clicked_pos_y,
                                                       &clicked_scale,
                                                       &clicked_width,
                                                       &clicked_height);
      element_type = MOODBOARD_ELEMENT_IMAGE;
    }
  }

  /* Check for double-click on text box to edit */
  if (clicked_index != -1 && element_type == MOODBOARD_ELEMENT_TEXTBOX &&
      event->val == KM_DBL_CLICK && clicked_handle == -1)
  {
    wmOperatorType *ot = WM_operatortype_find("MIXIE_OT_moodboard_edit_textbox", false);
    if (ot) {
      PointerRNA ptr = WM_operator_properties_create_ptr(ot);
      RNA_int_set(&ptr, "index", clicked_index);

      /* Pass the real double-click event (not nullptr) so the edit operator's
       * modal handler attaches reliably — a null event leaves the inline text
       * modal without keyboard focus. */
      WM_operator_name_call_ptr(C, ot, blender::wm::OpCallContext::InvokeDefault, &ptr, event);
      WM_operator_properties_free(&ptr);

      return OPERATOR_FINISHED;
    }
  }

  /* A movie keeps the normal image-like canvas interactions everywhere
   * except its centered playback affordance. Single-clicking that button,
   * or double-clicking anywhere on the movie, toggles playback directly in
   * its moodboard block without interfering with drag/resize gestures. */
  if (clicked_index != -1 && element_type == MOODBOARD_ELEMENT_IMAGE &&
      clicked_handle == -1 && moodboard_item_is_video(&scene_ptr, clicked_index))
  {
    const float center_x = clicked_pos_x + clicked_width * 0.5f;
    const float center_y = clicked_pos_y + clicked_height * 0.5f;
    const float view_scale = std::max(ui::view2d_scale_get_x(v2d), 0.001f);
    const float play_radius = MOODBOARD_VIDEO_PLAY_RADIUS_PX / view_scale;
    const float delta_x = mouse_x - center_x;
    const float delta_y = mouse_y - center_y;
    const bool play_button_hit = delta_x * delta_x + delta_y * delta_y <=
                                 play_radius * play_radius;

    if (event->val == KM_DBL_CLICK || play_button_hit) {
      return moodboard_toggle_video_playback(C, &scene_ptr, clicked_index, op->reports) ?
                 OPERATOR_FINISHED :
                 OPERATOR_CANCELLED;
    }
  }

  if (clicked_index == -1) {
    bool extend = RNA_boolean_get(op->ptr, "extend");

    if (!extend) {
      moodboard_deselect_all(&scene_ptr);
      ED_area_tag_redraw(CTX_wm_area(C));
    }

    wmOperatorType *ot = WM_operatortype_find("MIXIE_OT_moodboard_box_select", false);
    if (ot) {
      PointerRNA ptr = WM_operator_properties_create_ptr(ot);
      RNA_boolean_set(&ptr, "wait_for_input", false);
      RNA_enum_set(&ptr, "mode", extend ? SEL_OP_ADD : SEL_OP_SET);

      wmOperatorStatus status = WM_operator_name_call_ptr(
          C, ot, blender::wm::OpCallContext::InvokeDefault, &ptr, event);

      WM_operator_properties_free(&ptr);
      return status;
    }

    return OPERATOR_FINISHED;
  }

  /* Update selection using helper functions */
  if (element_type != MOODBOARD_ELEMENT_GROUP) {
    MoodboardSelectionContext ctx = get_selection_context(
        &scene_ptr, clicked_index, element_type, event, op);
    if (ctx.sel_prop) {
      update_moodboard_selection(ctx);
    }
  }

  ED_area_tag_redraw(CTX_wm_area(C));

  /* Allocate operator custom data */
  MoodboardMoveData *move_data = MEM_new<MoodboardMoveData>("MoodboardMoveData");
  if (!move_data) {
    return OPERATOR_CANCELLED;
  }
  move_data->element_type = element_type;
  move_data->image_index = clicked_index;
  move_data->initial_mouse_x = mouse_x;
  move_data->initial_mouse_y = mouse_y;
  move_data->initial_pos_x = clicked_pos_x;
  move_data->initial_pos_y = clicked_pos_y;
  move_data->initial_scale = clicked_scale;
  move_data->initial_width = clicked_width;
  move_data->initial_height = clicked_height;
  move_data->aspect_ratio = (clicked_width > 0.001f) ? (clicked_height / clicked_width) : 1.0f;
  move_data->is_dragging = false;
  move_data->is_resizing = (clicked_handle != -1);
  move_data->resize_handle = clicked_handle;
  move_data->has_stored_initial_positions = false;
  move_data->selected_count = 0;
  move_data->initial_font_size = 0;
  move_data->initial_rotation = 0.0f;

  /* Capture initial rotation and font size for resize operations */
  if (clicked_handle != -1) {
    const char *coll_name = (element_type == MOODBOARD_ELEMENT_TEXTBOX) ?
                                "mixie_moodboard_textboxes" :
                                "mixie_moodboard_images";
    PropertyRNA *coll_prop = RNA_struct_find_property(&scene_ptr, coll_name);
    if (coll_prop) {
      PointerRNA elem_ptr;
      RNA_property_collection_lookup_int(&scene_ptr, coll_prop, clicked_index, &elem_ptr);
      PropertyRNA *rot_prop = RNA_struct_find_property(&elem_ptr, "rotation");
      if (rot_prop) {
        move_data->initial_rotation = RNA_property_float_get(&elem_ptr, rot_prop);
      }
      if (element_type == MOODBOARD_ELEMENT_TEXTBOX) {
        PropertyRNA *fs_prop = RNA_struct_find_property(&elem_ptr, "font_size");
        if (fs_prop) {
          move_data->initial_font_size = RNA_property_int_get(&elem_ptr, fs_prop);
        }
      }
    }
  }

  op->customdata = move_data;

  /* Set cursor based on resize handle for visual feedback */
  if (clicked_handle != -1) {
    wmWindow *win = CTX_wm_window(C);
    int cursor_type;
    switch (clicked_handle) {
      case 0: /* Bottom-left */
      case 4: /* Top-right */
        cursor_type = WM_CURSOR_NSEW_SCROLL;
        break;
      case 2: /* Bottom-right */
      case 6: /* Top-left */
        cursor_type = WM_CURSOR_NSEW_SCROLL;
        break;
      case 1: /* Bottom-center */
      case 5: /* Top-center */
        cursor_type = WM_CURSOR_NS_SCROLL;
        break;
      case 3: /* Right-center */
      case 7: /* Left-center */
        cursor_type = WM_CURSOR_EW_SCROLL;
        break;
      default:
        cursor_type = WM_CURSOR_DEFAULT;
        break;
    }
    WM_cursor_modal_set(win, cursor_type);
  }

  WM_event_add_modal_handler(C, op);

  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus moodboard_select_image_modal(bContext *C,
                                                     wmOperator *op,
                                                     const wmEvent *event)
{
  MoodboardMoveData *move_data = static_cast<MoodboardMoveData *>(op->customdata);
  wmWindow *win = CTX_wm_window(C);
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  ScrArea *area = CTX_wm_area(C);

  /* Helper lambda to clean up and cancel */
  auto cleanup_and_cancel = [&]() -> wmOperatorStatus {
    if (move_data) {
      if (move_data->is_resizing && win) {
        WM_cursor_modal_restore(win);
      }
      MEM_delete(move_data);
      op->customdata = nullptr;
    }
    return OPERATOR_CANCELLED;
  };

  /* Context validation - cancel if context became invalid */
  if (!move_data || !win || !scene || !region || !area) {
    return cleanup_and_cancel();
  }

  /* Cancel if the operator's poll function fails (e.g., switched away from moodboard mode) */
  if (!moodboard_poll(C)) {
    return cleanup_and_cancel();
  }

  /* Cancel modal operation when window loses focus (e.g., alt-tab, or application quit).
   * This ensures cleanup happens before shutdown and is also standard UX for drag operations -
   * you can't continue dragging in a background window. */
  if (event->type == WINDEACTIVATE) {
    return cleanup_and_cancel();
  }

  /* Also cancel on Cmd+Q (macOS quit) or Ctrl+Q (Linux quit) to ensure cleanup before shutdown */
  if (event->type == EVT_QKEY && event->val == KM_PRESS &&
      (event->modifier & (KM_OSKEY | KM_CTRL)))
  {
    return cleanup_and_cancel();
  }

  View2D *v2d = &region->v2d;

  switch (event->type) {
    case MOUSEZOOM:
    case MOUSEPAN:
      return OPERATOR_PASS_THROUGH;

    case MOUSEMOVE: {
      float mouse_x, mouse_y;
      ui::view2d_region_to_view(v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);

      float delta_x = mouse_x - move_data->initial_mouse_x;
      float delta_y = mouse_y - move_data->initial_mouse_y;

      float drag_threshold = MOODBOARD_DRAG_THRESHOLD_PX / ui::view2d_scale_get_x(v2d);

      if (!move_data->is_dragging) {
        float distance_sq = delta_x * delta_x + delta_y * delta_y;
        if (distance_sq > drag_threshold * drag_threshold) {
          move_data->is_dragging = true;
        }
        else {
          return OPERATOR_PASS_THROUGH;
        }
      }

      /* Check if we're resizing */
      if (move_data->is_resizing) {
        PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

        /* Store initial values for all selected images and calculate bounding box */
        if (!move_data->has_stored_initial_positions) {
          move_data->selected_count = 0;
          move_data->has_stored_initial_positions = true;

          /* Initialize bounding box with extreme values */
          move_data->bbox_min_x = FLT_MAX;
          move_data->bbox_min_y = FLT_MAX;
          move_data->bbox_max_x = -FLT_MAX;
          move_data->bbox_max_y = -FLT_MAX;

          /* Get groups to check for group selection */
          PropertyRNA *groups_prop = RNA_struct_find_property(&scene_ptr,
                                                               "mixie_moodboard_groups");

          PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
          if (img_prop) {
            int image_count = RNA_property_collection_length(&scene_ptr, img_prop);
            for (int i = 0; i < image_count &&
                           move_data->selected_count < MOODBOARD_MAX_SELECTED_IMAGES;
                 i++)
            {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(&scene_ptr, img_prop, i, &item_ptr);

              /* Check if image is directly selected */
              PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
              bool is_image_selected = sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop);

              /* Check if image's group is selected */
              bool is_group_selected = false;
              PropertyRNA *group_idx_prop = RNA_struct_find_property(&item_ptr, "group_index");
              if (group_idx_prop && groups_prop) {
                int group_index = RNA_property_int_get(&item_ptr, group_idx_prop);
                if (group_index >= 0) {
                  PointerRNA group_ptr;
                  RNA_property_collection_lookup_int(
                      &scene_ptr, groups_prop, group_index, &group_ptr);
                  PropertyRNA *group_sel_prop = RNA_struct_find_property(&group_ptr, "selected");
                  if (group_sel_prop) {
                    is_group_selected = RNA_property_boolean_get(&group_ptr, group_sel_prop);
                  }
                }
              }

              if (is_image_selected || is_group_selected) {
                PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
                PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
                PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");

                if (pos_x_prop && pos_y_prop && scale_prop) {
                  float img_scale = RNA_property_float_get(&item_ptr, scale_prop);
                  float img_width = MOODBOARD_IMAGE_BASE_SIZE * img_scale;

                  /* Get image aspect ratio */
                  float img_aspect = 1.0f;
                  PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
                  if (image_prop) {
                    PointerRNA image_ptr = RNA_property_pointer_get(&item_ptr, image_prop);
                    if (image_ptr.data) {
                      Image *img = static_cast<Image *>(image_ptr.data);
                      ImageUser iuser = {nullptr};
                      void *lock;
                      ImBuf *ibuf = BKE_image_acquire_ibuf(img, &iuser, &lock);
                      if (ibuf && ibuf->x > 0) {
                        img_aspect = float(ibuf->y) / float(ibuf->x);
                      }
                      BKE_image_release_ibuf(img, ibuf, lock);
                    }
                  }
                  float img_height = img_width * img_aspect;

                  float pos_x = RNA_property_float_get(&item_ptr, pos_x_prop);
                  float pos_y = RNA_property_float_get(&item_ptr, pos_y_prop);

                  move_data->selected_indices[move_data->selected_count] = i;
                  move_data->selected_initial_x[move_data->selected_count] = pos_x;
                  move_data->selected_initial_y[move_data->selected_count] = pos_y;
                  move_data->selected_initial_scale[move_data->selected_count] = img_scale;
                  move_data->selected_initial_width[move_data->selected_count] = img_width;
                  move_data->selected_initial_height[move_data->selected_count] = img_height;
                  move_data->selected_aspect_ratio[move_data->selected_count] = img_aspect;

                  /* Update bounding box */
                  move_data->bbox_min_x = std::min(move_data->bbox_min_x, pos_x);
                  move_data->bbox_min_y = std::min(move_data->bbox_min_y, pos_y);
                  move_data->bbox_max_x = std::max(move_data->bbox_max_x, pos_x + img_width);
                  move_data->bbox_max_y = std::max(move_data->bbox_max_y, pos_y + img_height);

                  move_data->selected_count++;
                }
              }
            }
          }

          /* Calculate bounding box dimensions */
          move_data->bbox_width = move_data->bbox_max_x - move_data->bbox_min_x;
          move_data->bbox_height = move_data->bbox_max_y - move_data->bbox_min_y;
        }

        int handle = move_data->resize_handle;

        /* Calculate scale factor based on bounding box for multi-select */
        float scale_factor = 1.0f;
        float anchor_x, anchor_y;
        float dist_func_res;

        /* Use bounding box for anchor calculation when multiple images selected */
        bool use_bbox = (move_data->selected_count > 1);
        float ref_min_x = use_bbox ? move_data->bbox_min_x : move_data->initial_pos_x;
        float ref_min_y = use_bbox ? move_data->bbox_min_y : move_data->initial_pos_y;
        float ref_max_x = use_bbox ? move_data->bbox_max_x :
                                     (move_data->initial_pos_x + move_data->initial_width);
        float ref_max_y = use_bbox ? move_data->bbox_max_y :
                                     (move_data->initial_pos_y + move_data->initial_height);
        float ref_width = use_bbox ? move_data->bbox_width : move_data->initial_width;
        float ref_height = use_bbox ? move_data->bbox_height : move_data->initial_height;

        /* Inverse-rotate the mouse position into the element's local (unrotated)
         * coordinate space so that anchor points and distance calculations work
         * correctly for rotated elements.  The rotation pivot is the center of
         * the reference bounding box — the same pivot used by the drawing code. */
        float local_mouse_x = mouse_x;
        float local_mouse_y = mouse_y;
        float rotation_deg = move_data->initial_rotation;
        if (rotation_deg != 0.0f) {
          float cx = (ref_min_x + ref_max_x) * 0.5f;
          float cy = (ref_min_y + ref_max_y) * 0.5f;
          float rad = -rotation_deg * (float(M_PI) / 180.0f);
          float cos_a = cosf(rad);
          float sin_a = sinf(rad);
          float dx = mouse_x - cx;
          float dy = mouse_y - cy;
          local_mouse_x = cx + dx * cos_a - dy * sin_a;
          local_mouse_y = cy + dx * sin_a + dy * cos_a;
        }

        if (handle == 0) { /* Bottom-left: anchor at top-right */
          anchor_x = ref_max_x;
          anchor_y = ref_max_y;
          dist_func_res = sqrtf(powf(anchor_x - local_mouse_x, 2) + powf(anchor_y - local_mouse_y, 2));
        }
        else if (handle == 2) { /* Bottom-right: anchor at top-left */
          anchor_x = ref_min_x;
          anchor_y = ref_max_y;
          dist_func_res = sqrtf(powf(local_mouse_x - anchor_x, 2) + powf(anchor_y - local_mouse_y, 2));
        }
        else if (handle == 4) { /* Top-right: anchor at bottom-left */
          anchor_x = ref_min_x;
          anchor_y = ref_min_y;
          dist_func_res = sqrtf(powf(local_mouse_x - anchor_x, 2) + powf(local_mouse_y - anchor_y, 2));
        }
        else if (handle == 6) { /* Top-left: anchor at bottom-right */
          anchor_x = ref_max_x;
          anchor_y = ref_min_y;
          dist_func_res = sqrtf(powf(anchor_x - local_mouse_x, 2) + powf(local_mouse_y - anchor_y, 2));
        }
        else if (handle == 1) { /* Bottom-center: anchor at top */
          anchor_x = ref_min_x + ref_width / 2.0f;
          anchor_y = ref_max_y;
          dist_func_res = fabsf(anchor_y - local_mouse_y);
        }
        else if (handle == 5) { /* Top-center: anchor at bottom */
          anchor_x = ref_min_x + ref_width / 2.0f;
          anchor_y = ref_min_y;
          dist_func_res = fabsf(local_mouse_y - anchor_y);
        }
        else if (handle == 3) { /* Right-center: anchor at left */
          anchor_x = ref_min_x;
          anchor_y = ref_min_y + ref_height / 2.0f;
          dist_func_res = fabsf(local_mouse_x - anchor_x);
        }
        else if (handle == 7) { /* Left-center: anchor at right */
          anchor_x = ref_max_x;
          anchor_y = ref_min_y + ref_height / 2.0f;
          dist_func_res = fabsf(anchor_x - local_mouse_x);
        }
        else {
          anchor_x = ref_min_x;
          anchor_y = ref_min_y;
          dist_func_res = 1.0f;
        }

        float initial_dist;
        if (handle % 2 == 0) { /* Corner handles */
          initial_dist = sqrtf(powf(ref_width, 2) + powf(ref_height, 2));
        }
        else if (handle == 1 || handle == 5) { /* Vertical edge handles */
          initial_dist = ref_height;
        }
        else { /* Horizontal edge handles */
          initial_dist = ref_width;
        }

        if (initial_dist > 0.001f) {
          scale_factor = dist_func_res / initial_dist;
        }

        /* Handle textbox resizing (single element only).
         *
         * Corner handles (0,2,4,6): uniform scale — lock aspect ratio,
         *   scale width, height, and font_size proportionally.
         * Horizontal edge handles (3,7 — left/right): stretch width only,
         *   no font_size change — lets more text fit per line.
         * Vertical edge handles (1,5 — bottom/top): stretch height only,
         *   no font_size change. */
        if (move_data->element_type == MOODBOARD_ELEMENT_TEXTBOX) {
          bool is_corner = (handle % 2 == 0);

          float new_width, new_height;
          float new_pos_x = move_data->initial_pos_x;
          float new_pos_y = move_data->initial_pos_y;

          if (is_corner) {
            /* Uniform scale: keep aspect ratio locked */
            new_width = move_data->initial_width * scale_factor;
            new_height = move_data->initial_height * scale_factor;

            /* Clamp */
            new_width = std::max(50.0f, std::min(2000.0f, new_width));
            new_height = std::max(30.0f, std::min(2000.0f, new_height));
          }
          else if (handle == 3 || handle == 7) {
            /* Horizontal edge: stretch width only */
            new_width = move_data->initial_width * scale_factor;
            new_width = std::max(50.0f, std::min(2000.0f, new_width));
            new_height = move_data->initial_height;
          }
          else {
            /* Vertical edge (1, 5): stretch height only */
            new_width = move_data->initial_width;
            new_height = move_data->initial_height * scale_factor;
            new_height = std::max(30.0f, std::min(2000.0f, new_height));
          }

          /* Anchor the opposite corner/edge */
          if (handle == 0) { /* Bottom-left */
            new_pos_x = (move_data->initial_pos_x + move_data->initial_width) - new_width;
            new_pos_y = (move_data->initial_pos_y + move_data->initial_height) - new_height;
          }
          else if (handle == 1) { /* Bottom-center */
            new_pos_x = move_data->initial_pos_x + (move_data->initial_width - new_width) / 2.0f;
            new_pos_y = (move_data->initial_pos_y + move_data->initial_height) - new_height;
          }
          else if (handle == 2) { /* Bottom-right */
            new_pos_y = (move_data->initial_pos_y + move_data->initial_height) - new_height;
          }
          else if (handle == 3) { /* Right-center: anchor left edge */
            /* pos_x stays, pos_y stays */
          }
          else if (handle == 5) { /* Top-center: anchor bottom */
            new_pos_x = move_data->initial_pos_x + (move_data->initial_width - new_width) / 2.0f;
          }
          else if (handle == 6) { /* Top-left */
            new_pos_x = (move_data->initial_pos_x + move_data->initial_width) - new_width;
          }
          else if (handle == 7) { /* Left-center: anchor right edge */
            new_pos_x = (move_data->initial_pos_x + move_data->initial_width) - new_width;
          }

          PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_textboxes");
          if (prop) {
            PointerRNA item_ptr;
            RNA_property_collection_lookup_int(&scene_ptr, prop, move_data->image_index, &item_ptr);

            PropertyRNA *width_prop = RNA_struct_find_property(&item_ptr, "width");
            PropertyRNA *height_prop = RNA_struct_find_property(&item_ptr, "height");
            if (width_prop && height_prop) {
              RNA_property_float_set(&item_ptr, width_prop, new_width);
              RNA_property_float_set(&item_ptr, height_prop, new_height);
            }

            /* Scale font_size only for corner handles (uniform scale) */
            if (is_corner && move_data->initial_font_size > 0) {
              PropertyRNA *fs_prop = RNA_struct_find_property(&item_ptr, "font_size");
              if (fs_prop) {
                int new_font_size = int(move_data->initial_font_size * scale_factor + 0.5f);
                new_font_size = std::max(8, std::min(500, new_font_size));
                RNA_property_int_set(&item_ptr, fs_prop, new_font_size);
              }
            }

            if (new_pos_x != move_data->initial_pos_x) {
              PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
              if (pos_x_prop) {
                RNA_property_float_set(&item_ptr, pos_x_prop, new_pos_x);
              }
            }
            if (new_pos_y != move_data->initial_pos_y) {
              PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
              if (pos_y_prop) {
                RNA_property_float_set(&item_ptr, pos_y_prop, new_pos_y);
              }
            }
          }
        }
        else {
          /* Handle image resizing - apply to ALL selected images with group scaling */
          PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
          if (img_prop) {
            for (int i = 0; i < move_data->selected_count; i++) {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(
                  &scene_ptr, img_prop, move_data->selected_indices[i], &item_ptr);

              float init_scale = move_data->selected_initial_scale[i];
              float init_pos_x = move_data->selected_initial_x[i];
              float init_pos_y = move_data->selected_initial_y[i];

              /* Scale each image's scale property */
              float new_scale = init_scale * scale_factor;
              new_scale = std::max(MOODBOARD_IMAGE_MIN_SCALE,
                                   std::min(MOODBOARD_IMAGE_MAX_SCALE, new_scale));

              /* Calculate new position relative to the anchor point.
               * The position should scale around the anchor so that relative
               * positions and gaps between images are maintained. */
              float new_pos_x = anchor_x + (init_pos_x - anchor_x) * scale_factor;
              float new_pos_y = anchor_y + (init_pos_y - anchor_y) * scale_factor;

              PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");
              if (scale_prop) {
                RNA_property_float_set(&item_ptr, scale_prop, new_scale);
              }

              PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
              PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
              if (pos_x_prop) {
                RNA_property_float_set(&item_ptr, pos_x_prop, new_pos_x);
              }
              if (pos_y_prop) {
                RNA_property_float_set(&item_ptr, pos_y_prop, new_pos_y);
              }
            }
          }
        }

        /* Throttle redraws to avoid excessive GPU load during resize */
        double current_time = BLI_time_now_seconds();
        if (current_time - move_data->last_redraw_time >= MoodboardMoveData::MIN_REDRAW_INTERVAL) {
          ED_area_tag_redraw(CTX_wm_area(C));
          move_data->last_redraw_time = current_time;
        }
        return OPERATOR_RUNNING_MODAL;
      }
      else {
        /* Move logic: move all selected images and text boxes together */
        PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

        if (!move_data->has_stored_initial_positions) {
          move_data->selected_count = 0;
          move_data->selected_textbox_count = 0;
          move_data->has_stored_initial_positions = true;

          /* Get groups to check for group selection */
          PropertyRNA *groups_prop = RNA_struct_find_property(&scene_ptr,
                                                               "mixie_moodboard_groups");

          PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
          if (img_prop) {
            int image_count = RNA_property_collection_length(&scene_ptr, img_prop);
            for (int i = 0; i < image_count &&
                           move_data->selected_count < MOODBOARD_MAX_SELECTED_IMAGES;
                 i++)
            {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(&scene_ptr, img_prop, i, &item_ptr);

              /* Check if image is directly selected */
              PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
              bool is_image_selected = sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop);

              /* Check if image's group is selected */
              bool is_group_selected = false;
              PropertyRNA *group_idx_prop = RNA_struct_find_property(&item_ptr, "group_index");
              if (group_idx_prop && groups_prop) {
                int group_index = RNA_property_int_get(&item_ptr, group_idx_prop);
                if (group_index >= 0) {
                  PointerRNA group_ptr;
                  RNA_property_collection_lookup_int(
                      &scene_ptr, groups_prop, group_index, &group_ptr);
                  PropertyRNA *group_sel_prop = RNA_struct_find_property(&group_ptr, "selected");
                  if (group_sel_prop) {
                    is_group_selected = RNA_property_boolean_get(&group_ptr, group_sel_prop);
                  }
                }
              }

              if (is_image_selected || is_group_selected) {
                PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
                PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");

                if (pos_x_prop && pos_y_prop) {
                  move_data->selected_indices[move_data->selected_count] = i;
                  move_data->selected_initial_x[move_data->selected_count] =
                      RNA_property_float_get(&item_ptr, pos_x_prop);
                  move_data->selected_initial_y[move_data->selected_count] =
                      RNA_property_float_get(&item_ptr, pos_y_prop);
                  move_data->selected_count++;
                }
              }
            }
          }

          PropertyRNA *textbox_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_textboxes");
          if (textbox_prop) {
            int textbox_count = RNA_property_collection_length(&scene_ptr, textbox_prop);
            for (int i = 0; i < textbox_count &&
                           move_data->selected_textbox_count < MOODBOARD_MAX_SELECTED_IMAGES;
                 i++)
            {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(&scene_ptr, textbox_prop, i, &item_ptr);

              PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
              if (sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop)) {
                PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
                PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");

                if (pos_x_prop && pos_y_prop) {
                  move_data->selected_textbox_indices[move_data->selected_textbox_count] = i;
                  move_data->selected_textbox_initial_x[move_data->selected_textbox_count] =
                      RNA_property_float_get(&item_ptr, pos_x_prop);
                  move_data->selected_textbox_initial_y[move_data->selected_textbox_count] =
                      RNA_property_float_get(&item_ptr, pos_y_prop);
                  move_data->selected_textbox_count++;
                }
              }
            }
          }
        }

        PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
        if (img_prop) {
          for (int i = 0; i < move_data->selected_count; i++) {
            PointerRNA item_ptr;
            RNA_property_collection_lookup_int(
                &scene_ptr, img_prop, move_data->selected_indices[i], &item_ptr);

            PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
            PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");

            if (pos_x_prop && pos_y_prop) {
              float new_pos_x = move_data->selected_initial_x[i] + delta_x;
              float new_pos_y = move_data->selected_initial_y[i] + delta_y;

              RNA_property_float_set(&item_ptr, pos_x_prop, new_pos_x);
              RNA_property_float_set(&item_ptr, pos_y_prop, new_pos_y);
            }
          }
        }

        PropertyRNA *textbox_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_textboxes");
        if (textbox_prop) {
          for (int i = 0; i < move_data->selected_textbox_count; i++) {
            PointerRNA item_ptr;
            RNA_property_collection_lookup_int(
                &scene_ptr, textbox_prop, move_data->selected_textbox_indices[i], &item_ptr);

            PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
            PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");

            if (pos_x_prop && pos_y_prop) {
              float new_pos_x = move_data->selected_textbox_initial_x[i] + delta_x;
              float new_pos_y = move_data->selected_textbox_initial_y[i] + delta_y;

              RNA_property_float_set(&item_ptr, pos_x_prop, new_pos_x);
              RNA_property_float_set(&item_ptr, pos_y_prop, new_pos_y);
            }
          }
        }

        /* Throttle redraws to avoid excessive GPU load during move */
        double current_time = BLI_time_now_seconds();
        if (current_time - move_data->last_redraw_time >= MoodboardMoveData::MIN_REDRAW_INTERVAL) {
          ED_area_tag_redraw(CTX_wm_area(C));
          move_data->last_redraw_time = current_time;
        }

        return OPERATOR_RUNNING_MODAL;
      }
    }

    case WHEELUPMOUSE:
    case WHEELDOWNMOUSE:
      if (event->modifier & KM_OSKEY) {
        float scale_delta = (event->type == WHEELUPMOUSE) ? MOODBOARD_IMAGE_SCALE_DELTA :
                                                           -MOODBOARD_IMAGE_SCALE_DELTA;

        PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
        PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");

        if (prop) {
          int image_count = RNA_property_collection_length(&scene_ptr, prop);
          bool any_updated = false;

          for (int i = 0; i < image_count; i++) {
            PointerRNA item_ptr;
            RNA_property_collection_lookup_int(&scene_ptr, prop, i, &item_ptr);

            PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
            if (sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop)) {
              PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");
              if (scale_prop) {
                float current_scale = RNA_property_float_get(&item_ptr, scale_prop);
                float new_scale = current_scale + scale_delta;
                new_scale = std::max(MOODBOARD_IMAGE_MIN_SCALE,
                                     std::min(MOODBOARD_IMAGE_MAX_SCALE, new_scale));
                RNA_property_float_set(&item_ptr, scale_prop, new_scale);
                any_updated = true;
              }
            }
          }

          if (any_updated) {
            ED_area_tag_redraw(CTX_wm_area(C));
          }
        }

        return OPERATOR_RUNNING_MODAL;
      }
      break;

    case LEFTMOUSE:
      if (event->val == KM_RELEASE) {
        /* Restore cursor if we were resizing */
        if (move_data->is_resizing) {
          wmWindow *win = CTX_wm_window(C);
          WM_cursor_modal_restore(win);
        }

        MEM_delete(move_data);
        op->customdata = nullptr;

        WM_event_add_notifier(C, NC_SCENE | ND_SEQUENCER, scene);

        return OPERATOR_FINISHED;
      }
      break;

    case EVT_ESCKEY:
    case RIGHTMOUSE:
      if (move_data->is_dragging) {
        PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

        if (move_data->is_resizing) {
          /* Restore all selected images to their initial state */
          PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
          if (img_prop && move_data->has_stored_initial_positions) {
            for (int i = 0; i < move_data->selected_count; i++) {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(
                  &scene_ptr, img_prop, move_data->selected_indices[i], &item_ptr);

              PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");
              PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
              PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");

              if (scale_prop) {
                RNA_property_float_set(
                    &item_ptr, scale_prop, move_data->selected_initial_scale[i]);
              }
              if (pos_x_prop) {
                RNA_property_float_set(&item_ptr, pos_x_prop, move_data->selected_initial_x[i]);
              }
              if (pos_y_prop) {
                RNA_property_float_set(&item_ptr, pos_y_prop, move_data->selected_initial_y[i]);
              }
            }
          }
        }
        else {
          /* Restore all selected items during move */
          PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
          if (img_prop) {
            for (int i = 0; i < move_data->selected_count; i++) {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(
                  &scene_ptr, img_prop, move_data->selected_indices[i], &item_ptr);

              PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
              PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");

              if (pos_x_prop && pos_y_prop) {
                RNA_property_float_set(&item_ptr, pos_x_prop, move_data->selected_initial_x[i]);
                RNA_property_float_set(&item_ptr, pos_y_prop, move_data->selected_initial_y[i]);
              }
            }
          }

          PropertyRNA *textbox_prop = RNA_struct_find_property(&scene_ptr,
                                                                "mixie_moodboard_textboxes");
          if (textbox_prop) {
            for (int i = 0; i < move_data->selected_textbox_count; i++) {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(
                  &scene_ptr, textbox_prop, move_data->selected_textbox_indices[i], &item_ptr);

              PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
              PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");

              if (pos_x_prop && pos_y_prop) {
                RNA_property_float_set(
                    &item_ptr, pos_x_prop, move_data->selected_textbox_initial_x[i]);
                RNA_property_float_set(
                    &item_ptr, pos_y_prop, move_data->selected_textbox_initial_y[i]);
              }
            }
          }
        }

        ED_area_tag_redraw(CTX_wm_area(C));
      }

      /* Restore cursor if we were resizing */
      if (move_data->is_resizing) {
        wmWindow *win = CTX_wm_window(C);
        WM_cursor_modal_restore(win);
      }

      MEM_delete(move_data);
      op->customdata = nullptr;

      return OPERATOR_CANCELLED;

    default:
      break;
  }

  return OPERATOR_PASS_THROUGH;
}

static void moodboard_select_image_cancel(bContext *C, wmOperator *op)
{
  MoodboardMoveData *move_data = static_cast<MoodboardMoveData *>(op->customdata);

  if (move_data) {
    /* Restore cursor if we were resizing - check window is valid first */
    if (move_data->is_resizing) {
      wmWindow *win = CTX_wm_window(C);
      if (win) {
        WM_cursor_modal_restore(win);
      }
    }

    MEM_delete(move_data);
    op->customdata = nullptr;
  }
}

/** \} */

}  // namespace blender::ed::mixie

/* -------------------------------------------------------------------- */
/** \name Operator Registration (C linkage)
 * \{ */

void MIXIE_OT_moodboard_select_image(wmOperatorType *ot)
{
  ot->name = "Select and Move Image";
  ot->idname = "MIXIE_OT_moodboard_select_image";
  ot->description = "Select and move an image on the moodboard";

  ot->invoke = blender::ed::mixie::moodboard_select_image_invoke;
  ot->modal = blender::ed::mixie::moodboard_select_image_modal;
  ot->cancel = blender::ed::mixie::moodboard_select_image_cancel;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_BLOCKING;

  PropertyRNA *prop;
  prop = RNA_def_boolean(
      ot->srna, "extend", false, "Extend", "Extend selection instead of deselecting everything first");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}

/** \} */
