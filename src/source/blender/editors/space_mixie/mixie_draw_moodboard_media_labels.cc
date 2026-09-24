/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Selected image/movie names share the generation-node title painter.
 *
 * Titles stay attached to the full projected tile in screen space. Canvas
 * zoom changes the picture, never the font. The shared title geometry reserves
 * the action row and fits long names with UTF-8 ellipses; the caller's canvas
 * scissor clips off-screen text without moving it over another picture.
 */

#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

void mixie_draw_moodboard_selected_media_labels(const bContext * /*C*/,
                                                View2D *v2d,
                                                ARegion *region,
                                                PointerRNA *scene_ptr,
                                                const MoodboardGraphCache *cache)
{
  PropertyRNA *images = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!images || !cache) {
    return;
  }
  const Scene *scene = static_cast<const Scene *>(scene_ptr->data);
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, images, &iter);
  while (iter.valid) {
    PointerRNA media = iter.ptr;
    PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
    const bool standalone = !embedded || RNA_property_string_length(&media, embedded) == 0;
    if (standalone && RNA_boolean_get(&media, "selected")) {
      PointerRNA image_ptr = RNA_pointer_get(&media, "image");
      const Image *image = static_cast<const Image *>(image_ptr.data);
      char media_id[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(&media, "node_id", media_id, sizeof(media_id));
      const rctf *rect = cache->outputs.lookup_ptr(media_id);
      if (image && rect && !moodboard_media_rename_is_active(scene, media_id)) {
        rcti projected;
        moodboard_view_rect_to_region(v2d, region, *rect, &projected);
        rctf card;
        BLI_rctf_rcti_copy(&card, &projected);
        moodboard_draw_card_title(
            image->id.name + 2, card, true, moodboard_node_card_actions_width(true));
      }
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

}  // namespace blender::ed::mixie
