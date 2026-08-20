/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Past-chats overlay: a Mixar-styled floating card listing archived chat
 * sessions, drawn in screen-space on top of the message area (after
 * ui::view2d_view_restore, like the scroll indicator).
 *
 * Data flows one way from Python:
 *   - visibility:  WindowManager.mixie_chat_history_visible (bool, toggled
 *     by MIXIE_CHAT_OT_show_history in the header, which also syncs)
 *   - rows:        WindowManager.mixie_chat_history_entries (name /
 *     session_id / when / group), the runtime mirror of
 *     ~/.mixar/chat_history/ — `group` is a precomputed date-bucket label
 *     ("Today", "Yesterday", ...) rendered as section headers
 *   - current:     scene.mixie_session_id marks the open chat's row
 *
 * This file owns panel layout + drawing: search field (type-to-filter,
 * always focused while open), date-group section headers, pixel-smooth
 * eased scrolling (rows scissor-clip to the list viewport), keyboard
 * selection highlight, and the header close button. Event handling +
 * cursor live in mixie_chat_history_events.cc; shared helpers in
 * mixie_chat_history_util.cc.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_math_vector.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"

#include "BLF_api.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_history_intern.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static const float COL_ACCENT[4] = CHAT_ACCENT_LIVE;

/* -------------------------------------------------------------------- */
/** \name Small Helpers
 * \{ */

static SpaceMixieChat *history_space_from_area(ScrArea *area)
{
  /* SPACE_AGENT_BUBBLE reuses these callbacks via its layout-compatible
   * spacedata struct (see DNA_space_types.h on SpaceAgentBubble). */
  if (!area || !area->spacedata.first ||
      (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE))
  {
    return nullptr;
  }
  return static_cast<SpaceMixieChat *>(area->spacedata.first);
}

static float ease_out_cubic(float t)
{
  t = std::max(0.0f, std::min(1.0f, t));
  const float t1 = t - 1.0f;
  return t1 * t1 * t1 + 1.0f;
}

/** One line of the scrollable list: a date-group header or an entry row. */
struct HistoryDisplayItem {
  int entry_index;       /* index into the filtered entries, -1 = group header */
  const char *group;     /* header label (points into the entries vector) */
  float content_top;     /* px offset from content top, grows downward */
  float height;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Visibility (Python-registered WM bool)
 * \{ */

void mixie_chat_history_set_visible(bContext *C, bool visible)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_history_visible");
  if (!prop) {
    return;
  }
  RNA_property_boolean_set(&wm_ptr, prop, visible);
  /* Every chat surface (editor + floating bubble) shows the overlay —
   * repaint them all via the space notifier the listener already handles. */
  WM_main_add_notifier(NC_SPACE | ND_SPACE_MIXIE_CHAT, nullptr);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

/** Search field: rounded box, query text (tail-clipped) or placeholder,
 * and a static caret — the field is always focused while the overlay is
 * open (all typing filters the list). */
static void history_draw_search(
    MixieChatRuntime *rt, int font_id, int text_px, float scale, float slide, float ease)
{
  rctf field = rt->history_search_bounds;
  field.ymin -= slide;
  field.ymax -= slide;
  const float radius = 8.0f * scale;
  const float inner_pad = 10.0f * scale;

  float bg[4] = {HIST_COL_SEARCH_BG[0], HIST_COL_SEARCH_BG[1], HIST_COL_SEARCH_BG[2],
                 HIST_COL_SEARCH_BG[3] * ease};
  float outline[4] = {HIST_COL_SEARCH_OUTLINE[0], HIST_COL_SEARCH_OUTLINE[1],
                      HIST_COL_SEARCH_OUTLINE[2], HIST_COL_SEARCH_OUTLINE[3] * ease};
  chat_ui_draw_rounded_rect(&field, radius, bg);
  chat_ui_draw_rounded_rect_outline(&field, radius, outline, 1.0f);

  const float text_x = field.xmin + inner_pad;
  const float avail_w = (field.xmax - inner_pad) - text_x;
  const float baseline =
      (field.ymin + field.ymax) * 0.5f - float(text_px) * 0.35f;

  const char *query = rt->history_search;
  float caret_x = text_x;
  if (query[0] == '\0') {
    float hint_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                         HIST_COL_MUTED[3] * 0.85f * ease};
    /* Placeholder sits right of the caret so the two don't overlap. */
    hist_draw_label(
        "Search chats\xe2\x80\xa6", font_id, text_px, text_x + 5.0f * scale, baseline, hint_col);
  }
  else {
    /* Tail-clip: drop leading characters until the remainder fits, so the
     * end of the query (where the caret is) always stays visible. */
    BLF_size(font_id, float(text_px));
    const char *start = query;
    while (*start && BLF_width(font_id, start, strlen(start)) > avail_w) {
      start += std::max(1, BLI_str_utf8_size_safe(start));
    }
    float text_col[4] = {HIST_COL_TITLE[0], HIST_COL_TITLE[1], HIST_COL_TITLE[2],
                         HIST_COL_TITLE[3] * ease};
    hist_draw_label(start, font_id, text_px, text_x, baseline, text_col);
    caret_x = text_x + BLF_width(font_id, start, strlen(start)) + 1.0f * scale;
  }

  /* Caret. */
  {
    rctf caret;
    const float caret_half_h = float(text_px) * 0.62f;
    const float cy = (field.ymin + field.ymax) * 0.5f;
    BLI_rctf_init(&caret, caret_x, caret_x + 1.5f * scale, cy - caret_half_h, cy + caret_half_h);
    float caret_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.9f * ease};
    chat_ui_draw_rounded_rect(&caret, 0.75f * scale, caret_col);
  }
}

void mixie_chat_draw_history_overlay(const bContext *C, ARegion *region)
{
  ScrArea *area = CTX_wm_area(C);
  SpaceMixieChat *smixie = history_space_from_area(area);
  if (!smixie) {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  wmWindowManager *wm = CTX_wm_manager(C);
  const bool visible = mixie_chat_history_read_visible(wm);

  const double now = BLI_time_now_seconds();
  if (visible && !rt->history_overlay_active) {
    /* Opening edge: restart animation, scroll, search, selection. */
    rt->history_anim_start = now;
    rt->history_scroll_px = 0.0f;
    rt->history_scroll_target = 0.0f;
    rt->history_scroll_last_time = 0.0;
    rt->history_search[0] = '\0';
    rt->history_sel = -1;
    rt->history_confirm_id[0] = '\0';
  }
  rt->history_overlay_active = visible;
  if (!visible) {
    mixie_chat_history_reset_runtime(rt);
    return;
  }

  /* Smooth scroll: ease the drawn offset toward the target (events only
   * ever write the target). Exponential approach, framerate-independent. */
  float dt = 0.0f;
  if (rt->history_scroll_last_time > 0.0) {
    dt = float(std::min(now - rt->history_scroll_last_time, 0.05));
  }
  rt->history_scroll_last_time = now;
  {
    const float diff = rt->history_scroll_target - rt->history_scroll_px;
    if (std::abs(diff) <= 0.25f) {
      rt->history_scroll_px = rt->history_scroll_target;
    }
    else {
      const float f = 1.0f - std::exp(-HIST_SCROLL_APPROACH_RATE * dt);
      rt->history_scroll_px += diff * f;
    }
  }

  /* Open animation (fade + slide), pumped like the other chat animations.
   * Smooth scrolling shares the same pump while it settles. */
  const float anim_t = float((now - rt->history_anim_start) / HIST_OPEN_ANIM_DURATION);
  const float ease = ease_out_cubic(anim_t);
  const bool scroll_settling = (rt->history_scroll_px != rt->history_scroll_target);
  mixie_chat_anim_pump_request(C, anim_t < 1.0f || scroll_settling);
  if ((anim_t < 1.0f || scroll_settling) && area) {
    ED_area_tag_redraw(area);
  }

  blender::Vector<HistoryDrawEntry> entries;
  mixie_chat_history_read_entries(wm, entries);

  /* Type-to-filter: case-insensitive substring match on the title. */
  blender::Vector<int> filtered;
  for (int i = 0; i < int(entries.size()); i++) {
    if (rt->history_search[0] == '\0' ||
        BLI_strcasestr(entries[i].title, rt->history_search) != nullptr)
    {
      filtered.append(i);
    }
  }

  /* Current chat's session id (marks its row with the accent dot). */
  char current_id[128] = "";
  if (Scene *scene = CTX_data_scene(C)) {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    PropertyRNA *sid_prop = RNA_struct_find_property(&scene_ptr, "mixie_session_id");
    if (sid_prop) {
      char *value = RNA_property_string_get_alloc(
          &scene_ptr, sid_prop, current_id, sizeof(current_id), nullptr);
      if (value && value != current_id) {
        BLI_strncpy(current_id, value, sizeof(current_id));
        MEM_delete_void(value);
      }
    }
  }

  const float scale = UI_SCALE_FAC;
  const int winx = region->winx;
  const int winy = region->winy;
  const int font_id = BLF_default();
  const int title_px = int(14.0f * scale);
  const int meta_px = int(12.0f * scale);
  const int group_px = int(11.0f * scale);
  const int header_px = int(15.0f * scale);

  const float pad = HIST_PANEL_PAD * scale;
  const float row_h = HIST_ROW_HEIGHT * scale;
  const float group_h = HIST_GROUP_HEADER_HEIGHT * scale;
  const float header_h = HIST_HEADER_HEIGHT * scale;

  const bool store_empty = entries.is_empty();
  const float search_h = store_empty ? 0.0f : HIST_SEARCH_AREA_HEIGHT * scale;

  float panel_w = std::min(float(winx) - 2.0f * HIST_PANEL_SIDE_MARGIN * scale,
                           HIST_PANEL_MAX_WIDTH * scale);
  panel_w = std::max(panel_w, 120.0f * scale);

  /* Build the display list: entry rows with a section header wherever the
   * date-group label changes (entries arrive newest-first from Python). */
  blender::Vector<HistoryDisplayItem> items;
  float content_h = 0.0f;
  {
    const char *prev_group = "";
    for (const int entry_index : filtered) {
      const HistoryDrawEntry &entry = entries[entry_index];
      if (entry.group[0] != '\0' && !STREQ(entry.group, prev_group)) {
        items.append({-1, entry.group, content_h, group_h});
        content_h += group_h;
        prev_group = entry.group;
      }
      items.append({entry_index, nullptr, content_h, row_h});
      content_h += row_h;
    }
  }

  /* List viewport height: fit the region, capped, leaving breathing room. */
  const float avail_h = float(winy) - HIST_PANEL_TOP_MARGIN * scale - header_h - search_h - pad -
                        24.0f * scale;
  float view_h = std::min(content_h, std::min(avail_h, HIST_LIST_MAX_HEIGHT * scale));
  const bool no_matches = (!store_empty && filtered.is_empty());
  if (store_empty || no_matches) {
    view_h = 64.0f * scale;
  }
  view_h = std::max(view_h, row_h);

  const float panel_h = header_h + search_h + view_h + pad;
  const float panel_x = (float(winx) - panel_w) * 0.5f;
  const float panel_top = float(winy) - HIST_PANEL_TOP_MARGIN * scale;
  const float panel_bottom = panel_top - panel_h;

  /* Clamp scrolling to the content range (filter edits shrink it). */
  const float max_scroll = std::max(0.0f, content_h - view_h);
  rt->history_scroll_target = std::clamp(rt->history_scroll_target, 0.0f, max_scroll);
  rt->history_scroll_px = std::clamp(rt->history_scroll_px, 0.0f, max_scroll);
  rt->history_content_h = content_h;
  rt->history_view_h = view_h;

  /* Hit bounds at the FINAL (unslid) position for stable click targets. */
  BLI_rctf_init(&rt->history_panel_bounds, panel_x, panel_x + panel_w, panel_bottom, panel_top);
  const float list_top = panel_top - header_h - search_h;
  const float list_bottom = list_top - view_h;
  BLI_rctf_init(&rt->history_list_bounds, panel_x, panel_x + panel_w, list_bottom, list_top);
  {
    const float close_half = HIST_CLOSE_SIZE * 0.5f * scale;
    const float close_cx = panel_x + panel_w - pad - close_half;
    const float close_cy = panel_top - header_h * 0.5f;
    BLI_rctf_init(&rt->history_close_bounds,
                  close_cx - close_half,
                  close_cx + close_half,
                  close_cy - close_half,
                  close_cy + close_half);
  }
  if (!store_empty) {
    const float field_h = HIST_SEARCH_FIELD_HEIGHT * scale;
    const float field_top = panel_top - header_h - (search_h - field_h) * 0.5f;
    BLI_rctf_init(&rt->history_search_bounds,
                  panel_x + pad,
                  panel_x + panel_w - pad,
                  field_top - field_h,
                  field_top);
  }
  else {
    BLI_rctf_init(&rt->history_search_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  }
  rt->history_rows.clear();
  rt->history_sel = std::min(rt->history_sel, int(filtered.size()) - 1);

  /* Mouse position for hover (freshest source, like the empty state). */
  wmWindow *win = CTX_wm_window(C);
  float mouse_x = -1000.0f, mouse_y = -1000.0f;
  if (win) {
    mouse_x = float(win->eventstate->xy[0] - region->winrct.xmin);
    mouse_y = float(win->eventstate->xy[1] - region->winrct.ymin);
  }

  const float slide = HIST_OPEN_SLIDE_PX * scale * (1.0f - ease);

  GPU_blend(GPU_BLEND_ALPHA);

  /* Scrim: dim the chat behind the card. */
  {
    rctf full;
    BLI_rctf_init(&full, 0.0f, float(winx), 0.0f, float(winy));
    float scrim[4] = {HIST_COL_SCRIM[0], HIST_COL_SCRIM[1], HIST_COL_SCRIM[2],
                      HIST_COL_SCRIM[3] * ease};
    chat_ui_draw_rounded_rect(&full, 0.0f, scrim);
  }

  const float radius = HIST_PANEL_RADIUS * scale;
  rctf panel;
  BLI_rctf_init(&panel, panel_x, panel_x + panel_w, panel_bottom - slide, panel_top - slide);

  /* Soft shadow substitute: a slightly larger dark card behind. */
  {
    rctf shadow = panel;
    const float grow = 3.0f * scale;
    shadow.xmin -= grow;
    shadow.xmax += grow;
    shadow.ymin -= grow * 1.6f;
    shadow.ymax += grow * 0.4f;
    float col[4] = {HIST_COL_PANEL_SHADOW[0], HIST_COL_PANEL_SHADOW[1], HIST_COL_PANEL_SHADOW[2],
                    HIST_COL_PANEL_SHADOW[3] * ease};
    chat_ui_draw_rounded_rect(&shadow, radius + grow, col);
  }

  /* Card. */
  {
    float fill[4] = {HIST_COL_PANEL[0], HIST_COL_PANEL[1], HIST_COL_PANEL[2],
                     HIST_COL_PANEL[3] * ease};
    float outline[4] = {HIST_COL_PANEL_OUTLINE[0], HIST_COL_PANEL_OUTLINE[1],
                        HIST_COL_PANEL_OUTLINE[2], HIST_COL_PANEL_OUTLINE[3] * ease};
    chat_ui_draw_rounded_rect(&panel, radius, fill);
    chat_ui_draw_rounded_rect_outline(&panel, radius, outline, 1.0f);
  }

  /* Header: "Chats" + count left, close X right, hairline divider below. */
  {
    const float header_center = panel.ymax - header_h * 0.5f;
    const float baseline = header_center - float(header_px) * 0.35f;

    float title_col[4] = {HIST_COL_HEADER_TEXT[0], HIST_COL_HEADER_TEXT[1],
                          HIST_COL_HEADER_TEXT[2], HIST_COL_HEADER_TEXT[3] * ease};
    hist_draw_label("Chats", font_id, header_px, panel.xmin + pad, baseline, title_col);

    if (!store_empty) {
      char count_buf[32];
      if (rt->history_search[0] != '\0') {
        SNPRINTF(count_buf, "%d / %d", int(filtered.size()), int(entries.size()));
      }
      else {
        SNPRINTF(count_buf, "%d", int(entries.size()));
      }
      float count_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                            HIST_COL_MUTED[3] * ease};
      const float title_w = hist_text_width("Chats", font_id, header_px);
      hist_draw_label(count_buf, font_id, meta_px, panel.xmin + pad + title_w + 8.0f * scale,
                      header_center - float(meta_px) * 0.35f, count_col);
    }

    /* Close button (X, ring on hover). */
    {
      const bool close_hovered = BLI_rctf_isect_pt(&rt->history_close_bounds, mouse_x, mouse_y);
      const float close_cx = BLI_rctf_cent_x(&rt->history_close_bounds);
      const float close_cy = BLI_rctf_cent_y(&rt->history_close_bounds) - slide;
      if (close_hovered) {
        rctf ring = rt->history_close_bounds;
        ring.ymin -= slide;
        ring.ymax -= slide;
        float ring_col[4] = {HIST_COL_DELETE_HOVER_BG[0], HIST_COL_DELETE_HOVER_BG[1],
                             HIST_COL_DELETE_HOVER_BG[2], HIST_COL_DELETE_HOVER_BG[3] * ease};
        chat_ui_draw_rounded_rect(&ring, HIST_CLOSE_SIZE * 0.5f * scale, ring_col);
      }
      float x_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                        (close_hovered ? 1.0f : 0.8f) * ease};
      if (close_hovered) {
        x_col[0] = HIST_COL_HEADER_TEXT[0];
        x_col[1] = HIST_COL_HEADER_TEXT[1];
        x_col[2] = HIST_COL_HEADER_TEXT[2];
      }
      hist_draw_x_glyph(close_cx, close_cy, 4.6f * scale, x_col, scale);
    }

    rctf divider;
    BLI_rctf_init(&divider,
                  panel.xmin + pad,
                  panel.xmax - pad,
                  panel.ymax - header_h,
                  panel.ymax - header_h + 1.0f * scale);
    float div_col[4] = {HIST_COL_DIVIDER[0], HIST_COL_DIVIDER[1], HIST_COL_DIVIDER[2],
                        HIST_COL_DIVIDER[3] * ease};
    chat_ui_draw_rounded_rect(&divider, 0.0f, div_col);
  }

  if (!store_empty) {
    history_draw_search(rt, font_id, title_px, scale, slide, ease);
  }

  /* Empty states: no archived chats at all / no titles match the query. */
  if (store_empty || no_matches) {
    float title_col[4] = {HIST_COL_TITLE[0], HIST_COL_TITLE[1], HIST_COL_TITLE[2],
                          HIST_COL_TITLE[3] * ease};
    float hint_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                         HIST_COL_MUTED[3] * ease};

    const char *empty_text = store_empty ? "No past chats yet" : "No chats match your search";
    const char *hint_text = store_empty ?
                                "New Chat saves the current conversation here" :
                                "Backspace to edit, Esc to clear";
    const float cx = (panel.xmin + panel.xmax) * 0.5f;
    const float cy = (list_top + list_bottom) * 0.5f - slide;

    float w = hist_text_width(empty_text, font_id, title_px);
    hist_draw_label(empty_text, font_id, title_px, cx - w * 0.5f, cy + 4.0f * scale, title_col);
    w = hist_text_width(hint_text, font_id, meta_px);
    hist_draw_label(hint_text, font_id, meta_px, cx - w * 0.5f,
                    cy - (4.0f * scale + float(meta_px)), hint_col);

    GPU_blend(GPU_BLEND_NONE);
    /* Cursor is owned by mixie_chat_history_cursor (region event_cursor
     * callback) — never set it from a draw callback: draws fire for reasons
     * unrelated to the mouse (streaming redraws, scroll settling, the anim
     * pump), and would stomp the window cursor even while the mouse is over
     * another editor. */
    return;
  }

  /* Rows + group headers, scissor-clipped to the list viewport so the
   * pixel-smooth scroll can show partial rows at both edges. Regions draw
   * into a REGION-SIZED offscreen buffer (wm_draw_region_bind sets the
   * scissor to 0,0,winx,winy) — so GPU_scissor takes region-local coords
   * here, NOT window coords; restore the full-region scissor after. */
  const bool has_scrollbar = (content_h > view_h + 0.5f);
  const float row_xmin = panel_x + HIST_ROW_SIDE_INSET * scale;
  const float row_xmax =
      panel_x + panel_w - HIST_ROW_SIDE_INSET * scale - (has_scrollbar ? 8.0f * scale : 0.0f);

  bool any_hovered = false;

  GPU_scissor(int(std::floor(panel_x)),
              int(std::floor(list_bottom)),
              int(std::ceil(panel_w)) + 1,
              int(std::ceil(view_h)) + 1);

  for (const HistoryDisplayItem &item : items) {
    /* Content-space -> screen-space: scrolling moves content up. */
    const float item_top = list_top - item.content_top + rt->history_scroll_px;
    const float item_bottom = item_top - item.height;

    if (item.entry_index < 0) {
      /* Date-group section header. */
      if (item_bottom <= list_top + item.height && item_top >= list_bottom - item.height) {
        const float baseline = (item_top + item_bottom) * 0.5f - slide - float(group_px) * 0.30f;
        float group_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                              HIST_COL_MUTED[3] * 0.9f * ease};
        hist_draw_label(item.group, font_id, group_px, row_xmin + 8.0f * scale, baseline,
                        group_col);
      }
      continue;
    }

    const HistoryDrawEntry &entry = entries[item.entry_index];
    const bool is_current = (current_id[0] != '\0') && STREQ(entry.session_id, current_id);
    const bool is_armed = (rt->history_confirm_id[0] != '\0') &&
                          STREQ(entry.session_id, rt->history_confirm_id);

    const float row_top = item_top;
    const float row_bottom = item_bottom;
    const float row_center = (row_top + row_bottom) * 0.5f;

    /* Hit rects for EVERY filtered row (even offscreen ones — keyboard
     * selection needs their content offsets; mouse hits are additionally
     * gated on history_list_bounds). */
    HistoryRowHit hit;
    BLI_rctf_init(&hit.bounds, row_xmin, row_xmax, row_bottom, row_top);
    const float del_half = HIST_DELETE_SIZE * 0.5f * scale;
    const float del_cx = row_xmax - HIST_DELETE_RIGHT_INSET * scale - del_half;
    BLI_rctf_init(&hit.delete_bounds,
                  del_cx - del_half,
                  del_cx + del_half,
                  row_center - del_half,
                  row_center + del_half);
    hit.content_top = item.content_top;
    BLI_strncpy(hit.session_id, entry.session_id, sizeof(hit.session_id));
    const bool in_list = BLI_rctf_isect_pt(&rt->history_list_bounds, mouse_x, mouse_y);
    hit.is_hovered = in_list && BLI_rctf_isect_pt(&hit.bounds, mouse_x, mouse_y);
    hit.delete_hovered = hit.is_hovered &&
                         BLI_rctf_isect_pt(&hit.delete_bounds, mouse_x, mouse_y);
    any_hovered |= hit.is_hovered;
    const int row_index = int(rt->history_rows.size());
    rt->history_rows.append(hit);

    /* Skip drawing rows fully outside the viewport. */
    if (row_bottom > list_top || row_top < list_bottom) {
      continue;
    }

    const bool is_selected = (row_index == rt->history_sel);

    /* Draw geometry follows the slide offset. */
    const float draw_top = row_top - slide;
    const float draw_bottom = row_bottom - slide;
    const float draw_center = row_center - slide;

    if (hit.is_hovered || is_selected) {
      rctf hover_rect;
      BLI_rctf_init(
          &hover_rect, row_xmin, row_xmax, draw_bottom + 2.0f * scale, draw_top - 2.0f * scale);
      float hover_col[4];
      chat_ui_get_history_row_hover_color(hover_col);
      hover_col[3] *= ease * (hit.is_hovered ? 1.0f : 0.7f);
      chat_ui_draw_rounded_rect(&hover_rect, HIST_ROW_RADIUS * scale, hover_col);
      if (is_selected) {
        /* Keyboard selection: accent outline so it reads distinctly from
         * a transient mouse hover. */
        float sel_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.45f * ease};
        chat_ui_draw_rounded_rect_outline(&hover_rect, HIST_ROW_RADIUS * scale, sel_col, 1.0f);
      }
    }

    /* Accent dot on the currently open chat. */
    if (is_current) {
      const float dot_r = HIST_DOT_RADIUS * scale;
      const float dot_cx = row_xmin + 13.0f * scale;
      rctf dot;
      BLI_rctf_init(&dot, dot_cx - dot_r, dot_cx + dot_r, draw_center - dot_r,
                    draw_center + dot_r);
      float dot_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], COL_ACCENT[3] * ease};
      chat_ui_draw_rounded_rect(&dot, dot_r, dot_col);
    }

    /* Time label, right-aligned before the X. An armed row shows a red
     * "Delete?" prompt instead — click the X again to confirm. */
    const float del_zone_left = hit.delete_bounds.xmin - 8.0f * scale;
    const char *when_text = is_armed ? "Delete?" : entry.when;
    float when_w = 0.0f;
    if (when_text[0] != '\0') {
      when_w = hist_text_width(when_text, font_id, meta_px);
      float when_col[4];
      if (is_armed) {
        copy_v4_v4(when_col, HIST_COL_DELETE_HOVER);
        when_col[3] *= ease;
      }
      else {
        copy_v4_v4(when_col, HIST_COL_MUTED);
        when_col[3] *= 0.95f * ease;
      }
      hist_draw_label(when_text, font_id, meta_px, del_zone_left - when_w,
                      draw_center - float(meta_px) * 0.35f, when_col);
    }

    /* Title, ellipsis-clipped to the space before the time label. */
    {
      const float title_x = row_xmin + HIST_TITLE_INDENT * scale;
      const float title_max_w = (del_zone_left - when_w - 10.0f * scale) - title_x;
      char clipped[224];
      hist_text_ellipsis(entry.title[0] ? entry.title : "Untitled chat",
                         font_id, title_px, std::max(title_max_w, 20.0f * scale),
                         clipped, sizeof(clipped));
      const float *base_col = is_current ? HIST_COL_TITLE_CURRENT : HIST_COL_TITLE;
      float title_col[4] = {base_col[0], base_col[1], base_col[2], base_col[3] * ease};
      hist_draw_label(clipped, font_id, title_px, title_x,
                      draw_center - float(title_px) * 0.35f, title_col);
    }

    /* Delete X (ring + glyph). Armed rows keep a red-tinted ring and a red
     * glyph regardless of hover, signalling "click again to delete". */
    {
      if (is_armed || hit.delete_hovered) {
        rctf ring = hit.delete_bounds;
        ring.ymin -= slide;
        ring.ymax -= slide;
        const float *ring_base = is_armed ? HIST_COL_DELETE_ARMED_BG : HIST_COL_DELETE_HOVER_BG;
        float ring_col[4] = {ring_base[0], ring_base[1], ring_base[2], ring_base[3] * ease};
        chat_ui_draw_rounded_rect(&ring, del_half, ring_col);
      }
      const float *base_col = (is_armed || hit.delete_hovered) ? HIST_COL_DELETE_HOVER :
                                                                 HIST_COL_DELETE;
      float x_col[4] = {base_col[0], base_col[1], base_col[2], base_col[3] * ease};
      hist_draw_x_glyph(del_cx, draw_center, 4.2f * scale, x_col, scale);
    }
  }

  /* Restore the full-region scissor wm_draw_region_bind() established. */
  GPU_scissor(0, 0, region->winx, region->winy);

  /* Slim scrollbar thumb when the list overflows. */
  if (has_scrollbar) {
    const float track_top = list_top - 2.0f * scale;
    const float track_bottom = list_bottom + 2.0f * scale;
    const float track_h = track_top - track_bottom;
    if (track_h > 8.0f * scale) {
      const float thumb_h = std::max(track_h * view_h / content_h, 14.0f * scale);
      const float scroll_frac = (max_scroll > 0.0f) ? rt->history_scroll_px / max_scroll : 0.0f;
      const float thumb_top = track_top - (track_h - thumb_h) * scroll_frac - slide;
      rctf thumb;
      const float thumb_x = panel_x + panel_w - 7.0f * scale;
      BLI_rctf_init(&thumb, thumb_x, thumb_x + 3.5f * scale, thumb_top - thumb_h, thumb_top);
      float thumb_col[4] = {HIST_COL_SCROLL_THUMB[0], HIST_COL_SCROLL_THUMB[1],
                            HIST_COL_SCROLL_THUMB[2], HIST_COL_SCROLL_THUMB[3] * ease};
      chat_ui_draw_rounded_rect(&thumb, 1.75f * scale, thumb_col);
    }
  }

  GPU_blend(GPU_BLEND_NONE);

  /* Cursor is owned by mixie_chat_history_cursor (see above) — not set from
   * draw. */
  UNUSED_VARS(any_hovered);
}

/** \} */
}  // namespace blender
