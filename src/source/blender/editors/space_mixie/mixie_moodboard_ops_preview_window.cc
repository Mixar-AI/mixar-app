/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Opening a generated result in its own Image Preview window.
 *
 * A card on the canvas is a thumbnail: it is sized for the graph, not for
 * judging a result. This opens the node's own image or movie in a separate
 * window, at a size derived from the media itself, so several results can be
 * compared side by side without disturbing the board.
 *
 * Built on #WM_window_open, the same primitive Blender's own "Blender Render"
 * window uses (editors/render/render_view.cc): it creates the window, puts an
 * Image Editor in it, and moves the context there -- so the space to fill in is
 * simply `CTX_wm_area(C)` afterwards. Each call opens a NEW window, which is
 * what makes several previews at once work; nothing here reuses or reclaims an
 * existing one.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

#include "BKE_image.hh"

#include "MOV_read.hh"

#include "DNA_space_types.h"

#include "ED_image.hh"

#include "UI_interface_c.hh"

namespace blender::ed::mixie {

/* A preview is for looking at the result, so it opens near the size of the
 * media -- but a 64px thumbnail deserves a usable window, and an 8K render must
 * not open larger than the display. Matches the floor render_view.cc uses. */
static const int PREVIEW_MIN_W = 480;
static const int PREVIEW_MIN_H = 360;
static const int PREVIEW_MAX_W = 1600;
static const int PREVIEW_MAX_H = 1200;
/* Room for the Image Editor's own header and footer, so the media itself gets
 * the space the numbers above describe. */
static const int PREVIEW_CHROME_H = 60;

static Image *preview_image_for_node(PointerRNA *scene_ptr, const char *node_id)
{
  const int index = moodboard_find_embedded_media_index(scene_ptr, node_id);
  if (index < 0) {
    return nullptr;
  }
  return moodboard_item_image(scene_ptr, index);
}

/* A reference on the board is addressed by ITS OWN graph id (`node_id` on the
 * media entry), where a node's result is addressed through the node that owns
 * it (`embedded_node_id`). Two properties on the operator, because the two
 * lookups walk different fields and a single id resolved against both would
 * silently prefer whichever matched first. */
static Image *preview_image_for_media(PointerRNA *scene_ptr, const char *media_id)
{
  if (!media_id || media_id[0] == '\0') {
    return nullptr;
  }
  PropertyRNA *items = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  const int count = items ? RNA_property_collection_length(scene_ptr, items) : 0;
  for (int index = 0; index < count; index++) {
    PointerRNA item;
    RNA_property_collection_lookup_int(scene_ptr, items, index, &item);
    char item_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&item, "node_id", item_id, sizeof(item_id));
    if (STREQ(item_id, media_id)) {
      return moodboard_item_image(scene_ptr, index);
    }
  }
  return nullptr;
}

/* A movie opens on its first frame and stays there unless the image user knows
 * how long it is: with the range set and auto-refresh on, the space follows the
 * scene frame, so Blender's own playback drives it. */
static void configure_movie_user(SpaceImage *sima, Image *image)
{
  if (!image || image->source != IMA_SRC_MOVIE) {
    return;
  }
  ImageUser *iuser = &sima->iuser;
  ImageAnim *anim = static_cast<ImageAnim *>(image->anims.first);
  const int frames = (anim && anim->anim) ? MOV_get_duration_frames(anim->anim, IMB_TC_RECORD_RUN) :
                                            0;
  iuser->frames = std::max(frames, 1);
  iuser->sfra = 1;
  iuser->offset = 0;
  iuser->flag |= IMA_ANIM_ALWAYS;
}

static wmOperatorStatus moodboard_preview_media_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  wmWindow *parent = CTX_wm_window(C);
  if (!bmain || !scene || !parent) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  char node_id[MIXIE_GRAPH_ID_BUF];
  RNA_string_get(op->ptr, "node_id", node_id);
  char media_id[MIXIE_GRAPH_ID_BUF];
  RNA_string_get(op->ptr, "media_id", media_id);
  /* A reference's own row passes `media_id`; a card's row passes `node_id`. */
  Image *image = media_id[0] ? preview_image_for_media(&scene_ptr, media_id) :
                               preview_image_for_node(&scene_ptr, node_id);
  if (!image) {
    BKE_report(op->reports,
               RPT_WARNING,
               media_id[0] ? "This board item has no image or video to preview" :
                             "This node has no image or video to preview");
    return OPERATOR_CANCELLED;
  }

  /* Size the window to the media, within bounds. `size` is the pixel size of
   * the loaded buffer; a movie that has not decoded a frame yet reports zero,
   * so the floor covers it. */
  int width = image->gen_x > 0 ? image->gen_x : 0;
  int height = image->gen_y > 0 ? image->gen_y : 0;
  ImageUser probe{};
  BKE_imageuser_default(&probe);
  void *lock = nullptr;
  if (ImBuf *ibuf = BKE_image_acquire_ibuf(image, &probe, &lock)) {
    if (ibuf->x > 0 && ibuf->y > 0) {
      width = ibuf->x;
      height = ibuf->y;
    }
  }
  BKE_image_release_ibuf(image, nullptr, lock);

  width = std::clamp(width, PREVIEW_MIN_W, PREVIEW_MAX_W);
  height = std::clamp(height, PREVIEW_MIN_H, PREVIEW_MAX_H) + PREVIEW_CHROME_H;

  WM_window_dpi_set_userdef(parent);
  const rcti window_rect = {0, width, 0, height};

  /* Changes the context to the new window's area. `temp` so it stays a utility
   * window rather than becoming part of the saved workspace layout -- a preview
   * is something the user opens and closes, not a screen they arrange. */
  if (WM_window_open(C,
                     "Image Preview",
                     &window_rect,
                     SPACE_IMAGE,
                     false,
                     false,
                     true,
                     WIN_ALIGN_PARENT_CENTER,
                     nullptr,
                     nullptr) == nullptr)
  {
    BKE_report(op->reports, RPT_ERROR, "Could not open a preview window");
    return OPERATOR_CANCELLED;
  }

  ScrArea *area = CTX_wm_area(C);
  SpaceImage *sima = area ? static_cast<SpaceImage *>(area->spacedata.first) : nullptr;
  if (!sima) {
    /* The window exists but is not the Image Editor we asked for. Leaving it
     * open and empty would be worse than saying so. */
    BKE_report(op->reports, RPT_ERROR, "Preview window did not open an image editor");
    return OPERATOR_CANCELLED;
  }

  ED_space_image_set(bmain, sima, image, false);
  configure_movie_user(sima, image);
  ED_area_tag_redraw(area);
  return OPERATOR_FINISHED;
}

}  // namespace blender::ed::mixie

void MIXIE_OT_moodboard_preview_media(wmOperatorType *ot)
{
  ot->name = "Preview Media";
  ot->idname = "MIXIE_OT_moodboard_preview_media";
  ot->description =
      "Open this image or video in its own preview window. "
      "Several can be open at once";

  ot->exec = blender::ed::mixie::moodboard_preview_media_exec;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = OPTYPE_REGISTER;

  /* PROP_SKIP_SAVE: a REGISTER operator refills unset properties from the last
   * run, so a remembered id would preview a different card than the one whose
   * button was pressed. */
  PropertyRNA *prop = RNA_def_string(
      ot->srna, "node_id", nullptr, MIXIE_GRAPH_ID_BUF, "Node ID", "Node whose result to open");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
  /* Same SKIP_SAVE reasoning: a remembered media id would open a different
   * reference than the one whose button was pressed. Takes precedence over
   * `node_id` when both are set, since only a reference's own row sets it. */
  prop = RNA_def_string(ot->srna,
                        "media_id",
                        nullptr,
                        MIXIE_GRAPH_ID_BUF,
                        "Media ID",
                        "Board image or video (by its own graph id) to open");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
