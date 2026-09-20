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
  ctx.is_image_selected = false;
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

  /* Frame membership is DELIBERATELY not read here. A click on an item
   * selects THAT ITEM, whether or not it sits inside a frame -- the universal
   * behaviour, and the opposite of what this operator used to do: a plain
   * click on a grouped image selected the whole GROUP and reaching the image
   * needed a double-click, while Shift+click on it did nothing at all. A
   * frame is now selected by its own border or its thick top strip
   * (MIXIE_OT_moodboard_frame_select), which is a target of its own and needs
   * no special case here. */
  return ctx;
}

/* A plain click replaces the WHOLE board selection, cards included.
 * `moodboard_deselect_all` only knows about media, so on its own it left
 * inference and asset cards selected behind a click on a picture -- the graph
 * operator has always cleared both sides, and the two must agree. It matters
 * more now that a drag carries every selected kind: a card left selected by a
 * click the user read as "select just this image" would travel with it. */
static void moodboard_replace_selection(PointerRNA *scene_ptr)
{
  /* `moodboard_deselect_all` covers media, text boxes, cards, links AND
   * frames, so a click on a picture cannot leave a frame selected behind it --
   * which now matters more than ever, because a selected frame travels with
   * the drag and carries its members. */
  moodboard_deselect_all(scene_ptr);
  moodboard_graph_deselect_nodes(scene_ptr);
}

/** Double-click on individually selected image: deselect it */
static void handle_double_click_selected_image(MoodboardSelectionContext &ctx)
{
  if (ctx.sel_prop) {
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, false);
  }
}

/** Double-click on an unselected item: deselect all, select this item */
static void handle_double_click_unselected_item(MoodboardSelectionContext &ctx)
{
  moodboard_replace_selection(ctx.scene_ptr);
  if (ctx.sel_prop) {
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, true);
  }
}

/** Extend mode (Shift/Cmd+click): toggle this item in the selection */
static void handle_extend_click(MoodboardSelectionContext &ctx)
{
  if (ctx.sel_prop) {
    bool current_state = RNA_property_boolean_get(&ctx.item_ptr, ctx.sel_prop);
    RNA_property_boolean_set(&ctx.item_ptr, ctx.sel_prop, !current_state);
  }
}

/** Single click on an item: deselect all, select this item */
static void handle_click_select_image(MoodboardSelectionContext &ctx)
{
  moodboard_replace_selection(ctx.scene_ptr);
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
  /* Double-click actions */
  if (ctx.is_double_click) {
    if (ctx.is_image_selected) {
      handle_double_click_selected_image(ctx);
    }
    else {
      handle_double_click_unselected_item(ctx);
    }
    return;
  }

  /* Extend mode (Shift/Cmd+click) toggles, for every item alike. Membership
   * in a frame no longer disables it -- a grouped image used to be the ONE
   * thing on this canvas that Shift+click silently refused to add to a
   * selection. */
  if (ctx.extend_mode) {
    handle_extend_click(ctx);
    return;
  }

  /* Normal single click - if already selected, do nothing (allow drag) */
  if (ctx.is_image_selected) {
    return;
  }

  handle_click_select_image(ctx);
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
    /* Shared with the draw pass: a fixed PIXEL size in canvas units, capped
     * against the tile so a zoomed-out button and its target shrink together. */
    const rctf media_rect = {clicked_pos_x,
                             clicked_pos_x + clicked_width,
                             clicked_pos_y,
                             clicked_pos_y + clicked_height};
    const float play_radius = moodboard_video_play_radius(v2d, media_rect);
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
      moodboard_replace_selection(&scene_ptr);
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

  /* Update selection. Every element this operator can reach is an item in
   * its own right -- frames are the frame operator's business. */
  MoodboardSelectionContext ctx = get_selection_context(
      &scene_ptr, clicked_index, element_type, event, op);
  if (ctx.sel_prop) {
    update_moodboard_selection(ctx);
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

  /* Every handle is a corner and every corner is a uniform scale, so there is
   * one resize cursor. (The edge handles this replaces had their own NS/EW
   * cursors, which were the only thing that distinguished them.) */
  if (clicked_handle != -1) {
    WM_cursor_modal_set(CTX_wm_window(C), WM_CURSOR_NSEW_SCROLL);
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

          PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
          if (img_prop) {
            int image_count = RNA_property_collection_length(&scene_ptr, img_prop);
            for (int i = 0; i < image_count &&
                           move_data->selected_count < MOODBOARD_MAX_SELECTED_IMAGES;
                 i++)
            {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(&scene_ptr, img_prop, i, &item_ptr);

              /* Directly selected, or a member of a selected FRAME -- whose
               * border is what the user grabbed, so its members come with it.
               * ONE definition of that rule, shared with the drag set; the old
               * inline version resolved a `group_index` and so could only ever
               * carry images. */
              PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
              bool is_image_selected = sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop);
              const bool in_selected_frame = moodboard_item_frame_selected(&scene_ptr, &item_ptr);

              if (is_image_selected || in_selected_frame) {
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

        }

        int handle = move_data->resize_handle;

        /* Calculate scale factor based on bounding box for multi-select */
        float scale_factor = 1.0f;
        float anchor_x, anchor_y;

        /* Use bounding box for anchor calculation when multiple images selected */
        bool use_bbox = (move_data->selected_count > 1);
        float ref_min_x = use_bbox ? move_data->bbox_min_x : move_data->initial_pos_x;
        float ref_min_y = use_bbox ? move_data->bbox_min_y : move_data->initial_pos_y;
        float ref_max_x = use_bbox ? move_data->bbox_max_x :
                                     (move_data->initial_pos_x + move_data->initial_width);
        float ref_max_y = use_bbox ? move_data->bbox_max_y :
                                     (move_data->initial_pos_y + move_data->initial_height);

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

        /* The anchor and the scale factor come from the ONE resize rule the
         * card hit-test and the draw pass share: the corner diagonally
         * opposite the grabbed one is held, and the scale is that corner's
         * diagonal ratio -- one number for both axes, which is what locks the
         * aspect. Corners are the only handles there are. */
        const rctf ref_rect = {ref_min_x, ref_max_x, ref_min_y, ref_max_y};
        moodboard_resize_handle_anchor(ref_rect, handle, &anchor_x, &anchor_y);
        scale_factor = moodboard_resize_scale_factor(
            ref_rect, handle, local_mouse_x, local_mouse_y);

        /* Text box: uniform scale with the aspect locked, font_size carried
         * along so the text keeps its proportion to the box. */
        if (move_data->element_type == MOODBOARD_ELEMENT_TEXTBOX) {
          float new_width = std::max(
              50.0f, std::min(2000.0f, move_data->initial_width * scale_factor));
          float new_height = std::max(
              30.0f, std::min(2000.0f, move_data->initial_height * scale_factor));

          const rctf initial = {move_data->initial_pos_x,
                                move_data->initial_pos_x + move_data->initial_width,
                                move_data->initial_pos_y,
                                move_data->initial_pos_y + move_data->initial_height};
          rctf placed;
          moodboard_resize_place(initial, handle, new_width, new_height, &placed);
          const float new_pos_x = placed.xmin;
          const float new_pos_y = placed.ymin;

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

            /* Every handle is a uniform scale now, so the text always keeps
             * its proportion to the box it sits in. */
            if (move_data->initial_font_size > 0) {
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

          PropertyRNA *img_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
          if (img_prop) {
            int image_count = RNA_property_collection_length(&scene_ptr, img_prop);
            for (int i = 0; i < image_count &&
                           move_data->selected_count < MOODBOARD_MAX_SELECTED_IMAGES;
                 i++)
            {
              PointerRNA item_ptr;
              RNA_property_collection_lookup_int(&scene_ptr, img_prop, i, &item_ptr);

              /* Directly selected, or a member of a selected FRAME -- whose
               * border is what the user grabbed, so its members come with it.
               * ONE definition of that rule, shared with the drag set; the old
               * inline version resolved a `group_index` and so could only ever
               * carry images. */
              PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
              bool is_image_selected = sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop);
              const bool in_selected_frame = moodboard_item_frame_selected(&scene_ptr, &item_ptr);

              if (is_image_selected || in_selected_frame) {
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

              /* Same frame rule as images: a note inside a frame the user
               * grabbed has to travel with it. Frames hold every canvas kind,
               * which the index-based grouping this replaces never could. */
              PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
              const bool selected = sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop);
              if (selected || moodboard_item_frame_selected(&scene_ptr, &item_ptr)) {
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

          /* Inference and 3D asset cards -- and FRAMES -- selected alongside
           * this media come with it. Without this a picture and a card
           * selected together came apart under the mouse: the picture moved
           * and the card stayed put. Captured through the shared drag set,
           * which the graph drag uses in the other direction. */
          moodboard_drag_set_capture(
              &scene_ptr,
              MoodboardDragKinds(MOODBOARD_DRAG_NODES | MOODBOARD_DRAG_FRAMES),
              &move_data->node_drag);
        }

        if (event->modifier & KM_CTRL) {
          /* Snap the GRABBED item to the grid and move everything else by the
           * same delta, so a multi-item selection keeps its shape and only its
           * anchor lands on the grid. Snapping each item independently would
           * collapse the spacing the user arranged. Applied here, after the
           * drag threshold above has already used the raw delta. */
          const float grid = MOODBOARD_SNAP_GRID;
          const float snapped_x = std::round(
                                      (move_data->initial_pos_x + delta_x) / grid) *
                                  grid;
          const float snapped_y = std::round(
                                      (move_data->initial_pos_y + delta_y) / grid) *
                                  grid;
          delta_x = snapped_x - move_data->initial_pos_x;
          delta_y = snapped_y - move_data->initial_pos_y;
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

        /* Cards move by the delta the media already applied, so a mixed
         * selection keeps its arrangement. */
        moodboard_drag_set_apply(&scene_ptr, move_data->node_drag, delta_x, delta_y);

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

        /* Dragging a picture INTO a frame is how it joins one, and resizing
         * one can move its centre across a frame's edge -- so membership is
         * re-resolved once the gesture ends. Only when something actually
         * moved, so a plain click never writes scene data. */
        const bool changed_geometry = move_data->is_dragging || move_data->is_resizing;

        MEM_delete(move_data);
        op->customdata = nullptr;

        WM_event_add_notifier(C, NC_SCENE | ND_SEQUENCER, scene);
        if (changed_geometry) {
          moodboard_frames_request_reframe(C);
        }

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

          moodboard_drag_set_restore(&scene_ptr, move_data->node_drag);
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


/* Mixar 5.2 port: operator registrations live in namespace blender. */
namespace blender {
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
}  // namespace blender
