/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Project-rules overlay — event + cursor half (drawing lives in
 * mixie_chat_rules_overlay.cc).
 *
 * While open the overlay is modal for its region:
 *   - composer editing: printable keys insert at the caret, Shift+Enter
 *     inserts a newline, Tab two spaces, Backspace/Delete remove, arrows
 *     / Home / End navigate (Up/Down keep a goal column across wrapped
 *     lines; Shift+navigation extends the selection), click-drag selects
 *     text, Ctrl+A (Cmd+A on macOS) selects all, Ctrl+C/X copy/cut the
 *     selection (C copies the whole buffer without one), Ctrl+V pastes —
 *     typing or pasting over a selection replaces it, Backspace/Delete
 *     remove it, plain navigation or a click collapses it;
 *   - Enter or the Submit button saves: mixie_chat.rule_add for a new
 *     rule, mixie_chat.rule_update while editing an existing card;
 *   - clicks: a card's toggle pill dispatches rule_toggle, its pencil
 *     button loads the rule into the composer for editing (the card body
 *     itself is inert), its Global/Project chip dispatches
 *     rule_set_scope (moving the rule between the ~/.mixar disk store
 *     and this file's store), its X arms then confirms rule_delete
 *     (history-style), close X / click-away close;
 *   - scroll: wheel + trackpad scroll the card list;
 *   - ESC cancels an in-place edit first, then closes.
 *
 * All data mutations go through the Python rule operators — the local
 * buffer is only the in-flight composer state, so closing mid-typing
 * simply drops an unsubmitted draft (submitted rules are always safe).
 */

#include <algorithm>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_rules_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Edit Helpers
 * \{ */

static float rules_list_max_scroll(const MixieChatRuntime *rt)
{
  return std::max(0.0f, rt->rules_content_h - rt->rules_view_h);
}

static bool rules_buffer_has_content(const MixieChatRuntime *rt)
{
  for (const char *p = rt->rules_text; *p; p++) {
    if (*p != ' ' && *p != '\n' && *p != '\t') {
      return true;
    }
  }
  return false;
}

/** Selection range in ascending order; false when empty or none. */
static bool rules_sel_range(const MixieChatRuntime *rt, int *r_from, int *r_to)
{
  if (rt->rules_sel_anchor < 0) {
    return false;
  }
  *r_from = std::min(rt->rules_sel_anchor, rt->rules_cursor);
  *r_to = std::max(rt->rules_sel_anchor, rt->rules_cursor);
  return *r_to > *r_from;
}

/** Plain navigation / clicks collapse the selection without editing. */
static void rules_drop_selection(ARegion *region, MixieChatRuntime *rt)
{
  if (rt->rules_sel_anchor >= 0) {
    rt->rules_sel_anchor = -1;
    rt->rules_sel_dragging = false;
    ED_region_tag_redraw(region);
  }
}

/** Shift+navigation extends the selection from the caret. */
static void rules_sel_extend_begin(MixieChatRuntime *rt)
{
  if (rt->rules_sel_anchor < 0) {
    rt->rules_sel_anchor = rt->rules_cursor;
  }
}

/** Remove [from, to) without relayout (callers run rules_after_edit). */
static void rules_remove_raw(MixieChatRuntime *rt, int from, int to)
{
  const int total = int(strlen(rt->rules_text));
  from = std::clamp(from, 0, total);
  to = std::clamp(to, from, total);
  if (to <= from) {
    return;
  }
  memmove(rt->rules_text + from, rt->rules_text + to, size_t(total - to) + 1);
  rt->rules_cursor = from;
}

/** Byte offset under a mouse position inside the editor box. */
static int rules_offset_from_mouse(const MixieChatRuntime *rt, float mx, float my)
{
  if (rt->rules_lines.is_empty()) {
    return 0;
  }
  const float scale = UI_SCALE_FAC;
  const float text_pad = RULES_TEXT_PAD * scale;
  const float text_top = rt->rules_text_bounds.ymax - text_pad;
  const float text_x = rt->rules_text_bounds.xmin + text_pad;
  const float content_y = (text_top - my) + rt->rules_editor_scroll;
  const int line = std::clamp(int(content_y / std::max(rt->rules_line_h, 1.0f)), 0,
                              int(rt->rules_lines.size()) - 1);
  return mixie_chat_rules_x_to_offset(rt, line, mx - text_x);
}

/** Reset the composer to empty new-rule mode. */
static void rules_reset_composer(MixieChatRuntime *rt)
{
  rt->rules_editing_index = -1;
  rt->rules_text[0] = '\0';
  rt->rules_cursor = 0;
  rt->rules_sel_anchor = -1;
  rt->rules_sel_dragging = false;
  rt->rules_editor_scroll = 0.0f;
  rt->rules_caret_goal_x = -1.0f;
  mixie_chat_rules_relayout(rt);
}

/** Relayout + caret-follow after any local text change (data is only
 * persisted on submit — see rules_submit). */
static void rules_after_edit(ARegion *region, MixieChatRuntime *rt)
{
  mixie_chat_rules_relayout(rt);
  rt->rules_caret_goal_x = -1.0f;
  mixie_chat_rules_editor_follow_caret(rt, rt->rules_editor_view_h);
  ED_region_tag_redraw(region);
}

/** Insert `len` bytes at the caret, capacity permitting. */
static void rules_insert(ARegion *region, MixieChatRuntime *rt, const char *str, int len)
{
  /* Typing/pasting over a selection replaces it. */
  int sel_from = 0, sel_to = 0;
  if (rules_sel_range(rt, &sel_from, &sel_to)) {
    rules_remove_raw(rt, sel_from, sel_to);
  }
  rt->rules_sel_anchor = -1;
  rt->rules_sel_dragging = false;
  const int total = int(strlen(rt->rules_text));
  const int cap = int(sizeof(rt->rules_text)) - 1;
  const int room = std::min(len, cap - total);
  if (room <= 0) {
    return;
  }
  /* Never split a UTF-8 sequence at the capacity boundary: walk whole
   * characters forward and keep only the ones that fit completely. */
  int fit = 0;
  while (fit < room) {
    const int char_len = std::max(1, BLI_str_utf8_size_safe(str + fit));
    if (fit + char_len > room) {
      break;
    }
    fit += char_len;
  }
  if (fit <= 0) {
    return;
  }
  const int cursor = std::clamp(rt->rules_cursor, 0, total);
  memmove(rt->rules_text + cursor + fit, rt->rules_text + cursor, size_t(total - cursor) + 1);
  memcpy(rt->rules_text + cursor, str, size_t(fit));
  rt->rules_cursor = cursor + fit;
  rules_after_edit(region, rt);
}

/** Delete bytes in [from, to) and place the caret at `from`. */
static void rules_delete_range(ARegion *region, MixieChatRuntime *rt, int from, int to)
{
  const int before = int(strlen(rt->rules_text));
  rules_remove_raw(rt, from, to);
  rt->rules_sel_anchor = -1;
  rt->rules_sel_dragging = false;
  if (int(strlen(rt->rules_text)) != before) {
    rules_after_edit(region, rt);
  }
}

/** Paste from the system clipboard ('\r' stripped so CRLF becomes '\n'). */
static void rules_paste(ARegion *region, MixieChatRuntime *rt)
{
  int buf_len = 0;
  char *buf = WM_clipboard_text_get(false, true, &buf_len);
  if (!buf) {
    return;
  }
  int out = 0;
  for (int i = 0; i < buf_len && buf[i] != '\0'; i++) {
    if (buf[i] != '\r') {
      buf[out++] = (buf[i] == '\t') ? ' ' : buf[i];
    }
  }
  buf[out] = '\0';
  if (out > 0) {
    rules_insert(region, rt, buf, out);
  }
  MEM_freeN(buf);
}

/** Move the caret one visual line up/down, preserving the goal column. */
static void rules_caret_vertical(ARegion *region, MixieChatRuntime *rt, bool down)
{
  const int line_count = int(rt->rules_lines.size());
  if (line_count == 0) {
    return;
  }
  const int line = mixie_chat_rules_line_of_offset(rt, rt->rules_cursor);
  if (rt->rules_caret_goal_x < 0.0f) {
    rt->rules_caret_goal_x = mixie_chat_rules_offset_to_x(rt, line, rt->rules_cursor);
  }
  const int target = std::clamp(line + (down ? 1 : -1), 0, line_count - 1);
  if (target != line) {
    rt->rules_cursor = mixie_chat_rules_x_to_offset(rt, target, rt->rules_caret_goal_x);
    mixie_chat_rules_editor_follow_caret(rt, rt->rules_editor_view_h);
    ED_region_tag_redraw(region);
  }
}

/** Submit the composer: add a new rule or save the card being edited. */
static void rules_submit(bContext *C, ARegion *region, MixieChatRuntime *rt)
{
  if (!rules_buffer_has_content(rt)) {
    return;
  }
  if (rt->rules_editing_index >= 0) {
    mixie_chat_rules_dispatch_op(
        C, region, "mixie_chat.rule_update", rt->rules_editing_index, rt->rules_text);
  }
  else {
    mixie_chat_rules_dispatch_op(C, region, "mixie_chat.rule_add", -1, rt->rules_text);
  }
  rules_reset_composer(rt);
  ED_region_tag_redraw(region);
}

/** Load a card's text into the composer for in-place editing. */
static void rules_begin_edit(bContext *C, MixieChatRuntime *rt, int index)
{
  blender::Vector<RuleDrawEntry> entries;
  mixie_chat_rules_read_entries(CTX_wm_manager(C), entries);
  if (index < 0 || index >= int(entries.size())) {
    return;
  }
  rt->rules_editing_index = index;
  BLI_strncpy_utf8(rt->rules_text, entries[index].text, sizeof(rt->rules_text));
  rt->rules_cursor = int(strlen(rt->rules_text));
  rt->rules_sel_anchor = -1;
  rt->rules_sel_dragging = false;
  rt->rules_editor_scroll = 0.0f;
  rt->rules_caret_goal_x = -1.0f;
  mixie_chat_rules_relayout(rt);
  mixie_chat_rules_editor_follow_caret(rt, rt->rules_editor_view_h);
}

/** Arm-to-confirm delete of a card (first click arms, second deletes). */
static void rules_arm_or_delete(bContext *C, ARegion *region, MixieChatRuntime *rt, int index)
{
  if (rt->rules_confirm_delete == index) {
    rt->rules_confirm_delete = -1;
    if (rt->rules_editing_index == index) {
      rules_reset_composer(rt);
    }
    else if (rt->rules_editing_index > index) {
      rt->rules_editing_index--; /* indices shift down past the deletion */
    }
    mixie_chat_rules_dispatch_op(C, region, "mixie_chat.rule_delete", index, nullptr);
  }
  else {
    rt->rules_confirm_delete = index;
    ED_region_tag_redraw(region);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hover (region cursor callback)
 * \{ */

bool mixie_chat_rules_cursor(
    wmWindow *win, MixieChatRuntime *rt, ARegion *region, float mouse_x, float mouse_y)
{
  if (!rt->rules_overlay_active) {
    return false;
  }
  bool needs_redraw = false;
  bool any_button = false;

  const bool close_hovered = BLI_rctf_isect_pt(&rt->rules_close_bounds, mouse_x, mouse_y);
  needs_redraw |= (close_hovered != rt->rules_close_hovered);
  rt->rules_close_hovered = close_hovered;

  const bool submit_hovered = BLI_rctf_isect_pt(&rt->rules_submit_bounds, mouse_x, mouse_y);
  needs_redraw |= (submit_hovered != rt->rules_submit_hovered);
  rt->rules_submit_hovered = submit_hovered;

  any_button = close_hovered || submit_hovered;

  const bool in_list = BLI_rctf_isect_pt(&rt->rules_list_bounds, mouse_x, mouse_y);
  for (RuleRowHit &row : rt->rules_rows) {
    const bool was_hovered = row.is_hovered;
    const bool was_toggle = row.toggle_hovered;
    const bool was_edit = row.edit_hovered;
    const bool was_scope = row.scope_hovered;
    const bool was_delete = row.delete_hovered;
    row.is_hovered = in_list && BLI_rctf_isect_pt(&row.bounds, mouse_x, mouse_y);
    row.toggle_hovered = row.is_hovered &&
                         BLI_rctf_isect_pt(&row.toggle_bounds, mouse_x, mouse_y);
    row.edit_hovered = row.is_hovered &&
                       BLI_rctf_isect_pt(&row.edit_bounds, mouse_x, mouse_y);
    row.scope_hovered = row.is_hovered &&
                        BLI_rctf_isect_pt(&row.scope_bounds, mouse_x, mouse_y);
    row.delete_hovered = row.is_hovered &&
                         BLI_rctf_isect_pt(&row.delete_bounds, mouse_x, mouse_y);
    needs_redraw |= (was_hovered != row.is_hovered) || (was_toggle != row.toggle_hovered) ||
                    (was_edit != row.edit_hovered) || (was_scope != row.scope_hovered) ||
                    (was_delete != row.delete_hovered);
    /* Only the actual buttons show the hand cursor — the card body is
     * inert (editing goes through the pencil). */
    any_button |= row.toggle_hovered || row.edit_hovered || row.scope_hovered ||
                  row.delete_hovered;
  }

  if (needs_redraw) {
    ED_region_tag_redraw(region);
  }
  const bool over_text = BLI_rctf_isect_pt(&rt->rules_text_bounds, mouse_x, mouse_y);
  WM_cursor_set(win,
                over_text ? WM_CURSOR_TEXT_EDIT :
                            (any_button ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT));
  return true; /* Overlay is modal — suppress hover on elements behind it. */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Keyboard
 * \{ */

static bool rules_handle_key(bContext *C,
                             ARegion *region,
                             MixieChatRuntime *rt,
                             const wmEvent *event)
{
  const int total = int(strlen(rt->rules_text));
  const bool ctrl = (event->modifier & (KM_CTRL | KM_OSKEY)) != 0;
  const bool shift = (event->modifier & KM_SHIFT) != 0;

  if (ctrl) {
    int sel_from = 0, sel_to = 0;
    const bool has_sel = rules_sel_range(rt, &sel_from, &sel_to);
    switch (event->type) {
      case EVT_VKEY:
        rules_paste(region, rt);
        return true;
      case EVT_CKEY:
        /* Copy the selection, or the whole buffer without one. */
        if (has_sel) {
          char tmp[sizeof(rt->rules_text)];
          memcpy(tmp, rt->rules_text + sel_from, size_t(sel_to - sel_from));
          tmp[sel_to - sel_from] = '\0';
          WM_clipboard_text_set(tmp, false);
        }
        else if (total > 0) {
          WM_clipboard_text_set(rt->rules_text, false);
        }
        return true;
      case EVT_XKEY:
        /* Cut the selection. */
        if (has_sel) {
          char tmp[sizeof(rt->rules_text)];
          memcpy(tmp, rt->rules_text + sel_from, size_t(sel_to - sel_from));
          tmp[sel_to - sel_from] = '\0';
          WM_clipboard_text_set(tmp, false);
          rules_delete_range(region, rt, sel_from, sel_to);
        }
        return true;
      case EVT_AKEY:
        /* Select all (Ctrl+A on Windows/Linux, Cmd+A on macOS — the ctrl
         * mask above covers both). */
        if (total > 0) {
          rt->rules_sel_anchor = 0;
          rt->rules_cursor = total;
          rt->rules_caret_goal_x = -1.0f;
          ED_region_tag_redraw(region);
        }
        return true;
      default:
        return true; /* Consume other shortcuts — the overlay is modal. */
    }
  }

  switch (event->type) {
    case EVT_ESCKEY:
      /* ESC: cancel an in-place edit back to the composer, then close.
       * Submitted rules are always persisted; only an unsubmitted draft
       * is dropped. */
      if (rt->rules_editing_index >= 0) {
        rules_reset_composer(rt);
        ED_region_tag_redraw(region);
      }
      else {
        mixie_chat_rules_set_visible(C, false);
      }
      return true;

    case EVT_RETKEY:
    case EVT_PADENTER:
      /* Enter submits the rule; Shift+Enter inserts a newline (same
       * convention as the chat composer). */
      if (shift) {
        rules_insert(region, rt, "\n", 1);
      }
      else {
        rules_submit(C, region, rt);
      }
      return true;

    case EVT_TABKEY:
      rules_insert(region, rt, "  ", 2);
      return true;

    case EVT_BACKSPACEKEY: {
      int sel_from = 0, sel_to = 0;
      if (rules_sel_range(rt, &sel_from, &sel_to)) {
        rules_delete_range(region, rt, sel_from, sel_to);
      }
      else if (rt->rules_cursor > 0) {
        const char *prev = BLI_str_find_prev_char_utf8(rt->rules_text + rt->rules_cursor,
                                                       rt->rules_text);
        rules_delete_range(region, rt, int(prev - rt->rules_text), rt->rules_cursor);
      }
      return true;
    }

    case EVT_DELKEY: {
      int sel_from = 0, sel_to = 0;
      if (rules_sel_range(rt, &sel_from, &sel_to)) {
        rules_delete_range(region, rt, sel_from, sel_to);
      }
      else if (rt->rules_cursor < total) {
        const int char_len = std::max(
            1, BLI_str_utf8_size_safe(rt->rules_text + rt->rules_cursor));
        rules_delete_range(region, rt, rt->rules_cursor, rt->rules_cursor + char_len);
      }
      return true;
    }

    case EVT_LEFTARROWKEY:
    case EVT_RIGHTARROWKEY: {
      const bool right = (event->type == EVT_RIGHTARROWKEY);
      int sel_from = 0, sel_to = 0;
      if (!shift && rules_sel_range(rt, &sel_from, &sel_to)) {
        /* A plain arrow collapses the selection to its edge. */
        rt->rules_cursor = right ? sel_to : sel_from;
        rules_drop_selection(region, rt);
      }
      else {
        if (shift) {
          rules_sel_extend_begin(rt);
        }
        else {
          rules_drop_selection(region, rt);
        }
        if (right && rt->rules_cursor < total) {
          rt->rules_cursor += std::max(
              1, BLI_str_utf8_size_safe(rt->rules_text + rt->rules_cursor));
        }
        else if (!right && rt->rules_cursor > 0) {
          const char *prev = BLI_str_find_prev_char_utf8(rt->rules_text + rt->rules_cursor,
                                                         rt->rules_text);
          rt->rules_cursor = int(prev - rt->rules_text);
        }
      }
      rt->rules_caret_goal_x = -1.0f;
      mixie_chat_rules_editor_follow_caret(rt, rt->rules_editor_view_h);
      ED_region_tag_redraw(region);
      return true;
    }

    case EVT_UPARROWKEY:
    case EVT_DOWNARROWKEY:
      if (shift) {
        rules_sel_extend_begin(rt);
      }
      else {
        rules_drop_selection(region, rt);
      }
      rules_caret_vertical(region, rt, event->type == EVT_DOWNARROWKEY);
      return true;

    case EVT_HOMEKEY:
    case EVT_ENDKEY: {
      if (shift) {
        rules_sel_extend_begin(rt);
      }
      else {
        rules_drop_selection(region, rt);
      }
      const int line = mixie_chat_rules_line_of_offset(rt, rt->rules_cursor);
      if (line < int(rt->rules_lines.size())) {
        const RulesLineSpan &span = rt->rules_lines[line];
        rt->rules_cursor = (event->type == EVT_HOMEKEY) ? span.start : span.start + span.len;
        rt->rules_caret_goal_x = -1.0f;
        mixie_chat_rules_editor_follow_caret(rt, rt->rules_editor_view_h);
        ED_region_tag_redraw(region);
      }
      return true;
    }

    case EVT_PAGEUPKEY:
    case EVT_PAGEDOWNKEY: {
      const float dir = (event->type == EVT_PAGEDOWNKEY) ? 1.0f : -1.0f;
      rt->rules_scroll_target = std::clamp(
          rt->rules_scroll_target + dir * rt->rules_view_h, 0.0f, rules_list_max_scroll(rt));
      ED_region_tag_redraw(region);
      return true;
    }

    default:
      break;
  }

  /* Printable input inserts at the caret. */
  if (event->utf8_buf[0] != '\0' && uchar(event->utf8_buf[0]) >= 32 &&
      (event->modifier & KM_ALT) == 0)
  {
    rules_insert(region, rt, event->utf8_buf,
                 std::max(1, BLI_str_utf8_size_safe(event->utf8_buf)));
  }
  return true; /* Modal: no key press leaks to the chat behind the scrim. */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Events (called first from the region UI handler)
 * \{ */

bool mixie_chat_rules_handle_event(bContext *C, const wmEvent *event)
{
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  if (!area || !region || !area->spacedata.first ||
      (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE))
  {
    return false;
  }
  SpaceMixieChat *smixie = static_cast<SpaceMixieChat *>(area->spacedata.first);
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (!rt->rules_overlay_active) {
    return false;
  }

  if (ISKEYBOARD(event->type)) {
    if (event->val == KM_PRESS) {
      return rules_handle_key(C, region, rt, event);
    }
    return true; /* Consume releases too — the overlay is modal. */
  }

  const float mx = float(event->mval[0]);
  const float my = float(event->mval[1]);
  const bool inside_panel = BLI_rctf_isect_pt(&rt->rules_panel_bounds, mx, my);
  const bool scrollable = (rt->rules_content_h > rt->rules_view_h + 0.5f);

  /* Drag-selection: mouse-move extends from the press anchor until the
   * button releases (positions outside the box clamp to the nearest
   * line/edge, so dragging past an edge selects to it). */
  if (event->type == MOUSEMOVE) {
    if (rt->rules_sel_dragging) {
      const int offset = rules_offset_from_mouse(rt, mx, my);
      if (offset != rt->rules_cursor) {
        rt->rules_cursor = offset;
        rt->rules_caret_goal_x = -1.0f;
        mixie_chat_rules_editor_follow_caret(rt, rt->rules_editor_view_h);
        ED_region_tag_redraw(region);
      }
      return true;
    }
    return false; /* hover is the cursor callback's job */
  }

  if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
    if (rt->rules_sel_dragging) {
      rt->rules_sel_dragging = false;
      if (rt->rules_sel_anchor == rt->rules_cursor) {
        rt->rules_sel_anchor = -1; /* plain click — no selection */
      }
      return true;
    }
    return false;
  }

  if (event->type == WHEELUPMOUSE || event->type == WHEELDOWNMOUSE) {
    if (inside_panel && scrollable) {
      const float step = HIST_WHEEL_STEP_PX * UI_SCALE_FAC;
      rt->rules_scroll_target += (event->type == WHEELDOWNMOUSE) ? step : -step;
      rt->rules_scroll_target = std::clamp(
          rt->rules_scroll_target, 0.0f, rules_list_max_scroll(rt));
      ED_region_tag_redraw(region);
    }
    return true;
  }

  if (event->type == MOUSEPAN) {
    if (inside_panel && scrollable) {
      rt->rules_scroll_target += float(event->xy[1] - event->prev_xy[1]);
      rt->rules_scroll_target = std::clamp(
          rt->rules_scroll_target, 0.0f, rules_list_max_scroll(rt));
      ED_region_tag_redraw(region);
    }
    return true;
  }

  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    if (!inside_panel) {
      /* Click-away closes and consumes the click. */
      mixie_chat_rules_set_visible(C, false);
      return true;
    }

    if (BLI_rctf_isect_pt(&rt->rules_close_bounds, mx, my)) {
      mixie_chat_rules_set_visible(C, false);
      return true;
    }

    if (BLI_rctf_isect_pt(&rt->rules_submit_bounds, mx, my)) {
      rules_submit(C, region, rt);
      return true;
    }

    if (BLI_rctf_isect_pt(&rt->rules_text_bounds, mx, my) && !rt->rules_lines.is_empty()) {
      /* Caret placement + selection anchor: dragging from here extends
       * the selection until the button releases. */
      const int offset = rules_offset_from_mouse(rt, mx, my);
      rt->rules_cursor = offset;
      rt->rules_sel_anchor = offset;
      rt->rules_sel_dragging = true;
      rt->rules_caret_goal_x = -1.0f;
      ED_region_tag_redraw(region);
      return true;
    }

    if (BLI_rctf_isect_pt(&rt->rules_list_bounds, mx, my)) {
      for (const RuleRowHit &row : rt->rules_rows) {
        if (!BLI_rctf_isect_pt(&row.bounds, mx, my)) {
          continue;
        }
        if (BLI_rctf_isect_pt(&row.toggle_bounds, mx, my)) {
          rt->rules_confirm_delete = -1;
          mixie_chat_rules_dispatch_op(
              C, region, "mixie_chat.rule_toggle", row.index, nullptr);
        }
        else if (BLI_rctf_isect_pt(&row.edit_bounds, mx, my)) {
          /* Pencil is the only way into edit mode — a stray click on the
           * card body must not hijack the composer. */
          rt->rules_confirm_delete = -1;
          rules_begin_edit(C, rt, row.index);
          ED_region_tag_redraw(region);
        }
        else if (BLI_rctf_isect_pt(&row.scope_bounds, mx, my)) {
          /* Scope chip: flip global <-> this-file. The move reorders the
           * unified list, so cancel any in-place edit first — its index
           * would go stale. */
          rt->rules_confirm_delete = -1;
          if (rt->rules_editing_index >= 0) {
            rules_reset_composer(rt);
          }
          mixie_chat_rules_dispatch_op(
              C, region, "mixie_chat.rule_set_scope", row.index, nullptr);
        }
        else if (BLI_rctf_isect_pt(&row.delete_bounds, mx, my)) {
          rules_arm_or_delete(C, region, rt, row.index);
        }
        else if (rt->rules_confirm_delete >= 0) {
          /* Card body: inert — just disarm a pending delete. */
          rt->rules_confirm_delete = -1;
          ED_region_tag_redraw(region);
        }
        return true;
      }
    }

    if (rt->rules_confirm_delete >= 0) {
      /* Click on blank panel space disarms a pending delete. */
      rt->rules_confirm_delete = -1;
      ED_region_tag_redraw(region);
    }
    /* Clicks inside the panel never fall through to the chat behind it. */
    return true;
  }

  return false;
}

/** \} */
}  // namespace blender
