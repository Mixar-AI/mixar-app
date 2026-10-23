/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Playback gesture for a movie that lives inside an inference node.
 *
 * Split out of #mixie_moodboard_ops_graph.cc (500-line rule). A generated movie
 * carries `embedded_node_id`, which excludes it from the standalone-tile
 * hit-test that serves an uploaded movie -- so its node has to offer the same
 * hover controls itself (Preview, Play/Pause, Sound), plus a double-click
 * anywhere on the tile to toggle playback.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

namespace blender::ed::mixie {

bool moodboard_graph_node_video_click(bContext *C,
                                      PointerRNA *scene_ptr,
                                      View2D *v2d,
                                      const rctf &node_rect,
                                      const char *node_id,
                                      const float mouse_x,
                                      const float mouse_y,
                                      const bool double_click,
                                      ReportList *reports,
                                      wmOperatorStatus *r_status)
{
  const int media_index = moodboard_find_embedded_media_index(scene_ptr, node_id);
  if (media_index < 0 || !moodboard_item_is_video(scene_ptr, media_index)) {
    return false;
  }
  rctf preview_bounds{};
  moodboard_graph_node_preview_bounds(node_rect, &preview_bounds);
  /* Same controls and geometry as an uploaded movie's card, through the
   * shared definition the draw pass uses, so the target follows the glyph. */
  int button = moodboard_video_card_button_at(v2d, preview_bounds, mouse_x, mouse_y);
  if (button == MOODBOARD_VIDEO_CARD_NONE && double_click) {
    button = MOODBOARD_VIDEO_CARD_PLAY;
  }
  if (button == MOODBOARD_VIDEO_CARD_NONE) {
    return false;
  }
  *r_status = moodboard_video_card_press(
      C, scene_ptr, media_index, button, nullptr, node_id, reports);
  return true;
}

}  // namespace blender::ed::mixie
