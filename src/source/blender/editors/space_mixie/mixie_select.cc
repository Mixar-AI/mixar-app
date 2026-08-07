/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Selection and hit detection utilities for Mixie space
 */

#include <algorithm>
#include <cmath>

#include "BKE_context.hh"
#include "BKE_image.hh"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"

#include "mixie_intern.hh"
#include "mixie_moodboard_ops_common.hh"

/**
 * Inverse-rotate a point around a center.
 * Transforms a world-space point into the local (unrotated) space of an
 * element so that axis-aligned hit-testing works on rotated elements.
 */
static void inverse_rotate_point(float mx,
                                 float my,
                                 float cx,
                                 float cy,
                                 float rotation_deg,
                                 float *out_x,
                                 float *out_y)
{
  if (rotation_deg == 0.0f) {
    *out_x = mx;
    *out_y = my;
    return;
  }
  const float rotation_rad = -rotation_deg * (M_PI / 180.0f);
  const float cos_a = cosf(rotation_rad);
  const float sin_a = sinf(rotation_rad);
  const float dx = mx - cx;
  const float dy = my - cy;
  *out_x = cx + dx * cos_a - dy * sin_a;
  *out_y = cy + dx * sin_a + dy * cos_a;
}

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Moodboard Selection Helpers
 * \{ */

int moodboard_find_image_under_mouse(PointerRNA *scene_ptr,
                                     float mouse_x,
                                     float mouse_y,
                                     float *r_pos_x,
                                     float *r_pos_y,
                                     float *r_scale,
                                     float *r_width,
                                     float *r_height)
{
  PropertyRNA *prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!prop) {
    return -1;
  }

  int image_count = RNA_property_collection_length(scene_ptr, prop);

  /* Iterate in reverse to check top images first */
  for (int i = image_count - 1; i >= 0; i--) {
    PointerRNA item_ptr;
    RNA_property_collection_lookup_int(scene_ptr, prop, i, &item_ptr);

    PropertyRNA *embedded_prop = RNA_struct_find_property(&item_ptr, "embedded_node_id");
    if (embedded_prop && RNA_property_string_length(&item_ptr, embedded_prop) > 0) {
      continue;
    }

    PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
    PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
    PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
    PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");

    if (!image_prop || !pos_x_prop || !pos_y_prop || !scale_prop) {
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

    /* Read rotation (radians) */
    PropertyRNA *rot_prop = RNA_struct_find_property(&item_ptr, "rotation");
    float rotation = rot_prop ? RNA_property_float_get(&item_ptr, rot_prop) : 0.0f;

    /* Clamp scale to valid range to prevent rendering issues */
    scale = std::clamp(scale, MOODBOARD_IMAGE_MIN_SCALE, MOODBOARD_IMAGE_MAX_SCALE);

    /* Calculate image bounds using same logic as rendering */
    void *lock;
    ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
    float img_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
    float img_height;

    /* Validate image buffer and dimensions */
    if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
      img_height = (MOODBOARD_IMAGE_BASE_SIZE * float(ibuf->y) / float(ibuf->x)) * scale;
    }
    else {
      /* Fallback to square for images without valid buffers */
      img_height = MOODBOARD_IMAGE_BASE_SIZE * scale;
    }
    BKE_image_release_ibuf(image, ibuf, lock);

    /* Inverse-rotate mouse into the image's local space so that the
     * axis-aligned bounds check works correctly for rotated images. */
    float local_mx, local_my;
    inverse_rotate_point(mouse_x,
                         mouse_y,
                         pos_x + img_width / 2.0f,
                         pos_y + img_height / 2.0f,
                         rotation,
                         &local_mx,
                         &local_my);

    /* Check if mouse is within image bounds */
    if (local_mx >= pos_x && local_mx <= pos_x + img_width && local_my >= pos_y &&
        local_my <= pos_y + img_height)
    {
      if (r_pos_x)
        *r_pos_x = pos_x;
      if (r_pos_y)
        *r_pos_y = pos_y;
      if (r_scale)
        *r_scale = scale;
      if (r_width)
        *r_width = img_width;
      if (r_height)
        *r_height = img_height;
      return i;
    }
  }

  return -1;
}

int moodboard_find_textbox_under_mouse(PointerRNA *scene_ptr,
                                       float mouse_x,
                                       float mouse_y,
                                       float *r_pos_x,
                                       float *r_pos_y,
                                       float *r_width,
                                       float *r_height)
{
  PropertyRNA *prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_textboxes");
  if (!prop) {
    return -1;
  }

  int textbox_count = RNA_property_collection_length(scene_ptr, prop);

  /* Iterate in reverse to check top text boxes first */
  for (int i = textbox_count - 1; i >= 0; i--) {
    PointerRNA item_ptr;
    RNA_property_collection_lookup_int(scene_ptr, prop, i, &item_ptr);

    PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
    PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
    PropertyRNA *width_prop = RNA_struct_find_property(&item_ptr, "width");
    PropertyRNA *height_prop = RNA_struct_find_property(&item_ptr, "height");

    if (!pos_x_prop || !pos_y_prop || !width_prop || !height_prop) {
      continue;
    }

    float pos_x = RNA_property_float_get(&item_ptr, pos_x_prop);
    float pos_y = RNA_property_float_get(&item_ptr, pos_y_prop);
    float width = RNA_property_float_get(&item_ptr, width_prop);
    float height = RNA_property_float_get(&item_ptr, height_prop);

    /* Read rotation (radians) */
    PropertyRNA *rot_prop = RNA_struct_find_property(&item_ptr, "rotation");
    float rotation = rot_prop ? RNA_property_float_get(&item_ptr, rot_prop) : 0.0f;

    /* Inverse-rotate mouse into textbox local space */
    float local_mx, local_my;
    inverse_rotate_point(mouse_x,
                         mouse_y,
                         pos_x + width / 2.0f,
                         pos_y + height / 2.0f,
                         rotation,
                         &local_mx,
                         &local_my);

    /* Check if mouse is within text box bounds */
    if (local_mx >= pos_x && local_mx <= pos_x + width && local_my >= pos_y &&
        local_my <= pos_y + height)
    {
      if (r_pos_x)
        *r_pos_x = pos_x;
      if (r_pos_y)
        *r_pos_y = pos_y;
      if (r_width)
        *r_width = width;
      if (r_height)
        *r_height = height;
      return i;
    }
  }

  return -1;
}

int moodboard_find_resize_handle_at_mouse(PointerRNA *scene_ptr,
                                          float mouse_x,
                                          float mouse_y,
                                          float handle_tolerance,
                                          int *r_element_index,
                                          MoodboardElementType *r_element_type,
                                          float *r_pos_x,
                                          float *r_pos_y,
                                          float *r_scale,
                                          float *r_width,
                                          float *r_height)
{
  /* Check selected GROUP handles first (highest priority) */
  PropertyRNA *groups_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_groups");
  PropertyRNA *img_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");

  if (groups_prop && img_prop) {
    int group_count = RNA_property_collection_length(scene_ptr, groups_prop);
    int image_count = RNA_property_collection_length(scene_ptr, img_prop);

    for (int g = 0; g < group_count; g++) {
      PointerRNA group_ptr;
      RNA_property_collection_lookup_int(scene_ptr, groups_prop, g, &group_ptr);

      /* Only check selected groups */
      PropertyRNA *sel_prop = RNA_struct_find_property(&group_ptr, "selected");
      if (!sel_prop || !RNA_property_boolean_get(&group_ptr, sel_prop)) {
        continue;
      }

      /* Calculate group bounding box */
      float min_x = FLT_MAX, min_y = FLT_MAX;
      float max_x = -FLT_MAX, max_y = -FLT_MAX;
      bool has_valid_bounds = false;

      for (int j = 0; j < image_count; j++) {
        PointerRNA item_ptr;
        RNA_property_collection_lookup_int(scene_ptr, img_prop, j, &item_ptr);

        PropertyRNA *grp_idx_prop = RNA_struct_find_property(&item_ptr, "group_index");
        int group_index = grp_idx_prop ? RNA_property_int_get(&item_ptr, grp_idx_prop) : -1;

        if (group_index != g) {
          continue;
        }

        PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
        PropertyRNA *px_prop = RNA_struct_find_property(&item_ptr, "position_x");
        PropertyRNA *py_prop = RNA_struct_find_property(&item_ptr, "position_y");
        PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");

        if (!image_prop || !px_prop || !py_prop || !scale_prop) {
          continue;
        }

        PointerRNA image_ptr = RNA_property_pointer_get(&item_ptr, image_prop);
        if (!image_ptr.data) {
          continue;
        }

        Image *image = static_cast<Image *>(image_ptr.data);
        float pos_x = RNA_property_float_get(&item_ptr, px_prop);
        float pos_y = RNA_property_float_get(&item_ptr, py_prop);
        float scale = RNA_property_float_get(&item_ptr, scale_prop);

        void *lock;
        ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
        float iw = MOODBOARD_IMAGE_BASE_SIZE * scale;
        float ih = iw;
        if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
          ih = (MOODBOARD_IMAGE_BASE_SIZE * float(ibuf->y) / float(ibuf->x)) * scale;
        }
        BKE_image_release_ibuf(image, ibuf, lock);

        min_x = std::min(min_x, pos_x);
        min_y = std::min(min_y, pos_y);
        max_x = std::max(max_x, pos_x + iw);
        max_y = std::max(max_y, pos_y + ih);
        has_valid_bounds = true;
      }

      if (!has_valid_bounds) {
        continue;
      }

      /* Add padding (same as drawing code) */
      float padding = 10.0f;
      min_x -= padding;
      min_y -= padding;
      max_x += padding;
      max_y += padding;

      float width = max_x - min_x;
      float height = max_y - min_y;

      /* Check all 8 handle positions on group bounding box */
      float handle_positions[8][2] = {
          {min_x, min_y},                    /* 0: Bottom-left */
          {min_x + width / 2, min_y},        /* 1: Bottom-center */
          {max_x, min_y},                    /* 2: Bottom-right */
          {max_x, min_y + height / 2},       /* 3: Right-center */
          {max_x, max_y},                    /* 4: Top-right */
          {min_x + width / 2, max_y},        /* 5: Top-center */
          {min_x, max_y},                    /* 6: Top-left */
          {min_x, min_y + height / 2}        /* 7: Left-center */
      };

      for (int h = 0; h < 8; h++) {
        float dx = mouse_x - handle_positions[h][0];
        float dy = mouse_y - handle_positions[h][1];
        if (dx * dx + dy * dy < handle_tolerance * handle_tolerance) {
          if (r_element_index)
            *r_element_index = g;
          if (r_element_type)
            *r_element_type = MOODBOARD_ELEMENT_GROUP;
          if (r_pos_x)
            *r_pos_x = min_x;
          if (r_pos_y)
            *r_pos_y = min_y;
          if (r_scale)
            *r_scale = 1.0f;
          if (r_width)
            *r_width = width;
          if (r_height)
            *r_height = height;
          return h;
        }
      }
    }
  }

  /* Check selected images (iterate in reverse for z-order) */
  if (img_prop) {
    int image_count = RNA_property_collection_length(scene_ptr, img_prop);

    for (int i = image_count - 1; i >= 0; i--) {
      PointerRNA item_ptr;
      RNA_property_collection_lookup_int(scene_ptr, img_prop, i, &item_ptr);

      PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
      if (!sel_prop || !RNA_property_boolean_get(&item_ptr, sel_prop)) {
        continue; /* Skip unselected images */
      }

      PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
      PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
      PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
      PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");

      if (!image_prop || !pos_x_prop || !pos_y_prop || !scale_prop) {
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

      /* Read rotation (radians) */
      PropertyRNA *rot_prop = RNA_struct_find_property(&item_ptr, "rotation");
      float rotation = rot_prop ? RNA_property_float_get(&item_ptr, rot_prop) : 0.0f;

      scale = std::clamp(scale, MOODBOARD_IMAGE_MIN_SCALE, MOODBOARD_IMAGE_MAX_SCALE);

      void *lock;
      ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
      float img_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
      float img_height;

      if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
        img_height = (MOODBOARD_IMAGE_BASE_SIZE * float(ibuf->y) / float(ibuf->x)) * scale;
      }
      else {
        img_height = MOODBOARD_IMAGE_BASE_SIZE * scale;
      }
      BKE_image_release_ibuf(image, ibuf, lock);

      /* Inverse-rotate mouse into the image's local space */
      float local_mx, local_my;
      inverse_rotate_point(mouse_x,
                           mouse_y,
                           pos_x + img_width / 2.0f,
                           pos_y + img_height / 2.0f,
                           rotation,
                           &local_mx,
                           &local_my);

      /* Check all 8 handle positions (in unrotated local space) */
      float handle_positions[8][2] = {
          {pos_x, pos_y},                           /* 0: Bottom-left */
          {pos_x + img_width / 2, pos_y},           /* 1: Bottom-center */
          {pos_x + img_width, pos_y},               /* 2: Bottom-right */
          {pos_x + img_width, pos_y + img_height / 2}, /* 3: Right-center */
          {pos_x + img_width, pos_y + img_height},  /* 4: Top-right */
          {pos_x + img_width / 2, pos_y + img_height}, /* 5: Top-center */
          {pos_x, pos_y + img_height},              /* 6: Top-left */
          {pos_x, pos_y + img_height / 2}           /* 7: Left-center */
      };

      for (int h = 0; h < 8; h++) {
        float dx = local_mx - handle_positions[h][0];
        float dy = local_my - handle_positions[h][1];
        if (dx * dx + dy * dy < handle_tolerance * handle_tolerance) {
          if (r_element_index)
            *r_element_index = i;
          if (r_element_type)
            *r_element_type = MOODBOARD_ELEMENT_IMAGE;
          if (r_pos_x)
            *r_pos_x = pos_x;
          if (r_pos_y)
            *r_pos_y = pos_y;
          if (r_scale)
            *r_scale = scale;
          if (r_width)
            *r_width = img_width;
          if (r_height)
            *r_height = img_height;
          return h;
        }
      }
    }
  }

  /* Check selected textboxes */
  PropertyRNA *textbox_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_textboxes");
  if (textbox_prop) {
    int textbox_count = RNA_property_collection_length(scene_ptr, textbox_prop);

    for (int i = textbox_count - 1; i >= 0; i--) {
      PointerRNA item_ptr;
      RNA_property_collection_lookup_int(scene_ptr, textbox_prop, i, &item_ptr);

      PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
      if (!sel_prop || !RNA_property_boolean_get(&item_ptr, sel_prop)) {
        continue; /* Skip unselected textboxes */
      }

      PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
      PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
      PropertyRNA *width_prop = RNA_struct_find_property(&item_ptr, "width");
      PropertyRNA *height_prop = RNA_struct_find_property(&item_ptr, "height");

      if (!pos_x_prop || !pos_y_prop || !width_prop || !height_prop) {
        continue;
      }

      float pos_x = RNA_property_float_get(&item_ptr, pos_x_prop);
      float pos_y = RNA_property_float_get(&item_ptr, pos_y_prop);
      float width = RNA_property_float_get(&item_ptr, width_prop);
      float height = RNA_property_float_get(&item_ptr, height_prop);

      /* Read rotation (radians) */
      PropertyRNA *rot_prop = RNA_struct_find_property(&item_ptr, "rotation");
      float rotation = rot_prop ? RNA_property_float_get(&item_ptr, rot_prop) : 0.0f;

      /* Inverse-rotate mouse into textbox local space */
      float local_mx, local_my;
      inverse_rotate_point(mouse_x,
                           mouse_y,
                           pos_x + width / 2.0f,
                           pos_y + height / 2.0f,
                           rotation,
                           &local_mx,
                           &local_my);

      /* Check all 8 handle positions (in unrotated local space) */
      float handle_positions[8][2] = {
          {pos_x, pos_y},
          {pos_x + width / 2, pos_y},
          {pos_x + width, pos_y},
          {pos_x + width, pos_y + height / 2},
          {pos_x + width, pos_y + height},
          {pos_x + width / 2, pos_y + height},
          {pos_x, pos_y + height},
          {pos_x, pos_y + height / 2}
      };

      for (int h = 0; h < 8; h++) {
        float dx = local_mx - handle_positions[h][0];
        float dy = local_my - handle_positions[h][1];
        if (dx * dx + dy * dy < handle_tolerance * handle_tolerance) {
          if (r_element_index)
            *r_element_index = i;
          if (r_element_type)
            *r_element_type = MOODBOARD_ELEMENT_TEXTBOX;
          if (r_pos_x)
            *r_pos_x = pos_x;
          if (r_pos_y)
            *r_pos_y = pos_y;
          if (r_scale)
            *r_scale = 1.0f;
          if (r_width)
            *r_width = width;
          if (r_height)
            *r_height = height;
          return h;
        }
      }
    }
  }

  return -1; /* No handle found */
}

void moodboard_deselect_all(PointerRNA *scene_ptr)
{
  /* Deselect all images */
  PropertyRNA *img_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (img_prop) {
    int image_count = RNA_property_collection_length(scene_ptr, img_prop);
    for (int i = 0; i < image_count; i++) {
      PointerRNA item_ptr;
      RNA_property_collection_lookup_int(scene_ptr, img_prop, i, &item_ptr);
      PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
      if (sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop)) {
        RNA_property_boolean_set(&item_ptr, sel_prop, false);
      }
    }
  }

  /* Deselect all text boxes */
  PropertyRNA *textbox_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_textboxes");
  if (textbox_prop) {
    int textbox_count = RNA_property_collection_length(scene_ptr, textbox_prop);
    for (int i = 0; i < textbox_count; i++) {
      PointerRNA item_ptr;
      RNA_property_collection_lookup_int(scene_ptr, textbox_prop, i, &item_ptr);
      PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
      if (sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop)) {
        RNA_property_boolean_set(&item_ptr, sel_prop, false);
      }
    }
  }

  /* Deselect all groups */
  PropertyRNA *groups_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_groups");
  if (groups_prop) {
    int group_count = RNA_property_collection_length(scene_ptr, groups_prop);
    for (int i = 0; i < group_count; i++) {
      PointerRNA group_ptr;
      RNA_property_collection_lookup_int(scene_ptr, groups_prop, i, &group_ptr);
      PropertyRNA *sel_prop = RNA_struct_find_property(&group_ptr, "selected");
      if (sel_prop && RNA_property_boolean_get(&group_ptr, sel_prop)) {
        RNA_property_boolean_set(&group_ptr, sel_prop, false);
      }
    }
  }

  /* Graph nodes and links share the canvas selection model with media. */
  for (const char *collection_name : {"mixie_moodboard_action_nodes",
                                      "mixie_moodboard_asset_nodes",
                                      "mixie_moodboard_links"})
  {
    PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
    if (!collection) {
      continue;
    }
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(scene_ptr, collection, &iter);
    while (iter.valid) {
      PropertyRNA *selected = RNA_struct_find_property(&iter.ptr, "selected");
      if (selected) {
        RNA_property_boolean_set(&iter.ptr, selected, false);
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }
  if (RNA_struct_find_property(scene_ptr, "mixie_moodboard_active_node_id")) {
    RNA_string_set(scene_ptr, "mixie_moodboard_active_node_id", "");
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Mixie3D Preview Selection
 * \{ */

int mixie_get_sam3d_preview_at_position(const bContext *C,
                                        const ARegion *region,
                                        int mouse_x,
                                        int mouse_y)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return -1;
  }

  /* Layout constants from mixie_intern.hh (must match drawing code) */
  const int PREVIEW_HEIGHT = int(region->winy * SAM3D_PREVIEW_HEIGHT_RATIO);
  const int PREVIEW_PADDING = SAM3D_PREVIEW_PADDING;
  const int PREVIEW_GAP = SAM3D_PREVIEW_GAP;
  const int PREVIEW_THUMB_HEIGHT = PREVIEW_HEIGHT - (2 * PREVIEW_PADDING);

  /* Check if mouse is in preview area */
  if (mouse_y >= PREVIEW_HEIGHT) {
    return -1; /* Click is in main image area, not preview area */
  }

  if (mouse_y < PREVIEW_PADDING || mouse_y >= PREVIEW_HEIGHT - PREVIEW_PADDING) {
    return -1; /* Click is in padding area */
  }

  /* Get segmented history */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *history_prop = RNA_struct_find_property(&scene_ptr, "mixie_segmented_history");

  if (!history_prop) {
    return -1;
  }

  const int history_count = RNA_property_collection_length(&scene_ptr, history_prop);
  if (history_count == 0) {
    return -1;
  }

  /* Calculate which thumbnail was clicked - need to iterate to get each thumbnail's width */
  int current_x = PREVIEW_PADDING;

  /* Iterate through history items manually to have better control over scope */
  for (int idx = 0; idx < history_count; idx++) {
    PointerRNA item_ptr;
    if (!RNA_property_collection_lookup_int(&scene_ptr, history_prop, idx, &item_ptr)) {
      continue;
    }

    /* Get image from history item */
    PropertyRNA *history_image_prop = RNA_struct_find_property(&item_ptr, "image");
    if (!history_image_prop) {
      continue;
    }

    PointerRNA history_image_ptr = RNA_property_pointer_get(&item_ptr, history_image_prop);
    Image *history_image = (Image *)history_image_ptr.data;

    if (!history_image) {
      continue;
    }

    /* Calculate thumbnail width maintaining aspect ratio */
    int thumb_width = PREVIEW_THUMB_HEIGHT; /* Default to square */

    void *lock;
    ImBuf *ibuf = BKE_image_acquire_ibuf(history_image, nullptr, &lock);

    if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
      /* Maintain aspect ratio, fit to height */
      float aspect_ratio = float(ibuf->x) / float(ibuf->y);
      thumb_width = int(PREVIEW_THUMB_HEIGHT * aspect_ratio);
    }
    BKE_image_release_ibuf(history_image, ibuf, lock);

    /* Check if we're past the region width */
    if (current_x + thumb_width > region->winx - PREVIEW_PADDING) {
      break;
    }

    /* Check if mouse is within this thumbnail */
    if (mouse_x >= current_x && mouse_x < current_x + thumb_width) {
      return idx;
    }

    /* Move to next position */
    current_x += thumb_width + PREVIEW_GAP;
  }

  return -1;
}

int mixie_get_sam3d_preview_delete_at_position(const bContext *C,
                                               ARegion *region,
                                               const int mouse_x,
                                               const int mouse_y)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return -1;
  }

  /* Layout constants from mixie_intern.hh (must match drawing code) */
  const int PREVIEW_HEIGHT = int(region->winy * SAM3D_PREVIEW_HEIGHT_RATIO);
  const int PREVIEW_PADDING = SAM3D_PREVIEW_PADDING;
  const int PREVIEW_GAP = SAM3D_PREVIEW_GAP;
  const int PREVIEW_THUMB_HEIGHT = PREVIEW_HEIGHT - (2 * PREVIEW_PADDING);
  const int delete_btn_size = SAM3D_DELETE_BTN_SIZE;
  const int delete_btn_margin = SAM3D_DELETE_BTN_MARGIN;

  /* Check if mouse is in preview area */
  if (mouse_y >= PREVIEW_HEIGHT) {
    return -1;
  }

  if (mouse_y < PREVIEW_PADDING || mouse_y >= PREVIEW_HEIGHT - PREVIEW_PADDING) {
    return -1;
  }

  /* Get segmented history */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *history_prop = RNA_struct_find_property(&scene_ptr, "mixie_segmented_history");

  if (!history_prop) {
    return -1;
  }

  const int history_count = RNA_property_collection_length(&scene_ptr, history_prop);
  if (history_count == 0) {
    return -1;
  }

  /* Calculate which thumbnail's delete button was clicked */
  int current_x = PREVIEW_PADDING;

  for (int idx = 0; idx < history_count; idx++) {
    PointerRNA item_ptr;
    if (!RNA_property_collection_lookup_int(&scene_ptr, history_prop, idx, &item_ptr)) {
      continue;
    }

    PropertyRNA *history_image_prop = RNA_struct_find_property(&item_ptr, "image");
    if (!history_image_prop) {
      continue;
    }

    PointerRNA history_image_ptr = RNA_property_pointer_get(&item_ptr, history_image_prop);
    Image *history_image = (Image *)history_image_ptr.data;

    if (!history_image) {
      continue;
    }

    /* Calculate thumbnail width maintaining aspect ratio */
    int thumb_width = PREVIEW_THUMB_HEIGHT;

    void *lock;
    ImBuf *ibuf = BKE_image_acquire_ibuf(history_image, nullptr, &lock);

    if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
      float aspect_ratio = float(ibuf->x) / float(ibuf->y);
      thumb_width = int(PREVIEW_THUMB_HEIGHT * aspect_ratio);
    }
    BKE_image_release_ibuf(history_image, ibuf, lock);

    if (current_x + thumb_width > region->winx - PREVIEW_PADDING) {
      break;
    }

    /* Check if mouse is within this thumbnail's delete button */
    if (mouse_x >= current_x && mouse_x < current_x + thumb_width) {
      /* Calculate delete button position (top-right corner of thumbnail) */
      const int thumb_y = PREVIEW_PADDING;
      const int delete_btn_x = current_x + thumb_width - delete_btn_size - delete_btn_margin;
      const int delete_btn_y = thumb_y + PREVIEW_THUMB_HEIGHT - delete_btn_size - delete_btn_margin;

      /* Check if click is within delete button bounds */
      if (mouse_x >= delete_btn_x && mouse_x < delete_btn_x + delete_btn_size &&
          mouse_y >= delete_btn_y && mouse_y < delete_btn_y + delete_btn_size)
      {
        return idx;
      }
    }

    current_x += thumb_width + PREVIEW_GAP;
  }

  return -1;
}

/** \} */

}  // namespace blender::ed::mixie
