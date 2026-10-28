/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Opening a generated result in its own Image Preview window.
 *
 * A card on the canvas is a thumbnail: it is sized for the graph, not for
 * judging a result. This opens the node's own image or movie in a separate
 * window, at a size derived from the media itself, without disturbing the
 * board.
 *
 * Built on #WM_window_open, the same primitive Blender's own "Blender Render"
 * window uses (editors/render/render_view.cc): it creates the window, puts an
 * Image Editor in it, and moves the context there -- so the space to fill in is
 * simply `CTX_wm_area(C)` afterwards. A `temp` window is REUSED by upstream
 * when one is already open (any temporary single-Image-Editor window), so
 * there is one preview window at a time and the next preview replaces what it
 * shows: the video player running there is stopped first, so the window never
 * holds two players (or a player under a still).
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

#include "BLT_translation.hh"

#include "BKE_image.hh"

#include "DNA_space_types.h"

#include "ED_image.hh"

#include "UI_interface_c.hh"

#include "mixie_moodboard_video_player.hh"

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
/* A movie is watched, not inspected: a small clip is scaled up to at least
 * this width (UI-scaled), keeping its aspect, within 80% of the parent. */
static const int VIDEO_PREVIEW_MIN_W = 960;
static const float VIDEO_PREVIEW_MAX_SCREEN = 0.8f;

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

/* A movie gets the video player (mixie_moodboard_video_player.cc) running modal
 * in its window: its own clock and sound, and real controls instead of the
 * Image Editor's scene-frame playback. */
static bool start_video_player(bContext *C, Image *image, ReportList *reports)
{
  wmOperatorType *ot = WM_operatortype_find("MIXIE_OT_moodboard_video_player", false);
  if (!ot) {
    return false;
  }
  PointerRNA props = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&props, "image", image->id.name + 2);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::InvokeDefault, &props, nullptr);
  WM_operator_properties_free(&props);
  if (!(status & OPERATOR_RUNNING_MODAL)) {
    BKE_report(reports, RPT_WARNING, "Could not start the video player");
    return false;
  }
  return true;
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
               /* N_: BKE_report translates the message it is given. */
               media_id[0] ? N_("This board item has no image or video to preview") :
                             N_("This node has no image or video to preview"));
    return OPERATOR_CANCELLED;
  }

  /* Size the window to the media, within bounds. Generated size lives on the
   * base tile; a movie that has not decoded a frame yet reports zero, so the
   * floor covers it. */
  int width = 0;
  int height = 0;
  if (ImageTile *tile = BKE_image_get_tile(image, 0)) {
    width = tile->gen_x > 0 ? tile->gen_x : 0;
    height = tile->gen_y > 0 ? tile->gen_y : 0;
  }
  ImageUser probe{};
  BKE_imageuser_default(&probe);
  void *lock = nullptr;
  /* The acquired buffer is REFERENCED, so it has to be handed back to
   * `BKE_image_release_ibuf` -- passing nullptr releases the lock but leaks the
   * reference, once per preview the user opens. Hence the scope, rather than an
   * `if`-scoped declaration. */
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, &probe, &lock);
  if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
    width = ibuf->x;
    height = ibuf->y;
  }
  BKE_image_release_ibuf(image, ibuf, lock);

  const bool is_movie = image->source == IMA_SRC_MOVIE;
  if (is_movie && width > 0 && height > 0) {
    /* The player hides the Image Editor's header and footer, so the window
     * is the movie's own aspect. */
    const float max_w = WM_window_native_pixel_x(parent) * VIDEO_PREVIEW_MAX_SCREEN;
    const float max_h = WM_window_native_pixel_y(parent) * VIDEO_PREVIEW_MAX_SCREEN;
    const float fit = std::min(max_w / width, max_h / height);
    const float grow = std::max(VIDEO_PREVIEW_MIN_W * UI_SCALE_FAC / width, 1.0f);
    const float scale = std::min(grow, fit);
    width = int(width * scale);
    height = int(height * scale);
  }
  else {
    width = std::clamp(width, PREVIEW_MIN_W, PREVIEW_MAX_W);
    height = std::clamp(height, PREVIEW_MIN_H, PREVIEW_MAX_H) +
             (is_movie ? 0 : PREVIEW_CHROME_H);
  }

  WM_window_dpi_set_userdef(parent);
  const rcti window_rect = {0, width, 0, height};

  /* Changes the context to the new window's area. `temp` so it stays a utility
   * window rather than becoming part of the saved workspace layout -- a preview
   * is something the user opens and closes, not a screen they arrange. */
  if (WM_window_open(C,
                     is_movie ? IFACE_("Video Preview") : IFACE_("Image Preview"),
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

  /* A reused window may still be playing the previous preview: end that
   * player (and its sound) before this media replaces it, so the window's
   * controls, QA target and audio always belong to what it shows. */
  video_player_stop_in_window(C, CTX_wm_window(C));
  ED_space_image_set(bmain, sima, image, false);
  if (is_movie) {
    start_video_player(C, image, op->reports);
  }
  ED_area_tag_redraw(area);
  return OPERATOR_FINISHED;
}

wmOperatorStatus moodboard_video_card_press(bContext *C,
                                            PointerRNA *scene_ptr,
                                            const int media_index,
                                            const int button,
                                            const char *media_id,
                                            const char *node_id,
                                            ReportList *reports)
{
  switch (button) {
    case MOODBOARD_VIDEO_CARD_PLAY:
      return moodboard_toggle_video_playback(C, scene_ptr, media_index, reports) ?
                 OPERATOR_FINISHED :
                 OPERATOR_CANCELLED;
    case MOODBOARD_VIDEO_CARD_SOUND:
      return moodboard_toggle_video_mute(C, scene_ptr, media_index, reports) ?
                 OPERATOR_FINISHED :
                 OPERATOR_CANCELLED;
    case MOODBOARD_VIDEO_CARD_PREVIEW:
      break;
    default:
      return OPERATOR_CANCELLED;
  }

  wmOperatorType *ot = WM_operatortype_find("MIXIE_OT_moodboard_preview_media", false);
  if (!ot) {
    return OPERATOR_CANCELLED;
  }
  /* Opening a window moves the context into it; the click that asked for it
   * still has to finish in the canvas it came from. */
  wmWindow *win = CTX_wm_window(C);
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  PointerRNA props = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&props, "media_id", media_id ? media_id : "");
  RNA_string_set(&props, "node_id", node_id ? node_id : "");
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &props, nullptr);
  WM_operator_properties_free(&props);
  CTX_wm_window_set(C, win);
  CTX_wm_area_set(C, area);
  CTX_wm_region_set(C, region);
  return (status & OPERATOR_FINISHED) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

}  // namespace blender::ed::mixie

/* Mixar 5.2 port: operator registrations live in namespace blender. */
namespace blender {
void MIXIE_OT_moodboard_preview_media(wmOperatorType *ot)
{
  ot->name = "Preview Media";
  ot->idname = "MIXIE_OT_moodboard_preview_media";
  ot->description =
      "Open this image or video in the preview window. "
      "An open preview window is reused and shows this instead";

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
}  // namespace blender
