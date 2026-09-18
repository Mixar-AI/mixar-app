/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard drop image or video operator
 */

#include "mixie_moodboard_ops_common.hh"
#include "BLI_math_vector_types.hh"
#include "RNA_prototypes.hh"

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

  /* Loading allocates a datablock before decoding. Reject corrupt stills as
   * well as invalid/audio-only movies before adding an empty board card. */
  {
    ImageUser iuser{};
    BKE_imageuser_default(&iuser);
    iuser.frames = 0;
    iuser.framenr = 1;

    void *lock = nullptr;
    ImBuf *ibuf = BKE_image_acquire_ibuf(image, &iuser, &lock);
    const bool valid = ibuf && ibuf->x > 0 && ibuf->y > 0;
    BKE_image_release_ibuf(image, ibuf, lock);
    if (!valid) {
      BKE_reportf(reports, RPT_WARNING, "Cannot decode media preview: %s", filepath);
      BKE_id_free(bmain, image);
      return nullptr;
    }
  }

  if (image->source != IMA_SRC_MOVIE) {
    BKE_image_packfiles(reports, image, BKE_main_blendfile_path(bmain));
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
  const bool center_on_drop = RNA_boolean_get(op->ptr, "center_on_drop");

  std::vector<Image *> media_to_process;

  RNA_BEGIN (op->ptr, file, "files") {
    char *path = RNA_string_get_alloc(&file, "name", nullptr, 0, nullptr);
    if (Image *image = moodboard_media_load(bmain, path, op->reports)) {
      media_to_process.push_back(image);
    }
    MEM_delete_void(static_cast<void *>(path));
  }
  RNA_END;

  /* Keep the legacy scripted payload; native drags use lossless file lists. */
  if (RNA_collection_length(op->ptr, "files") == 0 &&
      RNA_struct_property_is_set(op->ptr, "multi_filepaths")) {
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
  float next_top = pos_y;
  rctf added_bounds;
  BLI_rctf_init_minmax(&added_bounds);

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

      int width, height;
      BKE_image_get_size(image, nullptr, &width, &height);
      /* Batch thumbnails fit one common longest-edge size. A portrait must
       * not dominate the entire framed batch or cover the following image. */
      const float display_scale = media_to_process.size() > 1 && height > width && width > 0 ?
                                      float(width) / float(height) : 1.0f;
      const float display_width = MOODBOARD_IMAGE_BASE_SIZE * display_scale;
      const float display_height = width > 0 ? display_width * float(height) / float(width) :
                                              display_width;
      const float current_x = center_on_drop ? pos_x - display_width * 0.5f : pos_x;
      const float current_y = added_count == 0 ?
                                  (center_on_drop ? pos_y - display_height * 0.5f : pos_y) :
                                  next_top - display_height;
      next_top = current_y - offset_step;
      BLI_rctf_do_minmax_v(&added_bounds, float2(current_x, current_y));
      BLI_rctf_do_minmax_v(
          &added_bounds, float2(current_x + display_width, current_y + display_height));

      RNA_property_float_set(&item_ptr, pos_x_prop, current_x);
      RNA_property_float_set(&item_ptr, pos_y_prop, current_y);
      RNA_property_float_set(&item_ptr, scale_prop, display_scale);

      /* Set z-order to be on top */
      int image_count_val = RNA_property_collection_length(&scene_ptr, prop);
      RNA_property_int_set(&item_ptr, z_order_prop, image_count_val - 1);

      added_count++;
    }
  }

  if (added_count == 0) {
    return OPERATOR_CANCELLED;
  }

  const ScrArea *area = CTX_wm_area(C);
  const WorkSpace *workspace = CTX_wm_workspace(C);
  if (from_drop && area && area->spacetype == SPACE_VIEW3D && workspace &&
      STREQ(workspace->id.name + 2, "Zen Mode"))
  {
    /* Successful drops reveal the drawer. Never toggle: another reference
     * arriving while open must keep it open. The drawer clock eases to 1. */
    PointerRNA wm_ptr = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
    if (PropertyRNA *target = RNA_struct_find_property(&wm_ptr, "mixar_moodboard_drawer_target")) {
      RNA_property_int_set(&wm_ptr, target, 1);
    }
  }

  if (from_drop) {
    PointerRNA frame = WM_operator_properties_create("MIXIE_OT_moodboard_ensure_visible");
    RNA_float_set(&frame, "x", added_bounds.xmin);
    RNA_float_set(&frame, "y", added_bounds.ymin);
    RNA_float_set(&frame, "width", BLI_rctf_size_x(&added_bounds));
    RNA_float_set(&frame, "height", BLI_rctf_size_y(&added_bounds));
    WM_operator_name_call(
        C, "MIXIE_OT_moodboard_ensure_visible", wm::OpCallContext::ExecDefault, &frame, nullptr);
    WM_operator_properties_free(&frame);
  }

  /* Trigger redraw */
  WM_event_add_notifier(C, NC_SCENE | ND_SEQUENCER, scene);
  ED_area_tag_redraw(CTX_wm_area(C));

  if (from_drop) {
    if (added_count == 1) {
       BKE_reportf(op->reports,
                RPT_INFO,
                "Added '%s' to moodboard",
                media_to_process[0]->id.name + 2);
    } else {
       BKE_reportf(op->reports,
                RPT_INFO,
                "Added %d references to moodboard",
                added_count);
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

  /* UNDO only. Every property below is `PROP_SKIP_SAVE` so that a drop payload
   * cannot contaminate the next one, which leaves REGISTER with nothing to put
   * in the redo panel: it drew an empty block that collapsed to its minimum
   * width and clipped its own header to "Drop Media to Moodboar", then stayed
   * on screen as the last operator through unrelated later actions. */
  ot->flag = OPTYPE_UNDO;

  RNA_def_string(
      ot->srna, "filepath", nullptr, FILE_MAX, "File Path", "Path to image or video file");
  RNA_def_string(ot->srna, "image_name", nullptr, MAX_ID_NAME - 2, "Image Name", "Name of existing image datablock");
  RNA_def_string(ot->srna, "multi_filepaths", nullptr, 0, "Multi File Paths", "Pipe-separated list of file paths for multi-file drops");
  RNA_def_collection_runtime(ot->srna, "files", RNA_OperatorFileListElement, "Files", "Dropped paths");
  RNA_def_float(ot->srna, "position_x", 0.0f, -FLT_MAX, FLT_MAX, "Position X", "X position on the moodboard canvas", -10000.0f, 10000.0f);
  RNA_def_float(ot->srna, "position_y", 0.0f, -FLT_MAX, FLT_MAX, "Position Y", "Y position on the moodboard canvas", -10000.0f, 10000.0f);
  RNA_def_boolean(ot->srna, "from_drop", false, "From Drop", "Whether this was invoked from a drag-drop operation");
  RNA_def_boolean(ot->srna, "center_on_drop", false, "Center", "Center viewport references in the drawer");
  /* Drop payloads are one-shot; REGISTER's last-used values must not leak a
   * previous filepath into a later Image-ID drop or scripted import. */
  for (const char *name : {"filepath", "files", "image_name", "multi_filepaths", "position_x",
                           "position_y", "from_drop", "center_on_drop"})
  {
    RNA_def_property_flag(RNA_struct_type_find_property(ot->srna, name), PROP_SKIP_SAVE);
  }
}

/** \} */
}  // namespace blender
