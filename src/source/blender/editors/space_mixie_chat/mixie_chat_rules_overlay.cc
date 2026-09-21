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
#include "DNA_userdef_types.h"
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


/* -------------------------------------------------------------------- */
/** \name Small Helpers
 * \{ */

static SpaceMixieChat *rules_space_from_area(ScrArea *area)
{
  /* SPACE_AGENT_BUBBLE reuses these callbacks via its layout-compatible
   * spacedata struct (same as the history overlay). */
  if (!area || !area->spacedata.first ||
      (area->spacetype != SPACE_AGENT_BUBBLE))
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
  BLF_disable(font_id, BLF_CLIPPING);
  const uiStyle *style = ui::style_get();
  const int text_px = int((style ? style->widget.points : UI_DEFAULT_TEXT_POINTS) * scale);
  const int hint_px = text_px;
  const int header_px = int(float(text_px) * 1.25f);
  const int meta_px = text_px;

  const float pad = HIST_PANEL_PAD * scale;
  const float header_h = std::max(HIST_HEADER_HEIGHT * scale, float(header_px) * 2.0f);
  const float footer_h = RULES_FOOTER_HEIGHT * scale;
  const float text_pad = RULES_TEXT_PAD * scale;
  const float line_h = std::max(RULES_LINE_HEIGHT * scale, float(text_px) * 1.4f);
  const float card_pad = RULES_CARD_PAD * scale;
  const float card_gap = RULES_CARD_GAP * scale;
  const float submit_h = std::max(RULES_SUBMIT_H * scale, float(text_px) * 1.8f);

  float panel_w = std::min(float(winx) - 2.0f * HIST_PANEL_SIDE_MARGIN * scale,
                           620.0f * scale);
  panel_w = std::max(panel_w, 1.0f);

  /* Active editor (composer) layout. */
  rt->rules_text_px = text_px;
  rt->rules_line_h = line_h;
  rt->rules_wrap_w = panel_w - 2.0f * pad - 2.0f * text_pad;
  const float editor_content_h = std::max(mixie_chat_rules_relayout(rt), line_h);
  /* Reserve the list and actions before growing the editor. A long draft
   * scrolls inside its field instead of pushing the panel off the window. */
  const float list_controls_h = entries.is_empty() ? 2.0f * line_h :
      line_h + (4.0f + RULES_SCOPE_CHIP_H + 2.0f * RULES_CARD_PAD +
                RULES_GROUP_HEADER_H) * scale;
  const float editor_budget = float(winy) - 2.0f * HIST_PANEL_TOP_MARGIN * scale -
      header_h - footer_h - submit_h - 2.0f * text_pad - 30.0f * scale - list_controls_h;
  const float editor_max_h = std::max(line_h,
      std::min(RULES_EDITOR_MAX_LINES * line_h, editor_budget));
  const float editor_inner_h = std::clamp(editor_content_h,
      std::min(RULES_EDITOR_MIN_LINES * line_h, editor_max_h), editor_max_h);
  rt->rules_editor_view_h = editor_inner_h;
  mixie_chat_rules_editor_follow_caret(rt, editor_inner_h);
  const float editor_box_h = editor_inner_h + 2.0f * text_pad;
  const float submit_gap = 6.0f * scale;
  const float composer_h = editor_box_h + submit_gap + submit_h;

  /* Card list layout: wrap every card's text for its height. */
  const float card_w = panel_w - 2.0f * pad;
  const float indent = RULES_TEXT_INDENT * scale;
  const float delete_zone = (HIST_DELETE_SIZE + 12.0f) * scale;
  const float scope_w = 2.0f * (std::max(hist_text_width(RULES_SCOPE_PROJECT, font_id, meta_px),
                                       hist_text_width(RULES_SCOPE_GLOBAL, font_id, meta_px)) +
                               16.0f * scale);
  const float chip_zone = scope_w + 6.0f * scale;
  const float card_wrap_w = card_w - card_pad - indent - chip_zone - delete_zone - card_pad;
  const float toggle_h = RULES_TOGGLE_H * scale;
  /* Left column stacks the toggle with the edit (pencil) button below. */
  const float left_stack_h = toggle_h + (RULES_EDIT_GAP + RULES_EDIT_SIZE) * scale;
  const float scope_stack_h = line_h + (4.0f + RULES_SCOPE_CHIP_H) * scale;
  const float group_h = RULES_GROUP_HEADER_H * scale;

  blender::Vector<blender::Vector<RulesLineSpan>> card_lines;
  blender::Vector<float> card_hs;
  for (const RuleDrawEntry &entry : entries) {
    blender::Vector<RulesLineSpan> lines;
    const int n = mixie_chat_rules_wrap_text(entry.text, font_id, text_px, card_wrap_w, lines);
    const float text_h = float(std::max(n, 1)) * line_h;
    card_hs.append(std::max({text_h, left_stack_h, scope_stack_h}) + 2.0f * card_pad);
    card_lines.append(std::move(lines));
  }

  /* Display list: cards, with "All projects" / "This project" section headers
   * whenever global rules are present (the mirror lists globals first). */
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
        push_header(RULES_SCOPE_GLOBAL);
      }
      if (has_global && i == first_project) {
        push_header(RULES_SCOPE_PROJECT);
      }
      if (!ditems.is_empty() && ditems.last().entry >= 0) {
        list_content_h += card_gap;
      }
      ditems.append({i, nullptr, list_content_h, card_hs[i]});
      list_content_h += card_hs[i];
    }
  }

  const float store_empty_h = line_h * 2.0f;
  const float avail_h = float(winy) - 2.0f * HIST_PANEL_TOP_MARGIN * scale - header_h - composer_h -
                        footer_h - 18.0f * scale;
  float list_view_h = entries.is_empty() ?
                          std::min(store_empty_h, std::max(avail_h, line_h)) :
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
    const float submit_w = hist_text_width("Add Rule", font_id, text_px) + 32.0f * scale;
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
      /* Scope choices beneath their caption, left of the delete X. */
      {
        const float chip_h = RULES_SCOPE_CHIP_H * scale;
        const float chip_xmax = del_cx - del_half - 6.0f * scale;
        const float chip_top = card_top - card_pad - line_h - 4.0f * scale;
        BLI_rctf_init(&hit.scope_bounds,
                      chip_xmax - scope_w,
                      chip_xmax,
                      chip_top - chip_h,
                      chip_top);
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
    mouse_x = float(win->runtime->eventstate->xy[0] - region->winrct.xmin);
    mouse_y = float(win->runtime->eventstate->xy[1] - region->winrct.ymin);
  }

  const float slide = HIST_OPEN_SLIDE_PX * scale * (1.0f - ease);

  GPU_blend(GPU_BLEND_ALPHA);

  const float radius = HIST_PANEL_RADIUS * scale;
  rctf panel;
  BLI_rctf_init(&panel, panel_x, panel_x + panel_w, panel_bottom - slide, panel_top - slide);
  const RulesDrawFrame frame{
      rt,
      region,
      entries,
      ditems,
      card_lines,
      font_id,
      text_px,
      hint_px,
      header_px,
      meta_px,
      winx,
      winy,
      scale,
      pad,
      header_h,
      footer_h,
      text_pad,
      line_h,
      card_pad,
      indent,
      submit_h,
      editor_inner_h,
      panel_x,
      panel_w,
      list_top,
      list_bottom,
      list_view_h,
      list_content_h,
      max_scroll,
      mouse_x,
      mouse_y,
      slide,
      ease,
      radius,
      panel,
  };
  rules_draw_chrome(frame);
  rules_draw_editor(frame);
  rules_draw_rows(frame);
  GPU_blend(GPU_BLEND_NONE);
}
}  // namespace blender
