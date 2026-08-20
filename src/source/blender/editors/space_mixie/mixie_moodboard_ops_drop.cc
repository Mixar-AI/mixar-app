/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard drop image or video operator
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

static bool moodboard_media_path_supported(const char *filepath)
{
  return BLI_path_extension_check_array(filepath, imb_ext_image) ||
         BLI_path_extension_check_array(filepath, imb_ext_movie);
}

static Image *moodboard_media_load(Main *bmain, const char *filepath, ReportList *reports)
{
  if (!moodboard_media_path_supported(filepath)) {
    BKE_reportf(reports, RPT_WARNING, "Unsupported moodboard media: %s", filepath);
    return nullptr;
  }

  Image *image = BKE_image_load(bmain, filepath);
  if (!image) {
    BKE_reportf(reports, RPT_WARNING, "Cannot load moodboard media: %s", filepath);
    return nullptr;
  }

  /* BKE_image_load creates a movie datablock from the extension before it
   * decodes a frame. Decode frame one now so invalid/audio-only files are
   * rejected and the moodboard immediately has real preview dimensions. */
  if (image->source == IMA_SRC_MOVIE) {
    ImageUser iuser{};
    BKE_imageuser_default(&iuser);
    iuser.frames = 0;
    iuser.framenr = 1;

    void *lock = nullptr;
    ImBuf *ibuf = BKE_image_acquire_ibuf(image, &iuser, &lock);
    const bool valid = ibuf && ibuf->x > 0 && ibuf->y > 0;
    BKE_image_release_ibuf(image, ibuf, lock);
    if (!valid) {
      BKE_reportf(reports, RPT_WARNING, "Cannot decode video preview: %s", filepath);
      BKE_id_free(bmain, image);
      return nullptr;
    }
  }

  return image;
}

/* -------------------------------------------------------------------- */
/** \name Moodboard Drop Image Operator
 * \{ */

static wmOperatorStatus moodboard_drop_image_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  bool from_drop = RNA_boolean_get(op->ptr, "from_drop");
  float pos_x = RNA_float_get(op->ptr, "position_x");
  float pos_y = RNA_float_get(op->ptr, "position_y");

  std::vector<Image *> media_to_process;

  /* Check for multi-file drop first */
  if (RNA_struct_property_is_set(op->ptr, "multi_filepaths")) {
    char *multi_paths_cstr = RNA_string_get_alloc(op->ptr, "multi_filepaths", nullptr, 0, nullptr);
    if (multi_paths_cstr) {
      std::string multi_paths(multi_paths_cstr);
      MEM_delete_void(static_cast<void *>(multi_paths_cstr));

      std::stringstream ss(multi_paths);
      std::string segment;
      while (std::getline(ss, segment, '|')) {
        if (!segment.empty()) {
          Image *img = moodboard_media_load(bmain, segment.c_str(), op->reports);
          if (img) {
            media_to_process.push_back(img);
          }
        }
      }
    }
  }

  /* Fallback to single file/image if no multi-file processed */
  if (media_to_process.empty()) {
    Image *image = nullptr;
    if (RNA_struct_property_is_set(op->ptr, "filepath")) {
      char filepath[FILE_MAX];
      RNA_string_get(op->ptr, "filepath", filepath);

      image = moodboard_media_load(bmain, filepath, op->reports);
      if (!image) {
        BKE_reportf(op->reports, RPT_ERROR, "Cannot load media from path: %s", filepath);
        return OPERATOR_CANCELLED;
      }
      /* Keep original colorspace (typically sRGB) - moodboard rendering handles display */
    }
    else if (RNA_struct_property_is_set(op->ptr, "image_name")) {
      char image_name[MAX_ID_NAME - 2];
      RNA_string_get(op->ptr, "image_name", image_name);

      image = reinterpret_cast<Image *>(BKE_libblock_find_name(bmain, ID_IM, image_name));
      if (!image) {
        BKE_reportf(op->reports, RPT_ERROR, "Cannot find image: %s", image_name);
        return OPERATOR_CANCELLED;
      }
    }

    if (image) {
      media_to_process.push_back(image);
    }
  }

  if (media_to_process.empty()) {
    BKE_report(op->reports, RPT_ERROR, "No supported media to add");
    return OPERATOR_CANCELLED;
  }

  /* Add to moodboard collection via Python */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");

  if (!prop) {
    BKE_report(op->reports, RPT_ERROR, "Moodboard images collection not found");
    return OPERATOR_CANCELLED;
  }

  int added_count = 0;
  float offset_step = 30.0f; // Offset for stacked images

  for (size_t i = 0; i < media_to_process.size(); i++) {
    Image *image = media_to_process[i];

    /* Skip viewer images */
    if (image->source == IMA_SRC_VIEWER) {
      BKE_reportf(
          op->reports, RPT_WARNING, "Cannot add viewer image '%s' to moodboard", image->id.name + 2);
      continue;
    }

    /* Create new item in collection */
    PointerRNA item_ptr;
    RNA_property_collection_add(&scene_ptr, prop, &item_ptr);

    /* Set properties */
    PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
    PropertyRNA *pos_x_prop = RNA_struct_find_property(&item_ptr, "position_x");
    PropertyRNA *pos_y_prop = RNA_struct_find_property(&item_ptr, "position_y");
    PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");
    PropertyRNA *z_order_prop = RNA_struct_find_property(&item_ptr, "z_order");

    if (image_prop && pos_x_prop && pos_y_prop && scale_prop && z_order_prop) {
      PointerRNA image_ptr = RNA_id_pointer_create(&image->id);
      RNA_property_pointer_set(&item_ptr, image_prop, image_ptr, nullptr);

      // Apply offset for multiple images
      float current_x = pos_x + (i * offset_step);
      float current_y = pos_y - (i * offset_step);

      RNA_property_float_set(&item_ptr, pos_x_prop, current_x);
      RNA_property_float_set(&item_ptr, pos_y_prop, current_y);
      RNA_property_float_set(&item_ptr, scale_prop, 1.0f);

      /* Set z-order to be on top */
      int image_count_val = RNA_property_collection_length(&scene_ptr, prop);
      RNA_property_int_set(&item_ptr, z_order_prop, image_count_val - 1);

      added_count++;
    }
  }

  if (added_count == 0) {
    return OPERATOR_CANCELLED;
  }

  /* Trigger redraw */
  WM_event_add_notifier(C, NC_SCENE | ND_SEQUENCER, scene);
  ED_area_tag_redraw(CTX_wm_area(C));

  if (from_drop) {
    if (added_count == 1) {
       BKE_reportf(op->reports,
                RPT_INFO,
                "Added '%s' to moodboard at (%.1f, %.1f)",
                media_to_process[0]->id.name + 2,
                pos_x,
                pos_y);
    } else {
       BKE_reportf(op->reports,
                RPT_INFO,
                "Added %d media items to moodboard starting at (%.1f, %.1f)",
                added_count,
                pos_x,
                pos_y);
    }
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus moodboard_drop_image_invoke(bContext *C,
                                                    wmOperator *op,
                                                    const wmEvent * /*event*/)
{
  if (!RNA_struct_property_is_set(op->ptr, "from_drop")) {
    return OPERATOR_CANCELLED;
  }

  return moodboard_drop_image_exec(C, op);
}

/** \} */

}  // namespace blender::ed::mixie


/* Mixar 5.2 port: operator registrations live in namespace blender. */
namespace blender {
/* -------------------------------------------------------------------- */
/** \name Operator Registration (C linkage)
 * \{ */

void MIXIE_OT_moodboard_drop_image(wmOperatorType *ot)
{
  ot->name = "Drop Media to Moodboard";
  ot->idname = "MIXIE_OT_moodboard_drop_image";
  ot->description = "Add an image or video to the moodboard at the drop position";

  ot->exec = blender::ed::mixie::moodboard_drop_image_exec;
  ot->invoke = blender::ed::mixie::moodboard_drop_image_invoke;
  ot->poll = nullptr;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_string(
      ot->srna, "filepath", nullptr, FILE_MAX, "File Path", "Path to image or video file");
  RNA_def_string(ot->srna, "image_name", nullptr, MAX_ID_NAME - 2, "Image Name", "Name of existing image datablock");
  RNA_def_string(ot->srna, "multi_filepaths", nullptr, 0, "Multi File Paths", "Pipe-separated list of file paths for multi-file drops");
  RNA_def_float(ot->srna, "position_x", 0.0f, -FLT_MAX, FLT_MAX, "Position X", "X position on the moodboard canvas", -10000.0f, 10000.0f);
  RNA_def_float(ot->srna, "position_y", 0.0f, -FLT_MAX, FLT_MAX, "Position Y", "Y position on the moodboard canvas", -10000.0f, 10000.0f);
  RNA_def_boolean(ot->srna, "from_drop", false, "From Drop", "Whether this was invoked from a drag-drop operation");
}

/** \} */
}  // namespace blender
