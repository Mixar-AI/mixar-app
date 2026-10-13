/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Widgets of the Scenes drawer's draw pass: the RNA readers that
 * pull `wm.mixar_scene_tabs` into the region runtime, elided text, the status
 * pill palette and the pill painter. The layout of the pass itself is
 * `view3d_scenes_drawer_draw.cc`.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_math_base.h"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "GPU_shader_builtin.hh"
#include "BLI_string.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "UI_mixar_theme.hh"
#include "UI_resources.hh"

#include "view3d_scenes_drawer.hh"
#include "view3d_scenes_drawer_motion.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::view3d_scenes_drawer {

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

int read_enum(PointerRNA *ptr, const char *name, const int fallback)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop ? RNA_property_enum_get(ptr, prop) : fallback;
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
    read_string(&tab_ptr, "scene_uid", card.scene_uid);
    read_string(&tab_ptr, "scene_name", card.scene_name);
    read_string(&tab_ptr, "session_id", card.session_id);
    const int status = read_enum(&tab_ptr, "status", 0);
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
  std::erase_if(runtime->selected_uids, [&](const std::string &uid) {
    return std::none_of(runtime->cards.begin(), runtime->cards.end(),
                        [&](const ScenesDrawerCard &card) { return card.scene_uid == uid; });
  });
  if (std::none_of(runtime->cards.begin(), runtime->cards.end(),
                   [&](const ScenesDrawerCard &card) {
                     return card.scene_uid == runtime->selection_anchor;
                   })) {
    runtime->selection_anchor.clear();
  }
  /* A card deleted elsewhere (agent, another window) takes its rename with it. */
  if (!runtime->rename_uid.empty() &&
      std::none_of(runtime->cards.begin(), runtime->cards.end(),
                   [&](const ScenesDrawerCard &card) { return card.scene_uid == runtime->rename_uid; }))
  {
    runtime->rename_uid.clear();
  }
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

void draw_pill(const rctf &rect, const float fill[4], const float radius)
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, radius, fill);
}

void draw_trash(const rcti &box, const float scale, const float color[4])
{
  /* Use the same vector icon as menus/dialogs, at a readable UI-scaled size. */
  const float size = 16.0f * scale;
  const float x = (box.xmin + box.xmax - size) * 0.5f;
  const float y = (box.ymin + box.ymax - size) * 0.5f;
  uchar tint[4];
  for (int i = 0; i < 4; i++) {
    tint[i] = uchar(std::clamp(color[i], 0.0f, 1.0f) * 255.0f);
  }
  ui::icon_draw_ex(x, y, ICON_TRASH, 16.0f / size, 1.0f, 0.0f,
                   tint, false, UI_NO_ICON_OVERLAY_TEXT);
  GPU_blend(GPU_BLEND_ALPHA);
}

void draw_selection_mark(const rctf &card, const float scale)
{
  /* Batch selection must read at a glance next to the active row's wash, so
   * it is three cues, none of them subtle: a green tint over the whole card,
   * a two-pixel outline in the light focus green (the dark primary vanished
   * on the glass), and a filled check badge where the drag grip sits. */
  const ui::mixar_tokens::Palette &zen = ui::mixar_tokens::mixar_zen();
  const float radius = 10.0f * scale;
  float tint[4];
  with_alpha(zen.primary, 0.30f, tint);
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&card, true, radius, tint);
  float line[4];
  with_alpha(zen.focus, 1.0f, line);
  ui::draw_roundbox_4fv(&card, false, radius, line);
  rctf inner = card;
  BLI_rctf_pad(&inner, -U.pixelsize, -U.pixelsize);
  ui::draw_roundbox_4fv(&inner, false, radius - U.pixelsize, line);

  const float size = 18.0f * scale;
  const float cx = card.xmin + 15.0f * scale;
  const float cy = (card.ymin + card.ymax) * 0.5f;
  rctf badge = {cx - 0.5f * size, cx + 0.5f * size, cy - 0.5f * size, cy + 0.5f * size};
  draw_pill(badge, line, 0.5f * size);
  const float glyph = 14.0f * scale;
  uchar dark[4];
  for (int i = 0; i < 4; i++) {
    dark[i] = uchar(std::clamp(zen.canvas[i], 0.0f, 1.0f) * 255.0f);
  }
  ui::icon_draw_ex(cx - 0.5f * glyph, cy - 0.5f * glyph, ICON_CHECKMARK, 16.0f / glyph, 1.0f, 0.0f,
                   dark, false, UI_NO_ICON_OVERLAY_TEXT);
  GPU_blend(GPU_BLEND_ALPHA);
}

void draw_hint(const rcti &anchor, const char *text, const float scale)
{
  /* A small label to the LEFT of the control it explains (the trash sits at
   * the card's right edge), drawn after the cards so it floats above them. */
  const ui::mixar_tokens::Palette &zen = ui::mixar_tokens::mixar_zen();
  const int font = BLF_default();
  BLF_size(font, 10.5f * scale);
  const float tw = BLF_width(font, text, strlen(text));
  const float th = BLF_height_max(font);
  rctf box;
  box.xmax = float(anchor.xmin) - 6.0f * scale;
  box.xmin = box.xmax - tw - 14.0f * scale;
  box.ymax = float(anchor.ymax) + 1.0f * scale;
  box.ymin = box.ymax - th - 8.0f * scale;
  float fill[4], border[4];
  with_alpha(zen.panel, 0.98f, fill);
  with_alpha(zen.border, 1.0f, border);
  rctf outer = box;
  BLI_rctf_pad(&outer, U.pixelsize, U.pixelsize);
  draw_pill(outer, border, 6.0f * scale + U.pixelsize);
  draw_pill(box, fill, 6.0f * scale);
  BLF_color4fv(font, zen.strong);
  BLF_position(font, box.xmin + 7.0f * scale, box.ymin + 5.0f * scale, 0.0f);
  BLF_draw(font, text, strlen(text));
}

void update_card_motion(ScenesDrawerRuntime *runtime)
{
  const double now = BLI_time_now_seconds();
  const double dt = runtime->cards_draw_time > 0.0 ? now - runtime->cards_draw_time : 0.0;
  runtime->cards_draw_time = now;
  const bool dragging = runtime->drag_target >= 0 && !runtime->drag_settling;
  for (int i = 0; i < int(runtime->cards.size()); i++) {
    if (runtime->cards[i].scene_uid == runtime->drag_scene) {
      runtime->drag_index = i;
      break;
    }
  }
  std::unordered_map<std::string, float> rows;
  for (int i = 0; i < int(runtime->cards.size()); i++) {
    const auto &uid = runtime->cards[i].scene_uid;
    const float target = dragging ? reorder_preview_row(i, runtime->drag_index, runtime->drag_target) : i;
    const auto previous = runtime->card_rows.find(uid);
    rows[uid] = previous == runtime->card_rows.end() || runtime->drag_target < 0 ?
                    target : follow_position(previous->second, target, dt);
  }
  runtime->card_rows = std::move(rows);
}

/* Decoration only: the existing list scissor clips this wash, and the original
 * card rect remains the sole hit target. No drawing crosses into the viewport. */
void draw_selection_wash(const rctf &card, const float panel_right,
                         const float region_right, const float scale)
{
  const auto &zen = ui::mixar_tokens::mixar_zen();
  const float radius = 10.0f * scale;
  const float width = region_right - card.xmin;
  if (width <= 2.0f * radius) {
    return;
  }
  const auto smooth = [](const float t) { return t * t * (3.0f - 2.0f * t); };
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint color = GPU_vertformat_attr_add(format, "color", gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  /* A small fixed strip: no textures, allocations, timers or retained GPU state. */
  /* Sample the short curves independently of the wide card body, so resizing
   * cannot reduce a rounded join to one or two straight edges. */
  constexpr int band_segments = 24;
  constexpr int segments = 4 * band_segments;
  const float stops[5] = {card.xmin, card.xmin + radius,
                          std::max(card.xmin + radius, panel_right - radius),
                          panel_right, region_right};
  immBegin(GPU_PRIM_TRI_STRIP, 2 * (segments + 1));
  for (int i = 0; i <= segments; i++) {
    const int band = std::min(i / band_segments, 3);
    const float t = float(i - band * band_segments) / band_segments;
    const float x = stops[band] + (stops[band + 1] - stops[band]) * t;
    float inset = 0.0f;
    if (x < card.xmin + radius) {
      const float dx = card.xmin + radius - x;
      inset = radius - std::sqrt(std::max(0.0f, radius * radius - dx * dx));
    }
    /* Concave joins open out toward the panel edge, within the row gap. */
    const float dx = std::clamp(x - (panel_right - radius), 0.0f, radius);
    const float flare = radius - std::sqrt(std::max(0.0f, radius * radius - dx * dx));
    const float fade = smooth(std::clamp((x - card.xmin - width * 0.72f) /
                                            (width * 0.28f), 0.0f, 1.0f));
    /* Keep the glass/progress visible on the body; cover its right outline
     * before joining the panel margin, then end at the region canvas color. */
    const float cover_start = card.xmin + (card.xmax - card.xmin) * 0.65f;
    const float cover = smooth(std::clamp((x - cover_start) /
                                             std::max(scale, card.xmax - radius - cover_start),
                                         0.0f, 1.0f));
    float fill[4];
    for (int c = 0; c < 3; c++) {
      fill[c] = zen.canvas[c] + (zen.primary[c] - zen.canvas[c]) * 0.58f * (1.0f - fade);
    }
    fill[3] = 0.62f + 0.38f * cover;
    immAttr4fv(color, fill);
    immVertex2f(pos, x, card.ymin + inset - flare);
    immAttr4fv(color, fill);
    immVertex2f(pos, x, card.ymax - inset + flare);
  }
  immEnd();
  immUnbindProgram();
}

void draw_drag_preview(ScenesDrawerRuntime *runtime, ARegion *region, const float scale)
{
  runtime->drag_rect = {};
  if (runtime->drag_target < 0 || BLI_rcti_size_y(&runtime->list_rect) <= 0) {
    return;
  }
  const auto found = std::find_if(runtime->cards.begin(), runtime->cards.end(),
                                [&](const ScenesDrawerCard &card) {
                                  return card.scene_uid == runtime->drag_scene;
                                });
  if (found == runtime->cards.end()) {
    return;
  }
  const auto &zen = ui::mixar_tokens::mixar_zen();
  rctf rect;
  BLI_rctf_rcti_copy(&rect, &runtime->list_rect);
  BLI_rctf_translate(&rect, -region->winrct.xmin, -region->winrct.ymin);
  const float height = VIEW3D_SCENES_DRAWER_CARD_H * scale;
  const float pointer_top = runtime->drag_settling ? runtime->drag_preview_top :
                                                       runtime->drag_y + runtime->drag_offset_y;
  rect.ymax = std::clamp(pointer_top - region->winrct.ymin,
                         std::min(rect.ymin + height, rect.ymax), rect.ymax);
  rect.ymin = rect.ymax - height;
  rect.xmin += 4.0f * scale;
  rect.xmax -= 4.0f * scale;
  rctf shadow = rect;
  BLI_rctf_translate(&shadow, 0.0f, -3.0f * scale);
  BLI_rctf_pad(&shadow, 3.0f * scale, 3.0f * scale);
  float shade[4];
  with_alpha(zen.canvas, 0.85f, shade);
  draw_pill(shadow, shade, 12.0f * scale);
  draw_pill(rect, zen.panel, 10.0f * scale);
  ui::draw_roundbox_4fv(&rect, false, 10.0f * scale, zen.strong);
  rcti thumb = {int(rect.xmin + 8.0f * scale),
                int(rect.xmin + (8.0f + VIEW3D_SCENES_DRAWER_THUMB_W) * scale),
                int(rect.ymin + 8.0f * scale), int(rect.ymax - 8.0f * scale)};
  auto image = runtime->thumbs.find(found->scene_name);
  if (image != runtime->thumbs.end()) {
    view3d_scenes_drawer_thumb_draw(image->second, found->scene_name, thumb);
  }
  const int font = BLF_default();
  const float x = thumb.xmax + 10.0f * scale;
  const float width = rect.xmax - 8.0f * scale - x;
  BLF_size(font, 12.0f * scale);
  draw_elided(font, found->scene_name, x, rect.ymax - 24.0f * scale, width, zen.strong);
  BLF_size(font, 10.0f * scale);
  if (!runtime->drag_settling) {
    draw_elided(font, "Release to move", x, rect.ymin + 10.0f * scale, width, zen.secondary);
  }
  BLI_rcti_rctf_copy(&runtime->drag_rect, &rect);
  BLI_rcti_translate(&runtime->drag_rect, region->winrct.xmin, region->winrct.ymin);
}

}  // namespace blender::view3d_scenes_drawer
