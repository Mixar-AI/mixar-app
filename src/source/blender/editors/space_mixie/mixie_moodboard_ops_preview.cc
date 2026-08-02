/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Native moodboard movie preview window.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_string_utf8.h"

#include "ED_image.hh"

namespace blender::ed::mixie {

static Image *moodboard_item_image(PointerRNA *scene_ptr, const int index) {
  PropertyRNA *items_prop =
      RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!items_prop || index < 0 ||
      index >= RNA_property_collection_length(scene_ptr, items_prop)) {
    return nullptr;
  }

  PointerRNA item_ptr;
  RNA_property_collection_lookup_int(scene_ptr, items_prop, index, &item_ptr);
  PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
  if (!image_prop) {
    return nullptr;
  }

  PointerRNA image_ptr = RNA_property_pointer_get(&item_ptr, image_prop);
  return static_cast<Image *>(image_ptr.data);
}

bool moodboard_item_is_video(PointerRNA *scene_ptr, const int index) {
  const Image *image = moodboard_item_image(scene_ptr, index);
  return image && image->source == IMA_SRC_MOVIE;
}

bool moodboard_open_video_preview(bContext *C, PointerRNA *scene_ptr,
                                  const int index, ReportList *reports) {
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  Image *image = moodboard_item_image(scene_ptr, index);
  if (!image || image->source != IMA_SRC_MOVIE) {
    BKE_report(reports, RPT_WARNING, "Selected moodboard item is not a video");
    return false;
  }

  /* Decode frame one before creating a window. Besides validating the source,
   * this discovers the frame count and dimensions used to fit the preview. */
  ImageUser preview_user{};
  BKE_imageuser_default(&preview_user);
  preview_user.frames = 0;
  preview_user.framenr = 1;

  void *lock = nullptr;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, &preview_user, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    BKE_reportf(reports, RPT_ERROR, "Cannot decode video: %s", image->filepath);
    return false;
  }
  const int video_width = ibuf->x;
  const int video_height = ibuf->y;
  const int frame_count = std::max(preview_user.frames, 1);
  BKE_image_release_ibuf(image, ibuf, lock);

  char title[MAX_ID_NAME + 64];
  SNPRINTF_UTF8(title, "Video Preview - %s (Spacebar to Play)",
                image->id.name + 2);
  wmWindow *window = WM_window_open_temp(C, title, SPACE_IMAGE, false);
  if (!window) {
    BKE_report(reports, RPT_ERROR, "Failed to open video preview window");
    return false;
  }

  SpaceImage *sima = CTX_wm_space_image(C);
  if (!sima) {
    BKE_report(reports, RPT_ERROR, "Video preview Image Editor is unavailable");
    return false;
  }

  sima->mode = SI_MODE_VIEW;
  sima->pin = true;
  ED_space_image_set(bmain, sima, image, false);
  sima->iuser.scene = scene;
  sima->iuser.frames = frame_count;
  sima->iuser.sfra = scene ? scene->r.cfra : 1;
  sima->iuser.framenr = 1;
  sima->iuser.offset = 0;
  sima->iuser.cycl = true;
  sima->iuser.flag |= IMA_ANIM_ALWAYS;

  /* Fit the video inside the new 800x600 editor instead of opening large
   * sources at 1:1 and making the user hunt for View All. */
  const float available_width = std::max(float(window->sizex) - 48.0f, 1.0f);
  const float available_height = std::max(float(window->sizey) - 96.0f, 1.0f);
  const float fit_zoom = std::min(available_width / float(video_width),
                                  available_height / float(video_height));
  sima->zoom = std::clamp(fit_zoom, 0.01f, 1.0f);
  sima->xof = 0.0f;
  sima->yof = 0.0f;

  ED_area_tag_redraw(CTX_wm_area(C));
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);
  return true;
}

} // namespace blender::ed::mixie
