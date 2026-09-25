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

void read_string(PointerRNA *ptr, const char *name, std::string &out)
{
  out.clear();
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (prop == nullptr) {
    return;
  }
  char fixed[256];
  char *buf = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), nullptr);
  out.assign(buf ? buf : "");
  if (buf != fixed && buf != nullptr) {
    /* 5.2: MEM_freeN is gone for void*; same port as view3d_agent_panel_sync.cc. */
    MEM_delete_void(static_cast<void *>(buf));
  }
}

int read_int(PointerRNA *ptr, const char *name, const int fallback)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop ? RNA_property_int_get(ptr, prop) : fallback;
}

bool read_bool(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop ? RNA_property_boolean_get(ptr, prop) : false;
}

/** Pull the tab list Python keeps on the WindowManager into the runtime,
 * keeping the previous rects until this pass lays them out again. */
void sync_cards(const bContext *C, ScenesDrawerRuntime *runtime)
{
  runtime->cards.clear();
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *tabs = RNA_struct_find_property(&wm_ptr, "mixar_scene_tabs");
  if (tabs == nullptr) {
    return;
  }
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&wm_ptr, tabs, &iter);
  while (iter.valid) {
    PointerRNA tab_ptr = iter.ptr;
    ScenesDrawerCard card;
    read_string(&tab_ptr, "scene_name", card.scene_name);
    read_string(&tab_ptr, "session_id", card.session_id);
    read_string(&tab_ptr, "last_text", card.last_text);
    const int status = read_int(&tab_ptr, "status", 0);
    card.status = (status >= 0 && status <= 3) ? ScenesDrawerTabStatus(status) :
                                                 ScenesDrawerTabStatus::Idle;
    card.workers_done = read_int(&tab_ptr, "workers_done", 0);
    card.workers_total = read_int(&tab_ptr, "workers_total", 0);
    card.is_active = read_bool(&tab_ptr, "is_active");
    card.attention = read_bool(&tab_ptr, "attention");
    runtime->cards.push_back(std::move(card));
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
}

void with_alpha(const float src[4], const float alpha, float r_out[4])
{
  r_out[0] = src[0];
  r_out[1] = src[1];
  r_out[2] = src[2];
  r_out[3] = src[3] * alpha;
}

void draw_elided(const int font_id,
                 const std::string &text,
                 const float x,
                 const float baseline_y,
                 const float max_width,
                 const float color[4])
{
  if (text.empty() || max_width <= 0.0f) {
    return;
  }
  BLF_color4fv(font_id, color);
  if (BLF_width(font_id, text.c_str(), text.size()) <= max_width) {
    BLF_position(font_id, x, baseline_y, 0.0f);
    BLF_draw(font_id, text.c_str(), text.size());
    return;
  }
  const float ellipsis_w = BLF_width(font_id, "…", strlen("…"));
  float measured = 0.0f;
  const size_t fit = BLF_width_to_strlen(
      font_id, text.c_str(), text.size(), std::max(max_width - ellipsis_w, 0.0f), &measured);
  std::string cut = text.substr(0, fit) + "…";
  BLF_position(font_id, x, baseline_y, 0.0f);
  BLF_draw(font_id, cut.c_str(), cut.size());
}

const char *status_label(const ScenesDrawerTabStatus status)
{
  switch (status) {
    case ScenesDrawerTabStatus::Working:
      return "Working";
    case ScenesDrawerTabStatus::Waiting:
      return "Waiting for you";
    case ScenesDrawerTabStatus::Done:
      return "Done";
    default:
      return "Idle";
  }
}

const float *status_color(const ScenesDrawerTabStatus status)
{
  const ui::mixar_tokens::Palette &zen = ui::mixar_tokens::mixar_zen();
  switch (status) {
    case ScenesDrawerTabStatus::Working:
      return zen.primary;
    case ScenesDrawerTabStatus::Waiting:
      return zen.warning;
    case ScenesDrawerTabStatus::Done:
      return zen.action;
    default:
      return zen.secondary;
  }
}

void clear_tab_gutter(const int xmin, const int width, const int height)
{
  GPU_blend(GPU_BLEND_NONE);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.0f, 0.0f, 0.0f, 0.0f);
  immRectf(pos, float(xmin), 0.0f, float(xmin + width), float(height));
  immUnbindProgram();
  GPU_blend(GPU_BLEND_ALPHA);
}

/** Paint the labeled Scenes tab with its flat inner edge at `x_left`. */
void draw_grip(const float x_left, const float y_centre)
{
  const float scale = UI_SCALE_FAC;
  const float grip_w = VIEW3D_SCENES_DRAWER_GRIP_WIDTH * scale;
  const float grip_h = VIEW3D_SCENES_DRAWER_GRIP_HEIGHT * scale;
  const float x_right = x_left + grip_w;
  const float radius = grip_w * 0.5f;

  rcti pane;
  pane.xmin = int(std::floor(x_left));
  pane.xmax = int(std::ceil(x_right));
  pane.ymin = int(std::floor(y_centre - grip_h * 0.5f));
  pane.ymax = int(std::ceil(y_centre + grip_h * 0.5f));

  int scissor_prev[4];
  GPU_scissor_get(scissor_prev);
  const int clip_w = pane.xmax - int(std::floor(x_left));
  if (clip_w > 0 && BLI_rcti_size_y(&pane) > 0) {
    GPU_scissor(pane.xmin, pane.ymin, clip_w, BLI_rcti_size_y(&pane));
    rctf tab;
    BLI_rctf_rcti_copy(&tab, &pane);
    MIXAR_THEME_LOAD(outer_green, CinemaPillOnB);
    MIXAR_THEME_LOAD(inner_dark, ViewportFill);
    /* Only the outer (right) corners round; the seam with the panel is flat. */
    ui::draw_roundbox_corner_set(ui::CNR_TOP_RIGHT | ui::CNR_BOTTOM_RIGHT);
    ui::draw_roundbox_4fv_ex(&tab, outer_green, inner_dark, 0.0f, nullptr, 0.0f, radius);
    ui::draw_roundbox_4fv(&tab, false, radius, ui::mixar_tokens::mixar_zen().border);
  }
  GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);

  const int font = BLF_default();
  BLF_size(font, 12.0f * scale);
  const char *label = "Scenes";
  const size_t label_len = strlen(label);
  const float text_w = BLF_width(font, label, label_len);
  const float text_h = BLF_height_max(font);
  BLF_color4fv(font, ui::mixar_tokens::mixar_zen().text);
  BLF_enable(font, BLF_ROTATION);
  BLF_rotation(font, float(M_PI_2));
  BLF_position(font, 0.5f * (x_left + x_right) + text_h * 0.32f, y_centre - text_w * 0.5f, 0.0f);
  BLF_draw(font, label, label_len);
  BLF_rotation(font, 0.0f);
  BLF_disable(font, BLF_ROTATION);
}

void draw_pill(const rctf &rect, const float fill[4], const float radius)
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, radius, fill);
}

}  // namespace

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
        Scene *scene = reinterpret_cast<Scene *>(BKE_libblock_find_name(CTX_data_main(C), ID_SCE, card.scene_name.c_str()));
        if (scene != nullptr) {
          ScenesDrawerThumb &t = runtime->thumbs[card.scene_name];
          const View3D *host = static_cast<const View3D *>(area ? area->spacedata.first : nullptr);
          view3d_scenes_drawer_thumb_render(t, scene, host, BLI_rcti_size_x(&thumb) + 1,
                                            BLI_rcti_size_y(&thumb) + 1, card.is_active ? 0.5 : 1.5);
          if (t.has_render) {
            GPU_viewport_draw_to_screen_ex(t.viewport, 0, &thumb, true, true);
            ED_region_pixelspace(region);
            GPU_blend(GPU_BLEND_ALPHA);
          }
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
}

}  // namespace blender
