/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard crop operator - crops images with C++ acceleration
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Crop Image Operator
 * \{ */

/**
 * Crop an image in the moodboard and add the cropped version as a new item.
 * The original image is preserved; the new cropped image is placed offset to the right.
 * Uses fast C++ pixel copying for performance.
 */
static wmOperatorStatus moodboard_crop_image_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);

  /* Get parameters from operator properties */
  int image_index = RNA_int_get(op->ptr, "image_index");
  float x1 = RNA_float_get(op->ptr, "x1");
  float y1 = RNA_float_get(op->ptr, "y1");
  float x2 = RNA_float_get(op->ptr, "x2");
  float y2 = RNA_float_get(op->ptr, "y2");

  /* Normalize box coordinates */
  float box_x1 = std::min(x1, x2);
  float box_x2 = std::max(x1, x2);
  float box_y1 = std::min(y1, y2);
  float box_y2 = std::max(y1, y2);

  /* Clamp to 0-1 range */
  box_x1 = std::max(0.0f, std::min(1.0f, box_x1));
  box_x2 = std::max(0.0f, std::min(1.0f, box_x2));
  box_y1 = std::max(0.0f, std::min(1.0f, box_y1));
  box_y2 = std::max(0.0f, std::min(1.0f, box_y2));

  /* Get source image from moodboard collection */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *images_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (!images_prop) {
    BKE_report(op->reports, RPT_ERROR, "Moodboard images collection not found");
    return OPERATOR_CANCELLED;
  }

  int image_count = RNA_property_collection_length(&scene_ptr, images_prop);
  if (image_index < 0 || image_index >= image_count) {
    BKE_report(op->reports, RPT_ERROR, "Invalid image index");
    return OPERATOR_CANCELLED;
  }

  PointerRNA img_item_ptr;
  RNA_property_collection_lookup_int(&scene_ptr, images_prop, image_index, &img_item_ptr);

  PropertyRNA *image_prop = RNA_struct_find_property(&img_item_ptr, "image");
  PointerRNA image_ptr = RNA_property_pointer_get(&img_item_ptr, image_prop);
  Image *src_image = (Image *)image_ptr.data;

  if (!src_image) {
    BKE_report(op->reports, RPT_ERROR, "Source image not found");
    return OPERATOR_CANCELLED;
  }

  /* Get source image buffer */
  void *lock;
  ImBuf *src_ibuf = BKE_image_acquire_ibuf(src_image, nullptr, &lock);
  if (!src_ibuf) {
    BKE_report(op->reports, RPT_ERROR, "Could not acquire source image buffer");
    return OPERATOR_CANCELLED;
  }

  int src_width = src_ibuf->x;
  int src_height = src_ibuf->y;

  /* Calculate pixel coordinates */
  int px1 = int(box_x1 * src_width);
  int px2 = int(box_x2 * src_width);
  int py1 = int(box_y1 * src_height);
  int py2 = int(box_y2 * src_height);

  int crop_width = px2 - px1;
  int crop_height = py2 - py1;

  if (crop_width <= 0 || crop_height <= 0) {
    BKE_image_release_ibuf(src_image, src_ibuf, lock);
    BKE_report(op->reports, RPT_ERROR, "Invalid crop region");
    return OPERATOR_CANCELLED;
  }

  /* Create cropped image */
  char crop_name[MAX_ID_NAME - 2];
  BLI_snprintf(crop_name, sizeof(crop_name), "%s_cropped", src_image->id.name + 2);

  const float black_color[4] = {0.0f, 0.0f, 0.0f, 1.0f};
  Image *crop_image = BKE_image_add_generated(bmain,
                                              crop_width,
                                              crop_height,
                                              crop_name,
                                              32,
                                              true,  /* floatbuf */
                                              IMA_GENTYPE_BLANK,
                                              black_color,
                                              false,
                                              false,
                                              false);
  if (!crop_image) {
    BKE_image_release_ibuf(src_image, src_ibuf, lock);
    BKE_report(op->reports, RPT_ERROR, "Could not create cropped image");
    return OPERATOR_CANCELLED;
  }

  /* Get crop image buffer */
  void *crop_lock;
  ImBuf *crop_ibuf = BKE_image_acquire_ibuf(crop_image, nullptr, &crop_lock);
  if (!crop_ibuf || !crop_ibuf->float_buffer.data) {
    BKE_image_release_ibuf(src_image, src_ibuf, lock);
    BKE_image_release_ibuf(crop_image, crop_ibuf, crop_lock);
    BKE_report(op->reports, RPT_ERROR, "Could not acquire crop buffer");
    return OPERATOR_CANCELLED;
  }

  /* Copy pixels - fast C++ loop */
  float *dst_pixels = crop_ibuf->float_buffer.data;
  bool src_has_float = (src_ibuf->float_buffer.data != nullptr);

  for (int y = 0; y < crop_height; y++) {
    int src_y = py1 + y;
    for (int x = 0; x < crop_width; x++) {
      int src_x = px1 + x;
      int dst_idx = (y * crop_width + x) * 4;

      if (src_has_float) {
        /* Source is float */
        int src_idx = (src_y * src_width + src_x) * 4;
        float *src_pixels = src_ibuf->float_buffer.data;
        dst_pixels[dst_idx + 0] = src_pixels[src_idx + 0];
        dst_pixels[dst_idx + 1] = src_pixels[src_idx + 1];
        dst_pixels[dst_idx + 2] = src_pixels[src_idx + 2];
        dst_pixels[dst_idx + 3] = src_pixels[src_idx + 3];
      }
      else if (src_ibuf->byte_buffer.data) {
        /* Source is byte, convert to float */
        int src_idx = (src_y * src_width + src_x) * 4;
        uchar *src_bytes = src_ibuf->byte_buffer.data;
        dst_pixels[dst_idx + 0] = src_bytes[src_idx + 0] / 255.0f;
        dst_pixels[dst_idx + 1] = src_bytes[src_idx + 1] / 255.0f;
        dst_pixels[dst_idx + 2] = src_bytes[src_idx + 2] / 255.0f;
        dst_pixels[dst_idx + 3] = src_bytes[src_idx + 3] / 255.0f;
      }
    }
  }

  BKE_image_release_ibuf(src_image, src_ibuf, lock);
  BKE_image_mark_dirty(crop_image, crop_ibuf);
  BKE_image_release_ibuf(crop_image, crop_ibuf, crop_lock);

  /* Read original item properties */
  float orig_pos_x = RNA_float_get(&img_item_ptr, "position_x");
  float orig_pos_y = RNA_float_get(&img_item_ptr, "position_y");
  float orig_scale = RNA_float_get(&img_item_ptr, "scale");
  float orig_rotation = RNA_float_get(&img_item_ptr, "rotation");
  bool orig_flip_h = RNA_boolean_get(&img_item_ptr, "flip_horizontal");
  bool orig_flip_v = RNA_boolean_get(&img_item_ptr, "flip_vertical");
  int orig_z_order = RNA_int_get(&img_item_ptr, "z_order");

  /* Deselect the original image */
  RNA_boolean_set(&img_item_ptr, "selected", false);

  /* Calculate offset: place new image to the right of the original */
  float orig_display_width = MOODBOARD_IMAGE_BASE_SIZE * orig_scale;
  float offset_x = orig_display_width + 50.0f;

  /* Scale the cropped item so it occupies the same canvas footprint as the
   * region it was taken from. display_width = BASE * scale is width-only and
   * does not account for the new image's pixel size, so copying orig_scale
   * verbatim would render any crop at the original's full canvas width.
   * Multiplying by the crop's normalized width preserves the aspect-correct
   * footprint (height follows from the new image's aspect ratio). */
  float new_scale = orig_scale * (box_x2 - box_x1);

  /* Add a new item to the moodboard collection */
  PointerRNA new_item_ptr;
  RNA_property_collection_add(&scene_ptr, images_prop, &new_item_ptr);

  /* Set the cropped image and copy properties from original */
  PointerRNA crop_image_ptr = RNA_id_pointer_create(&crop_image->id);
  RNA_pointer_set(&new_item_ptr, "image", crop_image_ptr);
  RNA_float_set(&new_item_ptr, "position_x", orig_pos_x + offset_x);
  RNA_float_set(&new_item_ptr, "position_y", orig_pos_y);
  RNA_float_set(&new_item_ptr, "scale", new_scale);
  RNA_float_set(&new_item_ptr, "rotation", orig_rotation);
  RNA_boolean_set(&new_item_ptr, "flip_horizontal", orig_flip_h);
  RNA_boolean_set(&new_item_ptr, "flip_vertical", orig_flip_v);
  RNA_boolean_set(&new_item_ptr, "selected", true);
  RNA_int_set(&new_item_ptr, "z_order", orig_z_order + 1);
  RNA_int_set(&new_item_ptr, "group_index", -1);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, crop_image);
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  ED_area_tag_redraw(CTX_wm_area(C));

  return OPERATOR_FINISHED;
}

/** \} */

}  // namespace blender::ed::mixie

/* -------------------------------------------------------------------- */
/** \name Operator Registration (C linkage)
 * \{ */

void MIXIE_OT_moodboard_crop_image(wmOperatorType *ot)
{
  ot->name = "Crop Image";
  ot->idname = "MIXIE_OT_moodboard_crop_image";
  ot->description = "Crop an image in the moodboard (C++ accelerated)";

  ot->exec = blender::ed::mixie::moodboard_crop_image_exec;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_int(ot->srna, "image_index", -1, -1, INT_MAX, "Image Index", "Index of the source image in moodboard", -1, 1000);
  RNA_def_float(ot->srna, "x1", 0.0f, 0.0f, 1.0f, "X1", "Crop start X (normalized 0-1)", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "y1", 0.0f, 0.0f, 1.0f, "Y1", "Crop start Y (normalized 0-1)", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "x2", 1.0f, 0.0f, 1.0f, "X2", "Crop end X (normalized 0-1)", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "y2", 1.0f, 0.0f, 1.0f, "Y2", "Crop end Y (normalized 0-1)", 0.0f, 1.0f);
}

/** \} */
