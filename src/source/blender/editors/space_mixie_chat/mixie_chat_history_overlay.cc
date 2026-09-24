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
 * This file owns the panel layout (measure, display list, scroll easing,
 * hit bounds) and the search field; it hands a HistoryDrawFrame to
 * mixie_chat_history_chrome.cc (scrim, card, header, footer, empty state)
 * and mixie_chat_history_rows.cc (rows, scrollbar). Event handling +
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
      (area->spacetype != SPACE_AGENT_BUBBLE))
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
  const HistoryMode mode = mixie_chat_history_read_mode(wm);
  const bool checkpoints = (mode == HistoryMode::Checkpoints);
  const bool locked = checkpoints && mixie_chat_history_read_locked(wm);
  char notice[160] = "";
  if (checkpoints) {
    mixie_chat_history_read_notice(wm, notice, sizeof(notice));
  }

  const double now = BLI_time_now_seconds();
  const bool mode_changed = (rt->history_mode_last != int(mode));
  if (visible && (!rt->history_overlay_active || mode_changed)) {
    /* Opening edge, or the open card switching between chats and
     * checkpoints: restart animation, scroll, search, selection. A chat
     * search left in place would otherwise filter the checkpoint rows with
     * no field to show it. */
    rt->history_anim_start = now;
    rt->history_scroll_px = 0.0f;
    rt->history_scroll_target = 0.0f;
    rt->history_scroll_last_time = 0.0;
    rt->history_search[0] = '\0';
    rt->history_sel = -1;
    rt->history_confirm_id[0] = '\0';
  }
  rt->history_overlay_active = visible;
  rt->history_mode_last = int(mode);
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

  /* Type-to-filter: case-insensitive substring match on the title. The
   * checkpoints card has no search, so it never filters. */
  blender::Vector<int> filtered;
  for (int i = 0; i < int(entries.size()); i++) {
    if (checkpoints || rt->history_search[0] == '\0' ||
        BLI_strcasestr(entries[i].title, rt->history_search) != nullptr)
    {
      filtered.append(i);
    }
  }

  /* Current chat's session id (marks its row with the accent dot). The
   * checkpoints card has no current row: where the scene is shows as the
   * split between the Turns and Reverted turns sections. */
  char current_id[128] = "";
  if (checkpoints) {
    /* none */
  }
  else if (Scene *scene = CTX_data_scene(C)) {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    PropertyRNA *sid_prop = RNA_struct_find_property(&scene_ptr, "mixie_session_id");
    if (sid_prop) {
      char *value = RNA_property_string_get_alloc(
          &scene_ptr, sid_prop, current_id, sizeof(current_id), nullptr);
      if (value && value != current_id) {
        BLI_strncpy(current_id, value, sizeof(current_id));
        MEM_delete_void(static_cast<void *>(value));
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
  const bool has_search = !store_empty && !checkpoints;
  const float search_h = has_search ? HIST_SEARCH_AREA_HEIGHT * scale : 0.0f;
  /* Checkpoints: a footer explains what a restore does (or why the card is
   * locked). Two short lines, never a modal dialog. */
  const char *footer_lines[3] = {nullptr, nullptr, nullptr};
  int footer_count = 0;
  if (checkpoints) {
    if (notice[0] != '\0') {
      footer_lines[footer_count++] = notice;
    }
    else if (!store_empty) {
      footer_lines[footer_count++] = "Click a turn to revert it and everything after it.";
      footer_lines[footer_count++] = "Reverted turns move below; click one to reapply it.";
      footer_lines[footer_count++] = "Nothing is written to your file.";
    }
  }
  const float footer_line_h = HIST_FOOTER_LINE_HEIGHT * scale;
  const float footer_h = (footer_count > 0) ?
                             footer_count * footer_line_h + HIST_FOOTER_PAD * scale :
                             0.0f;

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
  const float avail_h = float(winy) - HIST_PANEL_TOP_MARGIN * scale - header_h - search_h -
                        footer_h - pad - 24.0f * scale;
  float view_h = std::min(content_h, std::min(avail_h, HIST_LIST_MAX_HEIGHT * scale));
  const bool no_matches = (!store_empty && filtered.is_empty());
  if (store_empty || no_matches) {
    view_h = 64.0f * scale;
  }
  view_h = std::max(view_h, row_h);

  const float panel_h = header_h + search_h + view_h + footer_h + pad;
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
  if (has_search) {
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
    mouse_x = float(win->runtime->eventstate->xy[0] - region->winrct.xmin);
    mouse_y = float(win->runtime->eventstate->xy[1] - region->winrct.ymin);
  }

  const float slide = HIST_OPEN_SLIDE_PX * scale * (1.0f - ease);

  HistoryDrawFrame f;
  f.rt = rt;
  f.entries = &entries;
  f.items = &items;
  f.current_id = current_id;
  f.notice = notice;
  for (int line = 0; line < footer_count; line++) {
    f.footer_lines[line] = footer_lines[line];
  }
  f.footer_count = footer_count;
  f.filtered_count = int(filtered.size());
  f.entries_count = int(entries.size());
  f.checkpoints = checkpoints;
  f.locked = locked;
  f.store_empty = store_empty;
  f.no_matches = no_matches;
  f.font_id = font_id;
  f.title_px = title_px;
  f.meta_px = meta_px;
  f.group_px = group_px;
  f.header_px = header_px;
  f.scale = scale;
  f.pad = pad;
  f.header_h = header_h;
  f.footer_line_h = footer_line_h;
  f.slide = slide;
  f.ease = ease;
  f.panel_x = panel_x;
  f.panel_w = panel_w;
  f.list_top = list_top;
  f.list_bottom = list_bottom;
  f.view_h = view_h;
  f.content_h = content_h;
  f.max_scroll = max_scroll;
  f.mouse_x = mouse_x;
  f.mouse_y = mouse_y;
  f.winx = winx;
  f.winy = winy;
  BLI_rctf_init(&f.panel, panel_x, panel_x + panel_w, panel_bottom - slide, panel_top - slide);

  GPU_blend(GPU_BLEND_ALPHA);
  mixie_chat_history_draw_chrome(f);
  if (has_search) {
    history_draw_search(rt, font_id, title_px, scale, slide, ease);
  }
  if (store_empty || no_matches) {
    mixie_chat_history_draw_empty(f);
    return;
  }
  mixie_chat_history_draw_rows(f);
}

/** \} */
}  // namespace blender
