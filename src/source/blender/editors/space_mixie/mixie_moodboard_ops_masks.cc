/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard mask generation operators - box and lasso masks with C++ acceleration
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Mask Generation Operators
 * \{ */

/**
 * Fast point-in-polygon test using ray casting algorithm.
 */
static bool point_in_polygon_fast(float x, float y, const float *polygon, int num_points)
{
  bool inside = false;
  int j = num_points - 1;

  for (int i = 0; i < num_points; i++) {
    float xi = polygon[i * 2];
    float yi = polygon[i * 2 + 1];
    float xj = polygon[j * 2];
    float yj = polygon[j * 2 + 1];

    if (((yi > y) != (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi + 1e-10f) + xi)) {
      inside = !inside;
    }
    j = i;
  }
  return inside;
}

/**
 * Generate a black and white box mask image and add it to the moodboard.
 */
static wmOperatorStatus moodboard_generate_box_mask_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);

  /* Get parameters from operator properties */
  int image_index = RNA_int_get(op->ptr, "image_index");
  float x1 = RNA_float_get(op->ptr, "x1");
  float y1 = RNA_float_get(op->ptr, "y1");
  float x2 = RNA_float_get(op->ptr, "x2");
  float y2 = RNA_float_get(op->ptr, "y2");
  bool invert = RNA_boolean_get(op->ptr, "invert");
  float offset_x = RNA_float_get(op->ptr, "offset_x");

  /* Normalize box coordinates */
  float box_x1 = std::min(x1, x2);
  float box_x2 = std::max(x1, x2);
  float box_y1 = std::min(y1, y2);
  float box_y2 = std::max(y1, y2);

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

  /* Get image dimensions */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(src_image, nullptr, &lock);
  if (!ibuf) {
    BKE_report(op->reports, RPT_ERROR, "Could not acquire image buffer");
    return OPERATOR_CANCELLED;
  }
  int width = ibuf->x;
  int height = ibuf->y;
  BKE_image_release_ibuf(src_image, ibuf, lock);

  /* Create new mask image */
  char mask_name[MAX_ID_NAME - 2];
  BLI_snprintf(mask_name, sizeof(mask_name), "%s_mask", src_image->id.name + 2);

  const float black_color[4] = {0.0f, 0.0f, 0.0f, 1.0f};
  Image *mask_image = BKE_image_add_generated(bmain,
                                              width,
                                              height,
                                              mask_name,
                                              32,
                                              true,  /* floatbuf - need float buffer for pixel writing */
                                              IMA_GENTYPE_BLANK,
                                              black_color,
                                              false,
                                              false,
                                              false);
  if (!mask_image) {
    BKE_report(op->reports, RPT_ERROR, "Could not create mask image");
    return OPERATOR_CANCELLED;
  }

  /* Generate mask pixels - this is the fast C++ part */
  ImBuf *mask_ibuf = BKE_image_acquire_ibuf(mask_image, nullptr, &lock);
  if (!mask_ibuf || !mask_ibuf->float_buffer.data) {
    BKE_image_release_ibuf(mask_image, mask_ibuf, lock);
    BKE_report(op->reports, RPT_ERROR, "Could not acquire mask buffer");
    return OPERATOR_CANCELLED;
  }

  float *pixels = mask_ibuf->float_buffer.data;

  for (int y = 0; y < height; y++) {
    float ny = float(y) / float(height);
    for (int x = 0; x < width; x++) {
      float nx = float(x) / float(width);

      bool in_box = (nx >= box_x1 && nx <= box_x2 && ny >= box_y1 && ny <= box_y2);
      float value = (in_box != invert) ? 1.0f : 0.0f;

      int idx = (y * width + x) * 4;
      pixels[idx + 0] = value; /* R */
      pixels[idx + 1] = value; /* G */
      pixels[idx + 2] = value; /* B */
      pixels[idx + 3] = 1.0f;  /* A */
    }
  }

  /* Mark image as dirty so it updates */
  BKE_image_mark_dirty(mask_image, mask_ibuf);

  BKE_image_release_ibuf(mask_image, mask_ibuf, lock);

  /* Get source image position and scale for placing the mask */
  float src_pos_x = RNA_float_get(&img_item_ptr, "position_x");
  float src_pos_y = RNA_float_get(&img_item_ptr, "position_y");
  float src_scale = RNA_float_get(&img_item_ptr, "scale");

  /* Add mask to moodboard collection */
  PointerRNA new_item_ptr;
  RNA_property_collection_add(&scene_ptr, images_prop, &new_item_ptr);

  PointerRNA mask_image_ptr = RNA_id_pointer_create(&mask_image->id);
  RNA_pointer_set(&new_item_ptr, "image", mask_image_ptr);
  RNA_float_set(&new_item_ptr, "position_x", src_pos_x + offset_x);
  RNA_float_set(&new_item_ptr, "position_y", src_pos_y);
  RNA_float_set(&new_item_ptr, "scale", src_scale);
  RNA_int_set(&new_item_ptr, "z_order", image_count);

  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  ED_area_tag_redraw(CTX_wm_area(C));

  return OPERATOR_FINISHED;
}

/**
 * Generate a black and white lasso mask image and add it to the moodboard.
 * Reads lasso points from scene.mixie_edit_tool_state.lasso_points collection.
 */
static wmOperatorStatus moodboard_generate_lasso_mask_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);

  /* Get parameters from operator properties */
  int image_index = RNA_int_get(op->ptr, "image_index");
  bool invert = RNA_boolean_get(op->ptr, "invert");
  float offset_x = RNA_float_get(op->ptr, "offset_x");

  /* Get lasso points from scene's edit tool state */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *state_prop = RNA_struct_find_property(&scene_ptr, "mixie_edit_tool_state");
  if (!state_prop) {
    BKE_report(op->reports, RPT_ERROR, "Edit tool state not found");
    return OPERATOR_CANCELLED;
  }

  PointerRNA state_ptr = RNA_property_pointer_get(&scene_ptr, state_prop);
  PropertyRNA *lasso_points_prop = RNA_struct_find_property(&state_ptr, "lasso_points");
  if (!lasso_points_prop) {
    BKE_report(op->reports, RPT_ERROR, "Lasso points not found");
    return OPERATOR_CANCELLED;
  }

  int num_points = RNA_property_collection_length(&state_ptr, lasso_points_prop);
  if (num_points < 3) {
    BKE_report(op->reports, RPT_ERROR, "Need at least 3 points for lasso mask");
    return OPERATOR_CANCELLED;
  }

  /* Extract polygon coordinates into array */
  float *polygon = (float *)MEM_new_uninitialized(sizeof(float) * num_points * 2, "lasso_polygon");

  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&state_ptr, lasso_points_prop, &iter);
  int i = 0;
  while (iter.valid && i < num_points) {
    PointerRNA point_ptr = iter.ptr;
    polygon[i * 2] = RNA_float_get(&point_ptr, "x");
    polygon[i * 2 + 1] = RNA_float_get(&point_ptr, "y");
    i++;
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);

  /* Get source image from moodboard collection (scene_ptr already declared above) */
  PropertyRNA *images_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (!images_prop) {
    MEM_freeN(polygon);
    BKE_report(op->reports, RPT_ERROR, "Moodboard images collection not found");
    return OPERATOR_CANCELLED;
  }

  int image_count = RNA_property_collection_length(&scene_ptr, images_prop);
  if (image_index < 0 || image_index >= image_count) {
    MEM_freeN(polygon);
    BKE_report(op->reports, RPT_ERROR, "Invalid image index");
    return OPERATOR_CANCELLED;
  }

  PointerRNA img_item_ptr;
  RNA_property_collection_lookup_int(&scene_ptr, images_prop, image_index, &img_item_ptr);

  PropertyRNA *image_prop = RNA_struct_find_property(&img_item_ptr, "image");
  PointerRNA image_ptr = RNA_property_pointer_get(&img_item_ptr, image_prop);
  Image *src_image = (Image *)image_ptr.data;

  if (!src_image) {
    MEM_freeN(polygon);
    BKE_report(op->reports, RPT_ERROR, "Source image not found");
    return OPERATOR_CANCELLED;
  }

  /* Get image dimensions */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(src_image, nullptr, &lock);
  if (!ibuf) {
    MEM_freeN(polygon);
    BKE_report(op->reports, RPT_ERROR, "Could not acquire image buffer");
    return OPERATOR_CANCELLED;
  }
  int width = ibuf->x;
  int height = ibuf->y;
  BKE_image_release_ibuf(src_image, ibuf, lock);

  /* Create new mask image */
  char mask_name[MAX_ID_NAME - 2];
  BLI_snprintf(mask_name, sizeof(mask_name), "%s_mask", src_image->id.name + 2);

  const float black_color[4] = {0.0f, 0.0f, 0.0f, 1.0f};
  Image *mask_image = BKE_image_add_generated(bmain,
                                              width,
                                              height,
                                              mask_name,
                                              32,
                                              true,  /* floatbuf - need float buffer for pixel writing */
                                              IMA_GENTYPE_BLANK,
                                              black_color,
                                              false,
                                              false,
                                              false);
  if (!mask_image) {
    MEM_freeN(polygon);
    BKE_report(op->reports, RPT_ERROR, "Could not create mask image");
    return OPERATOR_CANCELLED;
  }

  /* Generate mask pixels - this is the fast C++ part */
  ImBuf *mask_ibuf = BKE_image_acquire_ibuf(mask_image, nullptr, &lock);
  if (!mask_ibuf || !mask_ibuf->float_buffer.data) {
    MEM_freeN(polygon);
    BKE_image_release_ibuf(mask_image, mask_ibuf, lock);
    BKE_report(op->reports, RPT_ERROR, "Could not acquire mask buffer");
    return OPERATOR_CANCELLED;
  }

  float *pixels = mask_ibuf->float_buffer.data;

  for (int y = 0; y < height; y++) {
    float ny = float(y) / float(height);
    for (int x = 0; x < width; x++) {
      float nx = float(x) / float(width);

      bool in_poly = point_in_polygon_fast(nx, ny, polygon, num_points);
      float value = (in_poly != invert) ? 1.0f : 0.0f;

      int idx = (y * width + x) * 4;
      pixels[idx + 0] = value; /* R */
      pixels[idx + 1] = value; /* G */
      pixels[idx + 2] = value; /* B */
      pixels[idx + 3] = 1.0f;  /* A */
    }
  }

  MEM_freeN(polygon);

  /* Mark image as dirty so it updates */
  BKE_image_mark_dirty(mask_image, mask_ibuf);

  BKE_image_release_ibuf(mask_image, mask_ibuf, lock);

  /* Get source image position and scale for placing the mask */
  float src_pos_x = RNA_float_get(&img_item_ptr, "position_x");
  float src_pos_y = RNA_float_get(&img_item_ptr, "position_y");
  float src_scale = RNA_float_get(&img_item_ptr, "scale");

  /* Add mask to moodboard collection */
  PointerRNA new_item_ptr;
  RNA_property_collection_add(&scene_ptr, images_prop, &new_item_ptr);

  PointerRNA mask_image_ptr = RNA_id_pointer_create(&mask_image->id);
  RNA_pointer_set(&new_item_ptr, "image", mask_image_ptr);
  RNA_float_set(&new_item_ptr, "position_x", src_pos_x + offset_x);
  RNA_float_set(&new_item_ptr, "position_y", src_pos_y);
  RNA_float_set(&new_item_ptr, "scale", src_scale);
  RNA_int_set(&new_item_ptr, "z_order", image_count);

  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  ED_area_tag_redraw(CTX_wm_area(C));

  return OPERATOR_FINISHED;
}

/** \} */

}  // namespace blender::ed::mixie

/* -------------------------------------------------------------------- */
/** \name Operator Registration (C linkage)
 * \{ */

void MIXIE_OT_moodboard_generate_box_mask(wmOperatorType *ot)
{
  ot->name = "Generate Box Mask";
  ot->idname = "MIXIE_OT_moodboard_generate_box_mask";
  ot->description = "Generate a black and white box mask image (C++ accelerated)";

  ot->exec = blender::ed::mixie::moodboard_generate_box_mask_exec;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_int(ot->srna, "image_index", -1, -1, INT_MAX, "Image Index", "Index of the source image in moodboard", -1, 1000);
  RNA_def_float(ot->srna, "x1", 0.0f, 0.0f, 1.0f, "X1", "Box start X (normalized 0-1)", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "y1", 0.0f, 0.0f, 1.0f, "Y1", "Box start Y (normalized 0-1)", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "x2", 1.0f, 0.0f, 1.0f, "X2", "Box end X (normalized 0-1)", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "y2", 1.0f, 0.0f, 1.0f, "Y2", "Box end Y (normalized 0-1)", 0.0f, 1.0f);
  RNA_def_boolean(ot->srna, "invert", false, "Invert", "Invert the mask");
  RNA_def_float(ot->srna, "offset_x", 750.0f, -FLT_MAX, FLT_MAX, "Offset X", "X offset for placing the mask image", -10000.0f, 10000.0f);
}

void MIXIE_OT_moodboard_generate_lasso_mask(wmOperatorType *ot)
{
  ot->name = "Generate Lasso Mask";
  ot->idname = "MIXIE_OT_moodboard_generate_lasso_mask";
  ot->description = "Generate a black and white lasso mask image (C++ accelerated). Reads points from scene.mixie_edit_tool_state.lasso_points";

  ot->exec = blender::ed::mixie::moodboard_generate_lasso_mask_exec;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_int(ot->srna, "image_index", -1, -1, INT_MAX, "Image Index", "Index of the source image in moodboard", -1, 1000);
  RNA_def_boolean(ot->srna, "invert", false, "Invert", "Invert the mask");
  RNA_def_float(ot->srna, "offset_x", 750.0f, -FLT_MAX, FLT_MAX, "Offset X", "X offset for placing the mask image", -10000.0f, 10000.0f);
}

/** \} */
