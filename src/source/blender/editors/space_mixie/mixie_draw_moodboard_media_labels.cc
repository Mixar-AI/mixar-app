/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Floating "Image"/"Video" label bar over selected standalone media.
 *
 * Split out of #mixie_draw_moodboard_node_ui.cc (500-line rule); drawn into
 * the same screen-space uiBlock as the node controls.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

namespace blender::ed::mixie {

void mixie_draw_moodboard_selected_media_labels(uiBlock *block,
                                                View2D *v2d,
                                                ARegion *region,
                                                PointerRNA *scene_ptr,
                                                const MoodboardGraphCache *cache)
{
  PropertyRNA *images = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!images) {
    return;
  }
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, images, &iter);
  while (iter.valid) {
    PointerRNA media = iter.ptr;
    PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
    if (!RNA_boolean_get(&media, "selected") ||
        (embedded && RNA_property_string_length(&media, embedded) > 0))
    {
      RNA_property_collection_next(&iter);
      continue;
    }
    PointerRNA image_ptr = RNA_pointer_get(&media, "image");
    Image *image = static_cast<Image *>(image_ptr.data);
    if (!image) {
      RNA_property_collection_next(&iter);
      continue;
    }
    /* Rect from the shared per-frame cache; only media that somehow missed the
     * id migration (and so is absent from the cache) falls back to deriving
     * the aspect from a freshly acquired ImBuf. */
    char media_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&media, "node_id", media_id, sizeof(media_id));
    const rctf *cached_rect = (cache && media_id[0]) ? cache->outputs.lookup_ptr(media_id) :
                                                       nullptr;
    rctf media_rect;
    if (cached_rect) {
      media_rect = *cached_rect;
    }
    else {
      float aspect = 1.0f;
      void *lock = nullptr;
      ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
      if (ibuf && ibuf->x > 0) {
        aspect = float(ibuf->y) / float(ibuf->x);
      }
      BKE_image_release_ibuf(image, ibuf, lock);
      const float width = MOODBOARD_IMAGE_BASE_SIZE * RNA_float_get(&media, "scale");
      media_rect.xmin = RNA_float_get(&media, "position_x");
      media_rect.ymin = RNA_float_get(&media, "position_y");
      media_rect.xmax = media_rect.xmin + width;
      media_rect.ymax = media_rect.ymin + width * aspect;
    }
    rcti media_region;
    if (moodboard_view_rect_to_region(v2d, region, media_rect, &media_region)) {
      if (BLI_rcti_size_x(&media_region) < 180 || BLI_rcti_size_y(&media_region) < 120) {
        RNA_property_collection_next(&iter);
        continue;
      }
      const int bar_width = std::clamp(BLI_rcti_size_x(&media_region), 180, 420);
      const int bar_x = std::clamp(BLI_rcti_cent_x(&media_region) - bar_width / 2,
                                   8,
                                   std::max(8, region->winx - bar_width - 8));
      const int bar_y = std::clamp(media_region.ymax + 10, 8, std::max(8, region->winy - 54));
      rctf bar_rect = {float(bar_x), float(bar_x + bar_width), float(bar_y), float(bar_y + 44)};
      moodboard_draw_floating_background(bar_rect);
      uiDefBut(block,
               ButType::Label,
               0,
               image->source == IMA_SRC_MOVIE ? "Video" : "Image",
               bar_x + 12,
               bar_y + 10,
               bar_width - 24,
               24,
               nullptr,
               0,
               0,
               nullptr);
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

}  // namespace blender::ed::mixie
