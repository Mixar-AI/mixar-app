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

#include "ED_moodboard_drawer.hh"

#include "UI_view2d.hh"

#include "WM_api.hh"

#include "../interface/interface_qa_inspect.hh"

#include "mixie_intern.hh"
#include "mixie_moodboard_node_layout.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

using blender::ed::mixie::MoodboardGraphCache;

bool canvas_rect_to_window(const ARegion *region, const rctf &canvas, rcti *r_win)
{
  if (!(canvas.xmax > canvas.xmin) || !(canvas.ymax > canvas.ymin)) {
    return false;
  }
  View2D *v2d = &const_cast<ARegion *>(region)->v2d;
  float x0, y0, x1, y1;
  blender::ui::view2d_view_to_region_fl(v2d, canvas.xmin, canvas.ymin, &x0, &y0);
  blender::ui::view2d_view_to_region_fl(v2d, canvas.xmax, canvas.ymax, &x1, &y1);
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
  const bool mixie_canvas = area->spacetype == SPACE_MIXIE &&
                            region->regiontype == RGN_TYPE_WINDOW;
  const bool drawer_canvas = area->spacetype == SPACE_VIEW3D &&
                             region->regiontype == RGN_TYPE_TOOL_PROPS;
  if (!mixie_canvas && !drawer_canvas) {
    return;
  }
  const size_t first_target = r_targets.size();
  /* The drawer draw pass shifts `v2d.cur` then restores it. Export canvas
   * targets only once that offset is gone, or the harness would click
   * translated cards that the live hit-test does not see. `regiondata` is
   * `MoodboardDrawerRuntime`; amount is the first member. */
  if (drawer_canvas) {
    if (region->regiondata == nullptr) {
      return;
    }
    const float amount = *static_cast<const float *>(region->regiondata);
    if (amount < MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT) {
      return;
    }
  }
  Scene *scene = WM_window_get_active_scene(win);
  if (scene == nullptr) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  MoodboardGraphCache cache;
  blender::ed::mixie::moodboard_graph_cache_build(&scene_ptr, &cache);

  blender::Set<std::string> asset_ids;
  if (PropertyRNA *assets = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_asset_nodes")) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(&scene_ptr, assets, &iter);
    while (iter.valid) {
      char id[MIXIE_GRAPH_ID_BUF];
      ed::mixie::mixie_rna_string_get_clamped(&iter.ptr, "node_id", id, sizeof(id));
      asset_ids.add(id);
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  blender::Set<std::string> media_title_ids;
  if (PropertyRNA *images = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images")) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(&scene_ptr, images, &iter);
    while (iter.valid) {
      PointerRNA media = iter.ptr;
      char id[MIXIE_GRAPH_ID_BUF];
      ed::mixie::mixie_rna_string_get_clamped(&media, "node_id", id, sizeof(id));
      PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
      if (id[0] && RNA_boolean_get(&media, "selected") &&
          RNA_pointer_get(&media, "image").data &&
          (!embedded || RNA_property_string_length(&media, embedded) == 0) &&
          !ed::mixie::moodboard_media_rename_is_active(scene, id))
      {
        media_title_ids.add(id);
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

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
    if (is_action || asset_ids.contains(node_id) || media_title_ids.contains(node_id)) {
      rcti card_pixels;
      if (canvas_rect_to_window(region, canvas_rect, &card_pixels)) {
        rctf card;
        BLI_rctf_rcti_copy(&card, &card_pixels);
        const bool media_title = media_title_ids.contains(node_id);
        const rctf title = ed::mixie::moodboard_node_title_rect(
            card, media_title ? ed::mixie::moodboard_node_card_actions_width(true) : 0.0f);
        MixarQATarget heading;
        BLI_rcti_rctf_copy(&heading.rect_win, &title);
        rcti visible = ed::mixie::moodboard_canvas_host_rect(
            area, const_cast<ARegion *>(region));
        BLI_rcti_translate(&visible, region->winrct.xmin, region->winrct.ymin);
        if (title.xmax > title.xmin &&
            BLI_rcti_isect(&heading.rect_win, &visible, &heading.rect_win))
        {
          heading.surface = media_title ? "moodboard_media_title" : "moodboard_node_title";
          heading.text = node_id;
          heading.enabled = false; /* Painted label, for visual capture only. */
          r_targets.push_back(std::move(heading));
        }
      }
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

    /* The four corner RESIZE handles, from the shared geometry unit the draw
     * pass and the hit-test read -- so a harness drag starts exactly where a
     * user's would. Exported for every node and every media tile in the cache:
     * they are only PAINTED while selected, but a scenario clicks to select and
     * then drags, and re-resolving targets between those two steps would be a
     * round trip for nothing.
     *
     * `detail` names the corner, because that is the whole difference between
     * the four: which one is anchored. */
    {
      static const char *corner_names[MOODBOARD_RESIZE_HANDLE_COUNT] = {
          "bottom_left", "bottom_right", "top_right", "top_left"};
      float handles[MOODBOARD_RESIZE_HANDLE_COUNT][2];
      blender::ed::mixie::moodboard_resize_handle_positions(canvas_rect, handles);
      View2D *hv2d = &const_cast<ARegion *>(region)->v2d;
      const int radius = int(MOODBOARD_RESIZE_HANDLE_PX);
      for (int i = 0; i < MOODBOARD_RESIZE_HANDLE_COUNT; i++) {
        float hx, hy;
        ui::view2d_view_to_region_fl(hv2d, handles[i][0], handles[i][1], &hx, &hy);
        MixarQATarget h;
        h.surface = "moodboard_resize_handle";
        h.text = node_id;
        h.detail = corner_names[i];
        h.rect_win.xmin = region->winrct.xmin + int(hx) - radius;
        h.rect_win.xmax = region->winrct.xmin + int(hx) + radius;
        h.rect_win.ymin = region->winrct.ymin + int(hy) - radius;
        h.rect_win.ymax = region->winrct.ymin + int(hy) + radius;
        r_targets.push_back(std::move(h));
      }
    }

    /* Output "+" handle: same formula as moodboard_find_output_socket_under_mouse
     * (rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET, centre-y). */
    {
      View2D *hv2d = &const_cast<ARegion *>(region)->v2d;
      float hx, hy;
      blender::ui::view2d_view_to_region_fl(hv2d,
                                  canvas_rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET,
                                  BLI_rctf_cent_y(&canvas_rect),
                                  &hx,
                                  &hy);
      const int radius = int(blender::ed::mixie::moodboard_socket_hit_radius_px(hv2d, true));
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

  /* Canvas frames. Each exports its BODY plus the one part a click means
   * something different on -- the thick top strip (select + drag + rename on a
   * double-click) -- and both rects come from the frame geometry unit the draw
   * pass and the hit-test share, so a QA click lands exactly where a user's
   * would. There is no resize target: a frame has no manual resize, its rect
   * follows what it holds. */
  {
    PropertyRNA *frames = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_frames");
    const int frame_count = frames ? RNA_property_collection_length(&scene_ptr, frames) : 0;
    for (int i = 0; i < frame_count; i++) {
      PointerRNA frame;
      if (!RNA_property_collection_lookup_int(&scene_ptr, frames, i, &frame)) {
        continue;
      }
      char frame_id[MIXIE_GRAPH_ID_BUF] = "";
      blender::ed::mixie::mixie_rna_string_get_clamped(
          &frame, "frame_id", frame_id, sizeof(frame_id));
      char frame_name[MIXIE_FRAME_NAME_BUF] = "";
      blender::ed::mixie::mixie_rna_string_get_clamped(
          &frame, "name", frame_name, sizeof(frame_name));

      rctf rect;
      blender::ed::mixie::moodboard_frame_rect(&frame, &rect);

      MixarQATarget body;
      if (canvas_rect_to_window(region, rect, &body.rect_win)) {
        body.surface = "moodboard_frame";
        /* The NAME, not the id: a scenario reads like the board does
         * ("the Interior refs frame"), and the id is an opaque uuid. */
        body.text = frame_name;
        body.detail = frame_id;
        body.index = i;
        r_targets.push_back(std::move(body));
      }

      rctf strip;
      blender::ed::mixie::moodboard_frame_top_strip(rect, &strip);
      MixarQATarget title;
      if (canvas_rect_to_window(region, strip, &title.rect_win)) {
        title.surface = "moodboard_frame_title";
        title.text = frame_name;
        title.detail = frame_id;
        title.index = i;
        r_targets.push_back(std::move(title));
      }
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
      blender::ui::view2d_view_to_region_fl(v2d, cx, cy, &rx, &ry);
      const int radius = int(blender::ed::mixie::moodboard_socket_hit_radius_px(v2d));

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

  rcti content = ed::mixie::moodboard_canvas_host_rect(area, const_cast<ARegion *>(region));
  BLI_rcti_translate(&content, region->winrct.xmin, region->winrct.ymin);
  /* Exclude the sidebar from interaction targets, but retain the canvas
   * beneath floating chrome. Native blocks own the controls above it. */
  r_targets.erase(
      std::remove_if(r_targets.begin() + first_target, r_targets.end(),
                     [&content](MixarQATarget &target) {
                       return !BLI_rcti_isect(&target.rect_win, &content, &target.rect_win) ||
                              BLI_rcti_size_x(&target.rect_win) <= 0 ||
                              BLI_rcti_size_y(&target.rect_win) <= 0;
                     }),
      r_targets.end());
  if (BLI_rcti_size_x(&content) > 0 && BLI_rcti_size_y(&content) > 0) {
    MixarQATarget canvas;
    canvas.surface = "moodboard_canvas";
    canvas.rect_win = content;
    r_targets.push_back(std::move(canvas));
  }
}

}  // namespace

void mixie_moodboard_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_MIXIE, moodboard_qa_targets);
  Mixar_qa_register_target_provider(SPACE_VIEW3D, moodboard_qa_targets);
}

}  // namespace blender
