/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "mixie_attachment_geometry.hh"
#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_moodboard_attachment.hh"
#include "ED_moodboard_drawer.hh"
#include "ED_space_api.hh"
#include "RNA_access.hh"
#include "UI_view2d.hh"
#include "WM_api.hh"
#include "mixie_draw_moodboard_intern.hh"
#include "mixie_intern.hh"
#include "mixie_moodboard_graph_geometry.hh"

#if defined(__APPLE__) || defined(_WIN32)
extern "C" bool Mixar_WindowCanAnimate(void *window_handle);
#endif

namespace blender::ed::mixie {
float attachment_pixel_scale(const wmWindow *win)
{
  return float(WM_window_native_pixel_x(win)) / std::max(1, int(win->sizex));
}

FlightQuad attachment_desktop_quad(const wmWindow *win, const rctf &r)
{
  const float scale = attachment_pixel_scale(win);
  FlightQuad quad{{{r.xmin, r.ymin}, {r.xmax, r.ymin}, {r.xmax, r.ymax}, {r.xmin, r.ymax}}};
  for (auto &p : quad) {
    p[0] = win->posx + p[0] / scale;
    p[1] = win->posy + p[1] / scale;
  }
  return quad;
}

bool attachment_window_visible(const wmWindow *win)
{
  if (!win || !win->runtime->ghostwin || win->sizex <= 0 || win->sizey <= 0) {
    return false;
  }
  if (const bScreen *screen = WM_window_get_active_screen(win)) {
    for (const ScrArea &area : screen->areabase) {
      if (area.spacetype == SPACE_AGENT_BUBBLE && !ED_agent_bubble_is_attachment_destination(win))
      {
        return false;
      }
    }
  }
#if defined(__APPLE__) || defined(_WIN32)
  return Mixar_WindowCanAnimate(win->runtime->ghostwin);
#else
  return true;
#endif
}

bool attachment_resting_target(wmWindow *win, FlightQuad &quad)
{
  bContext *context = CTX_create();
  CTX_wm_window_set(context, win);
  const bool resting = ED_agent_bubble_is_resting_pill(context);
  CTX_free(context);
  if (!resting) {
    return false;
  }
  const float x = WM_window_native_pixel_x(win) * 0.5f;
  const float y = WM_window_native_pixel_y(win) * 0.5f;
  const float half = 9 * attachment_pixel_scale(win);
  quad = attachment_desktop_quad(win, {x - half, x + half, y - half, y + half});
  return true;
}

static bool image_canvas_rect(
    Scene *scene, Image *image, rctf &rect, float &angle, bool &flip_x, bool &flip_y)
{
  PointerRNA ptr = RNA_id_pointer_create(&scene->id);
  if (!RNA_struct_find_property(&ptr, "mixie_moodboard_images")) {
    return false;
  }
  bool found = false;
  for (int pass = 0; pass < 2 && !found; pass++) {
    RNA_BEGIN (&ptr, item, "mixie_moodboard_images") {
      if ((pass == 1 || RNA_boolean_get(&item, "selected")) &&
          RNA_pointer_get(&item, "image").data == image &&
          RNA_string_get(&item, "embedded_node_id").empty())
      {
        found = moodboard_graph_media_rect(&item, &rect);
        angle = RNA_float_get(&item, "rotation") * (3.14159265f / 180.0f);
        flip_x = RNA_boolean_get(&item, "flip_horizontal");
        flip_y = RNA_boolean_get(&item, "flip_vertical");
        if (found) {
          break;
        }
      }
    }
    RNA_END;
  }
  if (found || !RNA_struct_find_property(&ptr, "mixie_moodboard_action_nodes")) {
    return found;
  }
  RNA_BEGIN (&ptr, node, "mixie_moodboard_action_nodes") {
    if (RNA_pointer_get(&node, "preview_image").data != image) {
      continue;
    }
    const float x = RNA_float_get(&node, "position_x"), y = RNA_float_get(&node, "position_y");
    moodboard_graph_node_preview_bounds(
        {x, x + RNA_float_get(&node, "width"), y, y + RNA_float_get(&node, "height")}, &rect);
    int px = 0;
    int py = 0;
    if (mixie_moodboard_image_size(image, nullptr, &px, &py) && px > 0 && py > 0) {
      const float fit = std::min(BLI_rctf_size_x(&rect) / float(px),
                                 BLI_rctf_size_y(&rect) / float(py));
      const float cx = BLI_rctf_cent_x(&rect), cy = BLI_rctf_cent_y(&rect);
      rect = {cx - float(px) * fit / 2,
              cx + float(px) * fit / 2,
              cy - float(py) * fit / 2,
              cy + float(py) * fit / 2};
      found = true;
    }
    break;
  }
  RNA_END;
  return found;
}

bool attachment_source(const bContext *C, Image *image, wmWindow **r_window, FlightQuad &quad)
{
  Scene *scene = CTX_data_scene(C);
  rctf canvas;
  float angle = 0;
  bool flip_x = false, flip_y = false;
  if (!image_canvas_rect(scene, image, canvas, angle, flip_x, flip_y)) {
    return false;
  }
  /* Prefer the event's window, then other visible hosts of this scene. */
  for (int pass = 0; pass < 2; pass++) {
    for (wmWindow &win : CTX_wm_manager(C)->windows) {
      if ((&win == CTX_wm_window(C)) != (pass == 0) || WM_window_get_active_scene(&win) != scene ||
          !attachment_window_visible(&win))
      {
        continue;
      }
      for (ScrArea &area : WM_window_get_active_screen(&win)->areabase) {
        for (ARegion &region : area.regionbase) {
          const bool drawer = area.spacetype == SPACE_VIEW3D &&
                              region.regiontype == RGN_TYPE_TOOL_PROPS;
          if (!region.runtime->visible ||
              !(drawer ||
                (area.spacetype == SPACE_MIXIE && region.regiontype == RGN_TYPE_WINDOW)) ||
              (drawer && view3d_moodboard_drawer_runtime_amount(&region) <
                             MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT))
          {
            continue;
          }
          rcti visible = region.winrct;
          if (drawer) {
            view3d_moodboard_drawer_panel_rect_for(&area, &region, 1.0f, &visible);
          }
          const float cx = BLI_rctf_cent_x(&canvas), cy = BLI_rctf_cent_y(&canvas);
          FlightQuad points{{{canvas.xmin, canvas.ymin},
                             {canvas.xmax, canvas.ymin},
                             {canvas.xmax, canvas.ymax},
                             {canvas.xmin, canvas.ymax}}};
          rctf bounds{1e20f, -1e20f, 1e20f, -1e20f};
          for (auto &p : points) {
            const float x = (p[0] - cx) * (flip_x ? -1 : 1);
            const float y = (p[1] - cy) * (flip_y ? -1 : 1);
            ui::view2d_view_to_region_fl(&region.v2d,
                                         cx + x * std::cos(angle) - y * std::sin(angle),
                                         cy + x * std::sin(angle) + y * std::cos(angle),
                                         &p[0],
                                         &p[1]);
            p[0] += region.winrct.xmin;
            p[1] += region.winrct.ymin;
            BLI_rctf_do_minmax_v(&bounds, p.data());
          }
          /* A clipped or tiny card cannot launch a faithful full-image copy. */
          if (bounds.xmin < visible.xmin || bounds.xmax > visible.xmax ||
              bounds.ymin < visible.ymin || bounds.ymax > visible.ymax ||
              BLI_rctf_size_x(&bounds) < 4 || BLI_rctf_size_y(&bounds) < 4)
          {
            continue;
          }
          const float scale = attachment_pixel_scale(&win);
          for (auto &p : points) {
            p[0] = win.posx + p[0] / scale;
            p[1] = win.posy + p[1] / scale;
          }
          quad = points;
          *r_window = &win;
          return true;
        }
      }
    }
  }
  return false;
}
}  // namespace blender::ed::mixie
