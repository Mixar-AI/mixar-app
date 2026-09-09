/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Playback gesture for a movie that lives inside an inference node.
 *
 * Split out of #mixie_moodboard_ops_graph.cc (500-line rule). A generated movie
 * carries `embedded_node_id`, which excludes it from the standalone-tile
 * hit-test that starts playback for an uploaded movie -- so its node has to
 * offer the same affordances itself: the centred play/pause button, or a
 * double-click anywhere on the tile.
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
  /* Radius through the shared definition the draw pass uses: a fixed PIXEL
   * size converted into canvas units, capped against the tile so the target
   * follows the glyph when zooming shrinks it. */
  const float play_radius = moodboard_video_play_radius(v2d, preview_bounds);
  const float delta_x = mouse_x - BLI_rctf_cent_x(&preview_bounds);
  const float delta_y = mouse_y - BLI_rctf_cent_y(&preview_bounds);
  const bool play_button_hit = delta_x * delta_x + delta_y * delta_y <=
                               play_radius * play_radius;
  if (!double_click && !play_button_hit) {
    return false;
  }
  *r_status = moodboard_toggle_video_playback(C, scene_ptr, media_index, reports) ?
                  OPERATOR_FINISHED :
                  OPERATOR_CANCELLED;
  return true;
}

}  // namespace blender::ed::mixie
