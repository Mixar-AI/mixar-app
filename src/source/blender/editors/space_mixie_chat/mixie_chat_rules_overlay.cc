/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Project-rules overlay: a Mixar-styled floating card, drawn in
 * screen-space on top of the message area in the same visual family as
 * the past-chats overlay (shared scrim / rounded card / header + close X
 * / open animation / eased scrolling).
 *
 * Layout, top to bottom:
 *   - header: "Project Rules" + count, close X;
 *   - composer/editor box: multiline text editor with a Submit button
 *     ("Add Rule", or "Save" while editing an existing rule in place —
 *     the card's pencil button loads its text here and outlines the card);
 *   - scrollable list of rule cards, grouped under "Global" / "This
 *     File" section headers when global rules exist (the WM mirror lists
 *     globals first): enable/disable toggle pill with an edit (pencil)
 *     button under it, wrapped rule text (dimmed when disabled), a
 *     Global/Project scope chip, arm-to-confirm delete X;
 *   - footer hint.
 *
 * Data is Python-owned (rules_ops.py): the cards come from the
 * WindowManager.mixie_chat_rule_entries mirror, and every mutation
 * dispatches a mixie_chat.rule_* operator — this file never writes the
 * store. Event handling + cursor live in mixie_chat_rules_events.cc;
 * wrap/caret/RNA helpers in mixie_chat_rules_util.cc.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "BLF_api.hh"

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

#include "mixie_chat_intern.hh"
#include "mixie_chat_rules_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static const float COL_ACCENT[4] = CHAT_ACCENT_LIVE;

/* -------------------------------------------------------------------- */
/** \name Small Helpers
 * \{ */

static SpaceMixieChat *rules_space_from_area(ScrArea *area)
{
  /* SPACE_AGENT_BUBBLE reuses these callbacks via its layout-compatible
   * spacedata struct (same as the history overlay). */
  if (!area || !area->spacedata.first ||
      (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE))
  {
    return nullptr;
  }
  return static_cast<SpaceMixieChat *>(area->spacedata.first);
}

static float rules_ease_out_cubic(float t)
{
  t = std::max(0.0f, std::min(1.0f, t));
  const float t1 = t - 1.0f;
  return t1 * t1 * t1 + 1.0f;
}

/** Length-bounded label draw (line spans are not null-terminated). */
static void rules_draw_text_n(int font_id,
                              int font_px,
                              float x,
                              float baseline_y,
                              const float color[4],
                              const char *str,
                              int len)
{
  if (len <= 0) {
    return;
  }
  BLF_size(font_id, float(font_px));
  BLF_color4fv(font_id, color);
  BLF_position(font_id, x, baseline_y, 0.0f);
  BLF_draw(font_id, str, size_t(len));
  /* BLF can leave a different blend mode behind (see hist_draw_label). */
  GPU_blend(GPU_BLEND_ALPHA);
}

/** True when the composer holds something submittable. */
static bool rules_buffer_has_content(const MixieChatRuntime *rt)
{
  for (const char *p = rt->rules_text; *p; p++) {
    if (*p != ' ' && *p != '\n' && *p != '\t') {
      return true;
    }
  }
  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

void mixie_chat_draw_rules_overlay(const bContext *C, ARegion *region)
{
  ScrArea *area = CTX_wm_area(C);
  SpaceMixieChat *smixie = rules_space_from_area(area);
  if (!smixie) {
    return;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  wmWindowManager *wm = CTX_wm_manager(C);
  const bool visible = mixie_chat_rules_read_visible(wm);

  const double now = BLI_time_now_seconds();
  if (visible && !rt->rules_overlay_active) {
    /* Opening edge: fresh composer, reset scroll / edit / anim state. */
    rt->rules_text[0] = '\0';
    rt->rules_cursor = 0;
    rt->rules_editing_index = -1;
    rt->rules_confirm_delete = -1;
    rt->rules_sel_anchor = -1;
    rt->rules_sel_dragging = false;
    rt->rules_anim_start = now;
    rt->rules_scroll_px = 0.0f;
    rt->rules_scroll_target = 0.0f;
    rt->rules_scroll_last_time = 0.0;
    rt->rules_editor_scroll = 0.0f;
    rt->rules_caret_goal_x = -1.0f;
  }
  rt->rules_overlay_active = visible;
  if (!visible) {
    mixie_chat_rules_reset_runtime(rt);
    return;
  }

  /* Smooth list scroll: ease the drawn offset toward the target. */
  float dt = 0.0f;
  if (rt->rules_scroll_last_time > 0.0) {
    dt = float(std::min(now - rt->rules_scroll_last_time, 0.05));
  }
  rt->rules_scroll_last_time = now;
  {
    const float diff = rt->rules_scroll_target - rt->rules_scroll_px;
    if (std::abs(diff) <= 0.25f) {
      rt->rules_scroll_px = rt->rules_scroll_target;
    }
    else {
      const float f = 1.0f - std::exp(-HIST_SCROLL_APPROACH_RATE * dt);
      rt->rules_scroll_px += diff * f;
    }
  }

  const float anim_t = float((now - rt->rules_anim_start) / HIST_OPEN_ANIM_DURATION);
  const float ease = rules_ease_out_cubic(anim_t);
  const bool scroll_settling = (rt->rules_scroll_px != rt->rules_scroll_target);
  mixie_chat_anim_pump_request(C, anim_t < 1.0f || scroll_settling);
  if ((anim_t < 1.0f || scroll_settling) && area) {
    ED_area_tag_redraw(area);
  }

  blender::Vector<RuleDrawEntry> entries;
  mixie_chat_rules_read_entries(wm, entries);
  if (rt->rules_editing_index >= int(entries.size())) {
    rt->rules_editing_index = -1; /* edited card was deleted underneath */
  }
  if (rt->rules_confirm_delete >= int(entries.size())) {
    rt->rules_confirm_delete = -1;
  }

  const float scale = UI_SCALE_FAC;
  const int winx = region->winx;
  const int winy = region->winy;
  const int font_id = BLF_default();
  const int text_px = int(14.0f * scale);
  const int hint_px = int(11.0f * scale);
  const int header_px = int(15.0f * scale);
  const int meta_px = int(12.0f * scale);

  const float pad = HIST_PANEL_PAD * scale;
  const float header_h = HIST_HEADER_HEIGHT * scale;
  const float footer_h = RULES_FOOTER_HEIGHT * scale;
  const float text_pad = RULES_TEXT_PAD * scale;
  const float line_h = RULES_LINE_HEIGHT * scale;
  const float card_pad = RULES_CARD_PAD * scale;
  const float card_gap = RULES_CARD_GAP * scale;
  const float submit_h = RULES_SUBMIT_H * scale;

  float panel_w = std::min(float(winx) - 2.0f * HIST_PANEL_SIDE_MARGIN * scale,
                           HIST_PANEL_MAX_WIDTH * scale);
  panel_w = std::max(panel_w, 160.0f * scale);

  /* Active editor (composer) layout. */
  rt->rules_text_px = text_px;
  rt->rules_line_h = line_h;
  rt->rules_wrap_w = panel_w - 2.0f * pad - 2.0f * text_pad;
  const float editor_content_h = std::max(mixie_chat_rules_relayout(rt), line_h);
  const float editor_inner_h = std::clamp(editor_content_h,
                                          RULES_EDITOR_MIN_LINES * line_h,
                                          RULES_EDITOR_MAX_LINES * line_h);
  rt->rules_editor_view_h = editor_inner_h;
  mixie_chat_rules_editor_follow_caret(rt, editor_inner_h);
  const float editor_box_h = editor_inner_h + 2.0f * text_pad;
  const float submit_gap = 6.0f * scale;
  const float composer_h = editor_box_h + submit_gap + submit_h;

  /* Card list layout: wrap every card's text for its height. */
  const float card_w = panel_w - 2.0f * pad;
  const float indent = RULES_TEXT_INDENT * scale;
  const float delete_zone = (HIST_DELETE_SIZE + 12.0f) * scale;
  const float chip_zone = (RULES_SCOPE_CHIP_W + 6.0f) * scale;
  const float card_wrap_w = card_w - card_pad - indent - chip_zone - delete_zone - card_pad;
  const float toggle_h = RULES_TOGGLE_H * scale;
  /* Left column stacks the toggle with the edit (pencil) button below. */
  const float left_stack_h = toggle_h + (RULES_EDIT_GAP + RULES_EDIT_SIZE) * scale;
  const float group_h = RULES_GROUP_HEADER_H * scale;

  blender::Vector<blender::Vector<RulesLineSpan>> card_lines;
  blender::Vector<float> card_hs;
  for (const RuleDrawEntry &entry : entries) {
    blender::Vector<RulesLineSpan> lines;
    const int n = mixie_chat_rules_wrap_text(entry.text, font_id, text_px, card_wrap_w, lines);
    const float text_h = float(std::max(n, 1)) * line_h;
    card_hs.append(std::max(text_h, left_stack_h) + 2.0f * card_pad);
    card_lines.append(std::move(lines));
  }

  /* Display list: cards, with "Global" / "This File" section headers
   * whenever global rules are present (the mirror lists globals first). */
  struct RulesDisplayItem {
    int entry;         /* index into entries, -1 = section header */
    const char *label; /* header label */
    float top;         /* px from content top */
    float height;
  };
  int first_project = -1;
  bool has_global = false;
  for (int i = 0; i < int(entries.size()); i++) {
    if (entries[i].is_global) {
      has_global = true;
    }
    else if (first_project < 0) {
      first_project = i;
    }
  }
  blender::Vector<RulesDisplayItem> ditems;
  float list_content_h = 0.0f;
  {
    auto push_header = [&](const char *label) {
      if (list_content_h > 0.0f) {
        list_content_h += 4.0f * scale;
      }
      ditems.append({-1, label, list_content_h, group_h});
      list_content_h += group_h;
    };
    for (int i = 0; i < int(entries.size()); i++) {
      if (has_global && i == 0) {
        push_header("Global \xe2\x80\x94 all Mixar files");
      }
      if (has_global && i == first_project) {
        push_header("This File");
      }
      if (!ditems.is_empty() && ditems.last().entry >= 0) {
        list_content_h += card_gap;
      }
      ditems.append({i, nullptr, list_content_h, card_hs[i]});
      list_content_h += card_hs[i];
    }
  }

  const float store_empty_h = 40.0f * scale;
  const float avail_h = float(winy) - HIST_PANEL_TOP_MARGIN * scale - header_h - composer_h -
                        footer_h - pad - 24.0f * scale;
  float list_view_h = entries.is_empty() ?
                          store_empty_h :
                          std::clamp(list_content_h, line_h,
                                     std::min(RULES_LIST_MAX_HEIGHT * scale,
                                              std::max(avail_h, line_h)));
  rt->rules_content_h = list_content_h;
  rt->rules_view_h = list_view_h;

  const float gap_top = 6.0f * scale;
  const float list_gap = 8.0f * scale;
  const float panel_h = header_h + gap_top + composer_h + list_gap + list_view_h + footer_h +
                        4.0f * scale;
  const float panel_x = (float(winx) - panel_w) * 0.5f;
  const float panel_top = float(winy) - HIST_PANEL_TOP_MARGIN * scale;
  const float panel_bottom = panel_top - panel_h;

  const float max_scroll = std::max(0.0f, list_content_h - list_view_h);
  rt->rules_scroll_target = std::clamp(rt->rules_scroll_target, 0.0f, max_scroll);
  rt->rules_scroll_px = std::clamp(rt->rules_scroll_px, 0.0f, max_scroll);

  /* Hit bounds at the FINAL (unslid) position for stable click targets. */
  BLI_rctf_init(&rt->rules_panel_bounds, panel_x, panel_x + panel_w, panel_bottom, panel_top);
  const float editor_top = panel_top - header_h - gap_top;
  BLI_rctf_init(&rt->rules_text_bounds,
                panel_x + pad,
                panel_x + panel_w - pad,
                editor_top - editor_box_h,
                editor_top);
  {
    const float submit_w = 88.0f * scale;
    const float submit_top = editor_top - editor_box_h - submit_gap;
    BLI_rctf_init(&rt->rules_submit_bounds,
                  panel_x + panel_w - pad - submit_w,
                  panel_x + panel_w - pad,
                  submit_top - submit_h,
                  submit_top);
  }
  const float list_top = editor_top - composer_h - list_gap;
  const float list_bottom = list_top - list_view_h;
  BLI_rctf_init(&rt->rules_list_bounds, panel_x, panel_x + panel_w, list_bottom, list_top);
  {
    const float close_half = HIST_CLOSE_SIZE * 0.5f * scale;
    const float close_cx = panel_x + panel_w - pad - close_half;
    const float close_cy = panel_top - header_h * 0.5f;
    BLI_rctf_init(&rt->rules_close_bounds,
                  close_cx - close_half,
                  close_cx + close_half,
                  close_cy - close_half,
                  close_cy + close_half);
  }

  /* Card hit rects, now that the viewport is placed. */
  rt->rules_rows.clear();
  {
    const float row_xmin = panel_x + pad;
    const float row_xmax = panel_x + panel_w - pad;
    for (const RulesDisplayItem &item : ditems) {
      if (item.entry < 0) {
        continue; /* section header — draw-only */
      }
      const int i = item.entry;
      const float card_h = item.height;
      const float card_top = list_top - item.top + rt->rules_scroll_px;
      const float card_bottom = card_top - card_h;

      RuleRowHit hit;
      BLI_rctf_init(&hit.bounds, row_xmin, row_xmax, card_bottom, card_top);
      const float toggle_w = RULES_TOGGLE_W * scale;
      const float toggle_cy = card_top - card_pad - line_h * 0.5f;
      BLI_rctf_init(&hit.toggle_bounds,
                    row_xmin + card_pad,
                    row_xmin + card_pad + toggle_w,
                    toggle_cy - toggle_h * 0.5f,
                    toggle_cy + toggle_h * 0.5f);
      /* Edit (pencil) button, centred under the toggle. */
      {
        const float edit_half = RULES_EDIT_SIZE * 0.5f * scale;
        const float edit_cx = row_xmin + card_pad + toggle_w * 0.5f;
        const float edit_cy = toggle_cy - toggle_h * 0.5f - RULES_EDIT_GAP * scale - edit_half;
        BLI_rctf_init(&hit.edit_bounds,
                      edit_cx - edit_half,
                      edit_cx + edit_half,
                      edit_cy - edit_half,
                      edit_cy + edit_half);
      }
      const float del_half = HIST_DELETE_SIZE * 0.5f * scale;
      const float del_cx = row_xmax - card_pad - del_half;
      const float del_cy = card_top - card_pad - line_h * 0.5f;
      BLI_rctf_init(&hit.delete_bounds,
                    del_cx - del_half,
                    del_cx + del_half,
                    del_cy - del_half,
                    del_cy + del_half);
      /* Scope chip, left of the delete X on the first line. */
      {
        const float chip_h = RULES_SCOPE_CHIP_H * scale;
        const float chip_xmax = del_cx - del_half - 6.0f * scale;
        BLI_rctf_init(&hit.scope_bounds,
                      chip_xmax - RULES_SCOPE_CHIP_W * scale,
                      chip_xmax,
                      del_cy - chip_h * 0.5f,
                      del_cy + chip_h * 0.5f);
      }
      hit.content_top = item.top;
      hit.height = card_h;
      hit.index = i;
      hit.enabled = entries[i].enabled;
      hit.is_global = entries[i].is_global;
      rt->rules_rows.append(hit);
    }
  }

  /* Mouse position for hover (freshest source, like the history overlay). */
  wmWindow *win = CTX_wm_window(C);
  float mouse_x = -1000.0f, mouse_y = -1000.0f;
  if (win) {
    mouse_x = float(win->eventstate->xy[0] - region->winrct.xmin);
    mouse_y = float(win->eventstate->xy[1] - region->winrct.ymin);
  }

  const float slide = HIST_OPEN_SLIDE_PX * scale * (1.0f - ease);

  GPU_blend(GPU_BLEND_ALPHA);

  /* Scrim. */
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

  /* Soft shadow substitute + card (same treatment as history). */
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
  {
    float fill[4] = {HIST_COL_PANEL[0], HIST_COL_PANEL[1], HIST_COL_PANEL[2],
                     HIST_COL_PANEL[3] * ease};
    float outline[4] = {HIST_COL_PANEL_OUTLINE[0], HIST_COL_PANEL_OUTLINE[1],
                        HIST_COL_PANEL_OUTLINE[2], HIST_COL_PANEL_OUTLINE[3] * ease};
    chat_ui_draw_rounded_rect(&panel, radius, fill);
    chat_ui_draw_rounded_rect_outline(&panel, radius, outline, 1.0f);
  }

  /* Header: title + count, "+" add button, close X, divider. */
  {
    const float header_center = panel.ymax - header_h * 0.5f;
    const float baseline = header_center - float(header_px) * 0.35f;

    float title_col[4] = {HIST_COL_HEADER_TEXT[0], HIST_COL_HEADER_TEXT[1],
                          HIST_COL_HEADER_TEXT[2], HIST_COL_HEADER_TEXT[3] * ease};
    hist_draw_label("Project Rules", font_id, header_px, panel.xmin + pad, baseline, title_col);

    if (!entries.is_empty()) {
      char count_buf[16];
      SNPRINTF(count_buf, "%d", int(entries.size()));
      float count_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                            HIST_COL_MUTED[3] * ease};
      const float title_w = hist_text_width("Project Rules", font_id, header_px);
      hist_draw_label(count_buf, font_id, meta_px, panel.xmin + pad + title_w + 8.0f * scale,
                      header_center - float(meta_px) * 0.35f, count_col);
    }

    /* Close X (ring on hover). */
    {
      const bool close_hovered = BLI_rctf_isect_pt(&rt->rules_close_bounds, mouse_x, mouse_y);
      const float close_cx = BLI_rctf_cent_x(&rt->rules_close_bounds);
      const float close_cy = BLI_rctf_cent_y(&rt->rules_close_bounds) - slide;
      if (close_hovered) {
        rctf ring = rt->rules_close_bounds;
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

  /* Composer / editor box. Accent outline while editing an existing rule
   * so the mode is unmistakable. */
  rctf field = rt->rules_text_bounds;
  field.ymin -= slide;
  field.ymax -= slide;
  const bool editing_existing = (rt->rules_editing_index >= 0);
  {
    float bg[4] = {HIST_COL_SEARCH_BG[0], HIST_COL_SEARCH_BG[1], HIST_COL_SEARCH_BG[2],
                   HIST_COL_SEARCH_BG[3] * ease};
    chat_ui_draw_rounded_rect(&field, 8.0f * scale, bg);
    if (editing_existing) {
      float outline[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.55f * ease};
      chat_ui_draw_rounded_rect_outline(&field, 8.0f * scale, outline, 1.0f);
    }
    else {
      float outline[4] = {HIST_COL_SEARCH_OUTLINE[0], HIST_COL_SEARCH_OUTLINE[1],
                          HIST_COL_SEARCH_OUTLINE[2], HIST_COL_SEARCH_OUTLINE[3] * ease};
      chat_ui_draw_rounded_rect_outline(&field, 8.0f * scale, outline, 1.0f);
    }
  }

  const float text_x = field.xmin + text_pad;
  const float text_top = field.ymax - text_pad;
  const float text_bottom = field.ymin + text_pad;

  GPU_scissor(int(std::floor(field.xmin)),
              int(std::floor(text_bottom - 2.0f * scale)),
              int(std::ceil(field.xmax - field.xmin)) + 1,
              int(std::ceil(editor_inner_h + 4.0f * scale)) + 1);

  if (rt->rules_text[0] == '\0') {
    float hint_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                         HIST_COL_MUTED[3] * 0.85f * ease};
    hist_draw_label("Type rules for Mixie to follow in this project\xe2\x80\xa6",
                    font_id, text_px, text_x + 3.0f * scale,
                    text_top - line_h * 0.5f - float(text_px) * 0.35f, hint_col);
  }

  /* Selection range (anchor..cursor, either direction). */
  const int sel_from = (rt->rules_sel_anchor >= 0) ?
                           std::min(rt->rules_sel_anchor, rt->rules_cursor) :
                           -1;
  const int sel_to = (rt->rules_sel_anchor >= 0) ?
                         std::max(rt->rules_sel_anchor, rt->rules_cursor) :
                         -1;
  const bool has_selection = (sel_from >= 0 && sel_to > sel_from);

  float text_col[4] = {HIST_COL_TITLE[0], HIST_COL_TITLE[1], HIST_COL_TITLE[2],
                       HIST_COL_TITLE[3] * ease};
  for (int li = 0; li < int(rt->rules_lines.size()); li++) {
    const RulesLineSpan &span = rt->rules_lines[li];
    const float span_top = text_top - span.top + rt->rules_editor_scroll;
    const float span_bottom = span_top - line_h;
    if (span_bottom > text_top || span_top < text_bottom) {
      continue;
    }
    /* Selection wash: the range's overlap with this line (partial at the
     * edge lines, full in between; a slim marker on empty lines). */
    if (has_selection && sel_to > span.start && sel_from <= span.start + span.len) {
      const int seg_from = std::max(sel_from, span.start);
      const int seg_to = std::min(sel_to, span.start + span.len);
      const float x1 = mixie_chat_rules_offset_to_x(rt, li, seg_from);
      float x2 = mixie_chat_rules_offset_to_x(rt, li, seg_to);
      if (x2 <= x1) {
        x2 = x1 + 4.0f * scale; /* empty line inside the selection */
      }
      rctf sel;
      BLI_rctf_init(&sel,
                    text_x + x1 - 1.0f * scale,
                    text_x + x2 + 1.0f * scale,
                    span_bottom + 1.5f * scale,
                    span_top - 1.5f * scale);
      float sel_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.22f * ease};
      chat_ui_draw_rounded_rect(&sel, 2.0f * scale, sel_col);
    }
    const float baseline = (span_top + span_bottom) * 0.5f - float(text_px) * 0.35f;
    rules_draw_text_n(font_id, text_px, text_x, baseline, text_col,
                      rt->rules_text + span.start, span.len);
  }

  /* Caret. */
  {
    const int caret_line = mixie_chat_rules_line_of_offset(rt, rt->rules_cursor);
    if (caret_line < int(rt->rules_lines.size())) {
      const RulesLineSpan &span = rt->rules_lines[caret_line];
      const float caret_x =
          text_x + mixie_chat_rules_offset_to_x(rt, caret_line, rt->rules_cursor);
      const float span_top = text_top - span.top + rt->rules_editor_scroll;
      const float cy = span_top - line_h * 0.5f;
      const float caret_half_h = float(text_px) * 0.62f;
      rctf caret;
      BLI_rctf_init(&caret, caret_x, caret_x + 1.5f * scale, cy - caret_half_h,
                    cy + caret_half_h);
      float caret_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.9f * ease};
      chat_ui_draw_rounded_rect(&caret, 0.75f * scale, caret_col);
    }
  }

  GPU_scissor(0, 0, region->winx, region->winy);

  /* Submit button ("Add Rule" / "Save"), dimmed when nothing to submit. */
  {
    const bool can_submit = rules_buffer_has_content(rt);
    const bool submit_hovered = can_submit &&
                                BLI_rctf_isect_pt(&rt->rules_submit_bounds, mouse_x, mouse_y);
    rctf btn = rt->rules_submit_bounds;
    btn.ymin -= slide;
    btn.ymax -= slide;
    const float btn_alpha = (can_submit ? (submit_hovered ? 1.0f : 0.85f) : 0.35f) * ease;
    float btn_col[4] = {COL_ACCENT[0] * 0.22f, COL_ACCENT[1] * 0.22f, COL_ACCENT[2] * 0.22f,
                        btn_alpha};
    float btn_outline[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.6f * btn_alpha};
    chat_ui_draw_rounded_rect(&btn, submit_h * 0.5f, btn_col);
    chat_ui_draw_rounded_rect_outline(&btn, submit_h * 0.5f, btn_outline, 1.0f);
    const char *label = editing_existing ? "Save" : "Add Rule";
    float label_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], btn_alpha};
    const float label_w = hist_text_width(label, font_id, meta_px);
    hist_draw_label(label, font_id, meta_px,
                    (btn.xmin + btn.xmax) * 0.5f - label_w * 0.5f,
                    (btn.ymin + btn.ymax) * 0.5f - float(meta_px) * 0.35f, label_col);
  }

  /* Rule cards, scissor-clipped to the list viewport. */
  if (entries.is_empty()) {
    float hint_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                         HIST_COL_MUTED[3] * ease};
    const char *empty_text = "No rules yet — type one above and press Enter";
    const float w = hist_text_width(empty_text, font_id, meta_px);
    const float cx = (panel.xmin + panel.xmax) * 0.5f;
    hist_draw_label(empty_text, font_id, meta_px, cx - w * 0.5f,
                    (list_top + list_bottom) * 0.5f - slide - float(meta_px) * 0.35f, hint_col);
  }
  else {
    GPU_scissor(int(std::floor(panel_x)),
                int(std::floor(list_bottom)),
                int(std::ceil(panel_w)) + 1,
                int(std::ceil(list_view_h)) + 1);

    /* Section headers (draw-only rows of the display list). */
    for (const RulesDisplayItem &item : ditems) {
      if (item.entry >= 0) {
        continue;
      }
      const float item_top = list_top - item.top + rt->rules_scroll_px;
      const float item_bottom = item_top - item.height;
      if (item_bottom > list_top || item_top < list_bottom) {
        continue;
      }
      const float baseline = (item_top + item_bottom) * 0.5f - slide - float(hint_px) * 0.30f;
      float group_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                            HIST_COL_MUTED[3] * 0.9f * ease};
      hist_draw_label(item.label, font_id, hint_px, panel_x + pad + 8.0f * scale, baseline,
                      group_col);
    }

    const bool in_list = BLI_rctf_isect_pt(&rt->rules_list_bounds, mouse_x, mouse_y);
    for (RuleRowHit &hit : rt->rules_rows) {
      hit.is_hovered = in_list && BLI_rctf_isect_pt(&hit.bounds, mouse_x, mouse_y);
      hit.toggle_hovered = hit.is_hovered &&
                           BLI_rctf_isect_pt(&hit.toggle_bounds, mouse_x, mouse_y);
      hit.edit_hovered = hit.is_hovered &&
                         BLI_rctf_isect_pt(&hit.edit_bounds, mouse_x, mouse_y);
      hit.scope_hovered = hit.is_hovered &&
                          BLI_rctf_isect_pt(&hit.scope_bounds, mouse_x, mouse_y);
      hit.delete_hovered = hit.is_hovered &&
                           BLI_rctf_isect_pt(&hit.delete_bounds, mouse_x, mouse_y);

      if (hit.bounds.ymin > list_top || hit.bounds.ymax < list_bottom) {
        continue; /* fully outside the viewport */
      }

      const RuleDrawEntry &entry = entries[hit.index];
      const bool is_editing = (hit.index == rt->rules_editing_index);
      const bool is_armed = (hit.index == rt->rules_confirm_delete);

      rctf card = hit.bounds;
      card.ymin -= slide;
      card.ymax -= slide;

      /* Card background (+hover wash, accent outline while being edited). */
      {
        float bg[4] = {HIST_COL_SEARCH_BG[0], HIST_COL_SEARCH_BG[1], HIST_COL_SEARCH_BG[2],
                       HIST_COL_SEARCH_BG[3] * (hit.is_hovered ? 1.8f : 1.0f) * ease};
        chat_ui_draw_rounded_rect(&card, HIST_ROW_RADIUS * scale, bg);
        if (is_editing) {
          float outline[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2], 0.55f * ease};
          chat_ui_draw_rounded_rect_outline(&card, HIST_ROW_RADIUS * scale, outline, 1.0f);
        }
        else if (is_armed) {
          float outline[4] = {HIST_COL_DELETE_HOVER[0], HIST_COL_DELETE_HOVER[1],
                              HIST_COL_DELETE_HOVER[2], 0.55f * ease};
          chat_ui_draw_rounded_rect_outline(&card, HIST_ROW_RADIUS * scale, outline, 1.0f);
        }
      }

      /* Enable/disable toggle pill: accent track + knob when on. */
      {
        rctf track = hit.toggle_bounds;
        track.ymin -= slide;
        track.ymax -= slide;
        const float knob_r = (track.ymax - track.ymin) * 0.5f - 1.5f * scale;
        float track_col[4];
        if (entry.enabled) {
          track_col[0] = COL_ACCENT[0] * 0.55f;
          track_col[1] = COL_ACCENT[1] * 0.55f;
          track_col[2] = COL_ACCENT[2] * 0.55f;
          track_col[3] = (hit.toggle_hovered ? 1.0f : 0.85f) * ease;
        }
        else {
          track_col[0] = 1.0f;
          track_col[1] = 1.0f;
          track_col[2] = 1.0f;
          track_col[3] = (hit.toggle_hovered ? 0.22f : 0.14f) * ease;
        }
        chat_ui_draw_rounded_rect(&track, (track.ymax - track.ymin) * 0.5f, track_col);

        rctf knob;
        const float cy = (track.ymin + track.ymax) * 0.5f;
        const float kx = entry.enabled ? track.xmax - 1.5f * scale - 2.0f * knob_r :
                                         track.xmin + 1.5f * scale;
        BLI_rctf_init(&knob, kx, kx + 2.0f * knob_r, cy - knob_r, cy + knob_r);
        float knob_col[4] = {0.95f, 0.97f, 1.0f, (entry.enabled ? 1.0f : 0.55f) * ease};
        chat_ui_draw_rounded_rect(&knob, knob_r, knob_col);
      }

      /* Edit (pencil) button under the toggle — the only way into edit
       * mode, so a stray click on the card body can't hijack the
       * composer. Accent glyph while this card is being edited. */
      {
        const float edit_cx = BLI_rctf_cent_x(&hit.edit_bounds);
        const float edit_cy = BLI_rctf_cent_y(&hit.edit_bounds) - slide;
        const float edit_half = RULES_EDIT_SIZE * 0.5f * scale;
        if (hit.edit_hovered) {
          rctf ring = hit.edit_bounds;
          ring.ymin -= slide;
          ring.ymax -= slide;
          float ring_col[4] = {HIST_COL_DELETE_HOVER_BG[0], HIST_COL_DELETE_HOVER_BG[1],
                               HIST_COL_DELETE_HOVER_BG[2], HIST_COL_DELETE_HOVER_BG[3] * ease};
          chat_ui_draw_rounded_rect(&ring, edit_half, ring_col);
        }
        float pen_col[4];
        if (is_editing) {
          pen_col[0] = COL_ACCENT[0];
          pen_col[1] = COL_ACCENT[1];
          pen_col[2] = COL_ACCENT[2];
          pen_col[3] = ease;
        }
        else {
          pen_col[0] = HIST_COL_MUTED[0];
          pen_col[1] = HIST_COL_MUTED[1];
          pen_col[2] = HIST_COL_MUTED[2];
          pen_col[3] = (hit.edit_hovered ? 1.0f : 0.8f) * ease;
        }
        rules_draw_edit_glyph(edit_cx, edit_cy, 4.6f * scale, pen_col, scale);
      }

      /* Scope chip: "Global" / "Project" — clicking flips the rule's
       * scope (mixie_chat.rule_set_scope moves it between the disk store
       * and this file's store). */
      {
        rctf chip = hit.scope_bounds;
        chip.ymin -= slide;
        chip.ymax -= slide;
        const float chip_r = (chip.ymax - chip.ymin) * 0.5f;
        const int chip_px = int(10.0f * scale);
        const char *chip_label = hit.is_global ? "Global" : "Project";
        const float hover_boost = hit.scope_hovered ? 1.0f : 0.75f;
        if (hit.is_global) {
          float fill[4] = {COL_ACCENT[0] * 0.20f, COL_ACCENT[1] * 0.20f,
                           COL_ACCENT[2] * 0.20f, hover_boost * ease};
          float outline[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2],
                              0.55f * hover_boost * ease};
          chat_ui_draw_rounded_rect(&chip, chip_r, fill);
          chat_ui_draw_rounded_rect_outline(&chip, chip_r, outline, 1.0f);
          float label_col[4] = {COL_ACCENT[0], COL_ACCENT[1], COL_ACCENT[2],
                                hover_boost * ease};
          const float lw = hist_text_width(chip_label, font_id, chip_px);
          hist_draw_label(chip_label, font_id, chip_px,
                          (chip.xmin + chip.xmax) * 0.5f - lw * 0.5f,
                          (chip.ymin + chip.ymax) * 0.5f - float(chip_px) * 0.35f, label_col);
        }
        else {
          float fill[4] = {1.0f, 1.0f, 1.0f, 0.05f * hover_boost * ease};
          float outline[4] = {1.0f, 1.0f, 1.0f, 0.10f * hover_boost * ease};
          chat_ui_draw_rounded_rect(&chip, chip_r, fill);
          chat_ui_draw_rounded_rect_outline(&chip, chip_r, outline, 1.0f);
          float label_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                                HIST_COL_MUTED[3] * hover_boost * ease};
          const float lw = hist_text_width(chip_label, font_id, chip_px);
          hist_draw_label(chip_label, font_id, chip_px,
                          (chip.xmin + chip.xmax) * 0.5f - lw * 0.5f,
                          (chip.ymin + chip.ymax) * 0.5f - float(chip_px) * 0.35f, label_col);
        }
      }

      /* Rule text (dimmed when disabled). */
      {
        const float *base_col = entry.enabled ? HIST_COL_TITLE : HIST_COL_MUTED;
        float col[4] = {base_col[0], base_col[1], base_col[2],
                        base_col[3] * (entry.enabled ? 1.0f : 0.8f) * ease};
        const float tx = hit.bounds.xmin + card_pad + indent;
        const float card_text_top = hit.bounds.ymax - card_pad;
        for (const RulesLineSpan &span : card_lines[hit.index]) {
          const float span_top = card_text_top - span.top * line_h - slide;
          const float baseline = span_top - line_h * 0.5f - float(text_px) * 0.35f;
          rules_draw_text_n(font_id, text_px, tx, baseline, col,
                            entry.text + span.start, span.len);
        }
      }

      /* Delete X (arm-to-confirm, like history rows). */
      {
        const float del_cx = BLI_rctf_cent_x(&hit.delete_bounds);
        const float del_cy = BLI_rctf_cent_y(&hit.delete_bounds) - slide;
        const float del_half = HIST_DELETE_SIZE * 0.5f * scale;
        if (is_armed || hit.delete_hovered) {
          rctf ring = hit.delete_bounds;
          ring.ymin -= slide;
          ring.ymax -= slide;
          const float *ring_base = is_armed ? HIST_COL_DELETE_ARMED_BG :
                                              HIST_COL_DELETE_HOVER_BG;
          float ring_col[4] = {ring_base[0], ring_base[1], ring_base[2], ring_base[3] * ease};
          chat_ui_draw_rounded_rect(&ring, del_half, ring_col);
        }
        const float *base_col = (is_armed || hit.delete_hovered) ? HIST_COL_DELETE_HOVER :
                                                                   HIST_COL_DELETE;
        float x_col[4] = {base_col[0], base_col[1], base_col[2], base_col[3] * ease};
        hist_draw_x_glyph(del_cx, del_cy, 4.2f * scale, x_col, scale);
      }
    }

    GPU_scissor(0, 0, region->winx, region->winy);

    /* Slim scrollbar thumb when the list overflows. */
    if (list_content_h > list_view_h + 0.5f) {
      const float track_top = list_top - 2.0f * scale;
      const float track_bottom = list_bottom + 2.0f * scale;
      const float track_h = track_top - track_bottom;
      if (track_h > 8.0f * scale) {
        const float thumb_h = std::max(track_h * list_view_h / list_content_h, 14.0f * scale);
        const float scroll_frac = (max_scroll > 0.0f) ? rt->rules_scroll_px / max_scroll : 0.0f;
        const float thumb_top = track_top - (track_h - thumb_h) * scroll_frac - slide;
        rctf thumb;
        const float thumb_x = panel_x + panel_w - 7.0f * scale;
        BLI_rctf_init(&thumb, thumb_x, thumb_x + 3.5f * scale, thumb_top - thumb_h, thumb_top);
        float thumb_col[4] = {HIST_COL_SCROLL_THUMB[0], HIST_COL_SCROLL_THUMB[1],
                              HIST_COL_SCROLL_THUMB[2], HIST_COL_SCROLL_THUMB[3] * ease};
        chat_ui_draw_rounded_rect(&thumb, 1.75f * scale, thumb_col);
      }
    }
  }

  /* Footer hint. */
  {
    const char *hint = "Enabled rules are sent with the first message of every new chat";
    float hint_col[4] = {HIST_COL_MUTED[0], HIST_COL_MUTED[1], HIST_COL_MUTED[2],
                         HIST_COL_MUTED[3] * 0.9f * ease};
    const float w = hist_text_width(hint, font_id, hint_px);
    const float cx = (panel.xmin + panel.xmax) * 0.5f;
    const float cy = panel.ymin + footer_h * 0.5f;
    hist_draw_label(hint, font_id, hint_px, cx - w * 0.5f, cy - float(hint_px) * 0.35f,
                    hint_col);
  }

  GPU_blend(GPU_BLEND_NONE);

  /* Cursor is owned by mixie_chat_rules_cursor (region cursor callback) —
   * never set it from a draw callback (see the history overlay). */
}

/** \} */
}  // namespace blender
