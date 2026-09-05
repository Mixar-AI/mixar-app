/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 *
 * QA harness target provider for the moodboard canvas: node/media rects come
 * from the SAME moodboard_graph_cache_build pass that link drawing and
 * hit-testing share, preview bounds from moodboard_graph_node_preview_bounds,
 * and input sockets from moodboard_graph_action_socket_position — the single
 * sources of truth, so QA targets cannot drift from real click geometry.
 * Read-only.
 */

#include <algorithm>
#include <string>

#include "BLI_rect.h"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "UI_view2d.hh"

#include "WM_api.hh"

#include "../interface/interface_qa_inspect.hh"

#include "mixie_intern.hh"

namespace {

using blender::ed::mixie::MoodboardGraphCache;

bool canvas_rect_to_window(const ARegion *region, const rctf &canvas, rcti *r_win)
{
  if (!(canvas.xmax > canvas.xmin) || !(canvas.ymax > canvas.ymin)) {
    return false;
  }
  View2D *v2d = &const_cast<ARegion *>(region)->v2d;
  float x0, y0, x1, y1;
  UI_view2d_view_to_region_fl(v2d, canvas.xmin, canvas.ymin, &x0, &y0);
  UI_view2d_view_to_region_fl(v2d, canvas.xmax, canvas.ymax, &x1, &y1);
  r_win->xmin = region->winrct.xmin + int(std::min(x0, x1));
  r_win->xmax = region->winrct.xmin + int(std::max(x0, x1));
  r_win->ymin = region->winrct.ymin + int(std::min(y0, y1));
  r_win->ymax = region->winrct.ymin + int(std::max(y0, y1));
  return true;
}

void moodboard_qa_targets(const wmWindow *win,
                          const ScrArea *area,
                          const ARegion *region,
                          std::vector<MixarQATarget> &r_targets)
{
  if (area->spacetype != SPACE_MIXIE || region->regiontype != RGN_TYPE_WINDOW) {
    return;
  }
  Scene *scene = WM_window_get_active_scene(win);
  if (scene == nullptr) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  MoodboardGraphCache cache;
  blender::ed::mixie::moodboard_graph_cache_build(&scene_ptr, &cache);

  for (const auto &item : cache.outputs.items()) {
    const std::string &node_id = item.key;
    const rctf &canvas_rect = item.value;
    const bool is_action = cache.action_nodes.contains(node_id);

    MixarQATarget t;
    if (canvas_rect_to_window(region, canvas_rect, &t.rect_win)) {
      t.surface = is_action ? "moodboard_node" : "moodboard_media";
      t.text = node_id;
      r_targets.push_back(std::move(t));
    }
    if (is_action) {
      rctf preview;
      blender::ed::mixie::moodboard_graph_node_preview_bounds(canvas_rect, &preview);
      MixarQATarget p;
      if (canvas_rect_to_window(region, preview, &p.rect_win)) {
        p.surface = "moodboard_preview";
        p.text = node_id;
        r_targets.push_back(std::move(p));
      }
    }

    /* Output "+" handle: same formula as moodboard_find_output_socket_under_mouse
     * (rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET, centre-y). */
    {
      View2D *hv2d = &const_cast<ARegion *>(region)->v2d;
      float hx, hy;
      UI_view2d_view_to_region_fl(hv2d,
                                  canvas_rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET,
                                  BLI_rctf_cent_y(&canvas_rect),
                                  &hx,
                                  &hy);
      const int radius = int(MOODBOARD_GRAPH_SOCKET_RADIUS + 5.0f);
      MixarQATarget h;
      h.surface = "moodboard_output";
      h.text = node_id;
      h.detail = "output";
      h.rect_win.xmin = region->winrct.xmin + int(hx) - radius;
      h.rect_win.xmax = region->winrct.xmin + int(hx) + radius;
      h.rect_win.ymin = region->winrct.ymin + int(hy) - radius;
      h.rect_win.ymax = region->winrct.ymin + int(hy) + radius;
      r_targets.push_back(std::move(h));
    }
  }

  /* Input sockets: same loop shape as moodboard_find_input_socket_under_mouse. */
  View2D *v2d = &const_cast<ARegion *>(region)->v2d;
  for (const auto &pair : cache.action_nodes.items()) {
    PointerRNA node = pair.value;
    PropertyRNA *sockets = RNA_struct_find_property(&node, "input_sockets");
    const int socket_count = sockets ? RNA_property_collection_length(&node, sockets) : 0;
    for (int i = 0; i < socket_count; i++) {
      float cx, cy;
      if (!blender::ed::mixie::moodboard_graph_action_socket_position(&node, i, &cx, &cy)) {
        continue;
      }
      float rx, ry;
      UI_view2d_view_to_region_fl(v2d, cx, cy, &rx, &ry);
      const int radius = int(MOODBOARD_GRAPH_SOCKET_RADIUS + 5.0f);

      PointerRNA socket;
      RNA_property_collection_lookup_int(&node, sockets, i, &socket);
      char socket_id[MIXIE_GRAPH_ID_BUF] = "";
      blender::ed::mixie::mixie_rna_string_get_clamped(
          &socket, "socket_id", socket_id, sizeof(socket_id));

      MixarQATarget t;
      t.surface = "moodboard_socket";
      t.text = pair.key;
      t.detail = socket_id;
      t.index = i;
      t.rect_win.xmin = region->winrct.xmin + int(rx) - radius;
      t.rect_win.xmax = region->winrct.xmin + int(rx) + radius;
      t.rect_win.ymin = region->winrct.ymin + int(ry) - radius;
      t.rect_win.ymax = region->winrct.ymin + int(ry) + radius;
      r_targets.push_back(std::move(t));
    }
  }
}

}  // namespace

void mixie_moodboard_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_MIXIE, moodboard_qa_targets);
}
