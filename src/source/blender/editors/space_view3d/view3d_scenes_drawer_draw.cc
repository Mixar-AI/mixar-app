/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Painting for the Zen Mode sliding Scenes drawer: the panel chrome (rounded
 * on its right edge, the face it slides in from), the labeled tab on that
 * edge, a "Scenes" header with "+ New scene", and one glass card per scene
 * tab read from the Python-owned `wm.mixar_scene_tabs` collection.
 *
 * Geometry comes from `ED_scenes_drawer.hh`; every rect painted here is also
 * cached on the region runtime in WINDOW pixels, so the click operator and
 * the QA provider answer from the pixels the user sees.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_agent_panel.hh"
#include "ED_mixar_glass.hh"
#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_viewport.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "UI_mixar_theme.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_scenes_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Layout, unscaled UI units. */
constexpr float HEADER_H = 40.0f;
constexpr float SIDE_PAD = 12.0f;
constexpr float CARD_H = 60.0f;
constexpr float CARD_GAP = 8.0f;
constexpr float CARD_RADIUS = 10.0f;
constexpr float NEW_W = 96.0f;
constexpr float NEW_H = 24.0f;
constexpr float CLOSE_SIZE = 22.0f;
constexpr float PILL_H = 16.0f;
constexpr float THUMB_W = 78.0f;
constexpr float THUMB_H = 44.0f;

}  // namespace

using namespace view3d_scenes_drawer;

void view3d_scenes_drawer_region_draw(const bContext *C, ARegion *region)
{
  if (!view3d_scenes_drawer_zen_active(C)) {
    return;
  }

  const float amount = view3d_scenes_drawer_display_amount(C);
  ScenesDrawerRuntime *runtime = static_cast<ScenesDrawerRuntime *>(region->regiondata);
  if (runtime) {
    runtime->amount = amount;
    runtime->new_visible = false;
  }

  if (region->overlap) {
    GPU_clear_color(0.0f, 0.0f, 0.0f, 0.0f);
  }
  else {
    ui::theme::frame_buffer_clear(TH_BACK);
  }

  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);

  const int winx = region->winx;
  const int winy = region->winy;
  if (winx <= 0 || winy <= 0) {
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  const float scale = UI_SCALE_FAC;
  const ui::mixar_tokens::Palette &zen = ui::mixar_tokens::mixar_zen();

  /* Grip placed from the same expression the hit test and QA use. */
  float grip_left = 0.0f;
  float grip_centre_y = 0.5f * float(winy);
  const ScrArea *area = CTX_wm_area(C);
  rcti grip_win;
  if (area && view3d_scenes_drawer_grip_rect_for(area, region, amount, &grip_win)) {
    grip_left = float(grip_win.xmin - region->winrct.xmin);
    grip_centre_y = 0.5f * float((grip_win.ymin - region->winrct.ymin) +
                                 (grip_win.ymax - region->winrct.ymin));
  }

  rcti panel_win;
  const bool panel_visible = view3d_scenes_drawer_panel_rect_for(area, region, amount, &panel_win);

  if (panel_visible && runtime) {
    int scissor_prev[4];
    GPU_scissor_get(scissor_prev);
    const int panel_xmax = panel_win.xmax - region->winrct.xmin;
    GPU_scissor(0, 0, panel_xmax, winy);

    rctf panel;
    panel.xmin = 0.0f;
    panel.xmax = float(panel_xmax);
    panel.ymin = 0.0f;
    panel.ymax = float(winy);

    /* Rounded RIGHT edge, square left edge: the drawer meets the area's edge. */
    const float radius = std::min(VIEW3D_SCENES_DRAWER_RADIUS * scale, 0.5f * (panel.xmax - panel.xmin));
    ui::draw_roundbox_corner_set(ui::CNR_TOP_RIGHT | ui::CNR_BOTTOM_RIGHT);
    ui::draw_roundbox_4fv_ex(&panel, zen.canvas, zen.canvas, 0.0f, zen.border, U.pixelsize, radius);

    /* The body slides with the panel: lay everything out from the panel's
     * moving right edge so an opening drawer reveals cards already in place. */
    const float open_w = float(winx) - (VIEW3D_SCENES_DRAWER_PAD + VIEW3D_SCENES_DRAWER_GRIP_WIDTH) * scale;
    const float off = float(panel_xmax) - open_w;   /* <= 0 while sliding in */
    const float x0 = off + SIDE_PAD * scale;
    const float x1 = off + open_w - SIDE_PAD * scale;
    const int font = BLF_default();

    /* Header: "Scenes" + "+ New scene". */
    const float header_top = float(winy);
    const float header_mid = header_top - 0.5f * HEADER_H * scale;
    BLF_size(font, 14.0f * scale);
    BLF_color4fv(font, zen.strong);
    BLF_position(font, x0, header_mid - 0.35f * BLF_height_max(font), 0.0f);
    BLF_draw(font, "Scenes", 6);

    rctf new_rect;
    new_rect.xmax = x1;
    new_rect.xmin = x1 - NEW_W * scale;
    new_rect.ymin = header_mid - 0.5f * NEW_H * scale;
    new_rect.ymax = header_mid + 0.5f * NEW_H * scale;
    {
      float fill[4];
      with_alpha(zen.primary, runtime->hover_new ? 1.0f : 0.85f, fill);
      draw_pill(new_rect, fill, 0.5f * NEW_H * scale);
      BLF_size(font, 11.0f * scale);
      const char *label = "+ New scene";
      const float tw = BLF_width(font, label, strlen(label));
      BLF_color4fv(font, zen.strong);
      BLF_position(font, 0.5f * (new_rect.xmin + new_rect.xmax) - 0.5f * tw,
                   header_mid - 0.35f * BLF_height_max(font), 0.0f);
      BLF_draw(font, label, strlen(label));
    }
    runtime->new_rect.xmin = int(new_rect.xmin) + region->winrct.xmin;
    runtime->new_rect.xmax = int(new_rect.xmax) + region->winrct.xmin;
    runtime->new_rect.ymin = int(new_rect.ymin) + region->winrct.ymin;
    runtime->new_rect.ymax = int(new_rect.ymax) + region->winrct.ymin;
    runtime->new_visible = true;

    /* Cards, top to bottom. Anything past the bottom is clipped (no scroll). */
    sync_cards(C, runtime);
    for (auto it = runtime->thumbs.begin(); it != runtime->thumbs.end();) {
      const std::string &name = it->first;
      const bool listed = std::any_of(runtime->cards.begin(), runtime->cards.end(),
                                      [&](const ScenesDrawerCard &c) { return c.scene_name == name; });
      if (listed) {
        ++it;
      }
      else {
        view3d_scenes_drawer_thumb_free(it->second);
        it = runtime->thumbs.erase(it);
      }
    }
    float y_top = header_top - HEADER_H * scale - CARD_GAP * scale;
    const int count = int(runtime->cards.size());
    for (int i = 0; i < count; i++) {
      ScenesDrawerCard &card = runtime->cards[i];
      const float y_bottom = y_top - CARD_H * scale;
      if (y_top < -CARD_H * scale) {
        break;
      }
      rctf rect;
      rect.xmin = x0;
      rect.xmax = x1;
      rect.ymin = y_bottom;
      rect.ymax = y_top;

      /* Glass pane, with the progress light while workers build. */
      rcti pane;
      BLI_rcti_rctf_copy(&pane, &rect);
      ui::MixarGlassStyle style;
      style.role = ui::MIXAR_GLASS_PANEL;
      style.radius = CARD_RADIUS * scale;
      style.alpha = runtime->hover == i ? 1.0f : 0.92f;
      style.progress = card.workers_total > 0 ?
                           float(card.workers_done) / float(card.workers_total) :
                           0.0f;
      style.progress_tint[0] = 0.015f;
      style.progress_tint[1] = 0.74f;
      style.progress_tint[2] = 0.19f;
      style.progress_tint[3] = card.status == ScenesDrawerTabStatus::Working ? 0.28f : 0.0f;
      ui::mixar_glass_draw(pane, style);
      if (card.is_active) {
        ui::draw_roundbox_corner_set(ui::CNR_ALL);
        ui::draw_roundbox_4fv(&rect, false, CARD_RADIUS * scale, zen.selected);
      }

      /* Thumbnail: the scene rendered natively into a small offscreen, blitted
       * here; a scene that has never been evaluated shows a dark bed. */
      rcti thumb;
      thumb.xmin = int(rect.xmin + 8.0f * scale);
      thumb.xmax = thumb.xmin + int(THUMB_W * scale);
      thumb.ymax = int(rect.ymax - 8.0f * scale);
      thumb.ymin = thumb.ymax - int(THUMB_H * scale);
      {
        rctf bed;
        BLI_rctf_rcti_copy(&bed, &thumb);
        draw_pill(bed, zen.panel, 6.0f * scale);
        auto found = runtime->thumbs.find(card.scene_name);
        if (found != runtime->thumbs.end() && found->second.has_render) {
          GPU_viewport_draw_to_screen_ex(found->second.viewport, 0, &thumb, true, true);
          ED_region_pixelspace(region);
          GPU_blend(GPU_BLEND_ALPHA);
        }
      }
      card.thumb_rect.xmin = thumb.xmin + region->winrct.xmin;
      card.thumb_rect.xmax = thumb.xmax + region->winrct.xmin;
      card.thumb_rect.ymin = thumb.ymin + region->winrct.ymin;
      card.thumb_rect.ymax = thumb.ymax + region->winrct.ymin;

      const float inner_x = float(thumb.xmax) + 10.0f * scale;
      const float close_w = (count > 1) ? CLOSE_SIZE * scale : 0.0f;
      rctf close_rect;
      close_rect.xmax = rect.xmax - 8.0f * scale;
      close_rect.xmin = close_rect.xmax - close_w;
      close_rect.ymax = rect.ymax - 8.0f * scale;
      close_rect.ymin = close_rect.ymax - close_w;

      /* Status pill, left of the close glyph. */
      BLF_size(font, 10.0f * scale);
      const char *status = status_label(card.status);
      const float status_w = BLF_width(font, status, strlen(status)) + 14.0f * scale;
      rctf pill;
      pill.xmax = close_rect.xmin - (count > 1 ? 6.0f * scale : 0.0f);
      pill.xmin = pill.xmax - status_w;
      pill.ymax = rect.ymax - 11.0f * scale;
      pill.ymin = pill.ymax - PILL_H * scale;
      {
        float fill[4];
        with_alpha(status_color(card.status), 0.22f, fill);
        draw_pill(pill, fill, 0.5f * PILL_H * scale);
        BLF_color4fv(font, status_color(card.status));
        BLF_position(font, pill.xmin + 7.0f * scale, pill.ymin + 4.0f * scale, 0.0f);
        BLF_draw(font, status, strlen(status));
      }

      /* Name, with an attention dot for a tab that needs the user. */
      float name_x = inner_x;
      if (card.attention) {
        rctf dot;
        dot.xmin = inner_x;
        dot.xmax = inner_x + 7.0f * scale;
        dot.ymax = rect.ymax - 14.0f * scale;
        dot.ymin = dot.ymax - 7.0f * scale;
        draw_pill(dot, zen.warning, 3.5f * scale);
        name_x += 12.0f * scale;
      }
      BLF_size(font, 12.0f * scale);
      draw_elided(font, card.scene_name, name_x, rect.ymax - 24.0f * scale,
                  pill.xmin - 8.0f * scale - name_x, zen.strong);

      /* The agent's last line. */
      BLF_size(font, 11.0f * scale);
      draw_elided(font, card.last_text, inner_x, rect.ymin + 10.0f * scale,
                  rect.xmax - 12.0f * scale - inner_x, zen.secondary);

      /* Close glyph (never on the last remaining tab). */
      rcti close_i = {};
      if (count > 1) {
        BLI_rcti_rctf_copy(&close_i, &close_rect);
        ED_agent_panel_draw_close(close_i, 1.0f, runtime->hover == i && runtime->hover_close);
      }

      /* Cache in window pixels for hit tests and QA. */
      card.rect.xmin = int(rect.xmin) + region->winrct.xmin;
      card.rect.xmax = int(rect.xmax) + region->winrct.xmin;
      card.rect.ymin = int(rect.ymin) + region->winrct.ymin;
      card.rect.ymax = int(rect.ymax) + region->winrct.ymin;
      if (count > 1) {
        card.close_rect.xmin = close_i.xmin + region->winrct.xmin;
        card.close_rect.xmax = close_i.xmax + region->winrct.xmin;
        card.close_rect.ymin = close_i.ymin + region->winrct.ymin;
        card.close_rect.ymax = close_i.ymax + region->winrct.ymin;
      }
      else {
        card.close_rect = {};
      }
      y_top = y_bottom - CARD_GAP * scale;
    }

    /* Reorder drag: an insertion line above the slot the card would land in. */
    if (runtime->drag_index >= 0 && runtime->drag_target >= 0 &&
        runtime->drag_target < int(runtime->cards.size()) && runtime->drag_target != runtime->drag_index)
    {
      const ScenesDrawerCard &slot = runtime->cards[runtime->drag_target];
      const float line_y = float(slot.rect.ymax - region->winrct.ymin) + 0.5f * CARD_GAP * scale +
                           (runtime->drag_target > runtime->drag_index ? -(CARD_H + CARD_GAP) * scale : 0.0f);
      rctf line;
      line.xmin = x0;
      line.xmax = x1;
      line.ymin = line_y - 1.5f * scale;
      line.ymax = line_y + 1.5f * scale;
      draw_pill(line, zen.primary, 1.5f * scale);
    }

    /* Keep the gutter right of the panel transparent, then the tab on top. */
    GPU_scissor(panel_xmax, 0, winx - panel_xmax, winy);
    clear_tab_gutter(panel_xmax, winx - panel_xmax, winy);
    GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
    ED_region_pixelspace(region);
    draw_grip(grip_left, grip_centre_y);
  }
  else {
    if (runtime) {
      runtime->cards.clear();
    }
    draw_grip(grip_left, grip_centre_y);
  }

  GPU_blend(GPU_BLEND_NONE);

  /* Thumbnails render LAST, after every pixel of chrome: an offscreen scene
   * draw in the middle of the pass left whatever was painted after it
   * invisible for the frame (a fresh tab stayed a blank card). A render only
   * lands on screen on the next frame, which it asks for. */
  if (panel_visible && runtime) {
    const View3D *host = static_cast<const View3D *>(area ? area->spacedata.first : nullptr);
    const int thumb_w = int(THUMB_W * scale) + 1;
    const int thumb_h = int(THUMB_H * scale) + 1;
    bool rendered = false;
    for (const ScenesDrawerCard &card : runtime->cards) {
      Scene *scene = reinterpret_cast<Scene *>(
          BKE_libblock_find_name(CTX_data_main(C), ID_SCE, card.scene_name.c_str()));
      if (scene == nullptr) {
        continue;
      }
      ScenesDrawerThumb &t = runtime->thumbs[card.scene_name];
      const double before = t.last_render_time;
      view3d_scenes_drawer_thumb_render(t, scene, host, thumb_w, thumb_h,
                                        card.is_active ? 0.5 : 1.5);
      rendered |= (t.last_render_time != before);
    }
    if (rendered && !runtime->redraw_pending) {
      /* `ED_region_tag_redraw` here is a no-op: the region carries
       * RGN_DRAWING and `wm_draw.cc` clears `do_draw` right after this pass.
       * Flag the runtime and queue the drawer's own notifier; the region
       * listener tags the redraw from the next event loop. */
      runtime->redraw_pending = true;
      WM_event_add_notifier(const_cast<bContext *>(C), NC_SPACE | ND_SPACE_SCENES_DRAWER, nullptr);
    }
  }
}

}  // namespace blender
