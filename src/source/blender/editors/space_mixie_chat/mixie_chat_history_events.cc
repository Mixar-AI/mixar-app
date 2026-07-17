/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Past-chats overlay — event + cursor half (drawing lives in
 * mixie_chat_history_overlay.cc).
 *
 * While open the overlay is modal for its region:
 *   - clicks: row open, arm-to-confirm delete (first X click arms the
 *     row — red "Delete?" — second X click deletes), header close X,
 *     click-away closes;
 *   - scroll: wheel + trackpad pan write history_scroll_target in pixels,
 *     the draw eases toward it (smooth scrolling);
 *   - keys: every printable key edits the search query (the field is
 *     always focused), Backspace deletes, Up/Down move the keyboard
 *     selection (auto-scrolled into view), Enter opens the selection (or
 *     the first match while searching), Delete arms/confirms deleting the
 *     selection, Page Up/Down scroll a viewport, ESC clears the armed
 *     delete, then the search, then closes.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

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

#include "mixie_chat_history_intern.hh"
#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Helpers
 * \{ */

/** Row index under the mouse, or -1. `r_over_delete` reports the X hit.
 * Rows scrolled out of the list viewport never hit. */
static int history_hit_row(const MixieChatRuntime *rt, float mx, float my, bool *r_over_delete)
{
  *r_over_delete = false;
  if (!BLI_rctf_isect_pt(&rt->history_list_bounds, mx, my)) {
    return -1;
  }
  for (int i = 0; i < int(rt->history_rows.size()); i++) {
    const HistoryRowHit &row = rt->history_rows[i];
    if (row.bounds.xmax <= row.bounds.xmin) {
      continue;
    }
    if (BLI_rctf_isect_pt(&row.bounds, mx, my)) {
      *r_over_delete = BLI_rctf_isect_pt(&row.delete_bounds, mx, my);
      return i;
    }
  }
  return -1;
}

static float history_max_scroll(const MixieChatRuntime *rt)
{
  return std::max(0.0f, rt->history_content_h - rt->history_view_h);
}

/** Search query changed: selection and armed delete no longer refer to
 * the same row set, and the (shorter) list should show from the top. */
static void history_on_search_edit(MixieChatRuntime *rt)
{
  rt->history_sel = -1;
  rt->history_confirm_id[0] = '\0';
  rt->history_scroll_target = 0.0f;
}

/** Scroll history_scroll_target the minimum amount that brings the
 * selected row fully into the list viewport. */
static void history_scroll_selection_into_view(MixieChatRuntime *rt)
{
  if (rt->history_sel < 0 || rt->history_sel >= int(rt->history_rows.size())) {
    return;
  }
  const HistoryRowHit &row = rt->history_rows[rt->history_sel];
  const float row_h = row.bounds.ymax - row.bounds.ymin;
  const float top = row.content_top;
  const float bottom = top + row_h;
  if (top < rt->history_scroll_target) {
    rt->history_scroll_target = top;
  }
  else if (bottom > rt->history_scroll_target + rt->history_view_h) {
    rt->history_scroll_target = bottom - rt->history_view_h;
  }
  rt->history_scroll_target = std::clamp(rt->history_scroll_target, 0.0f, history_max_scroll(rt));
}

/** Open a row's session and close the overlay. */
static void history_open_row(bContext *C, ARegion *region, MixieChatRuntime *rt, int index)
{
  if (index < 0 || index >= int(rt->history_rows.size())) {
    return;
  }
  /* Copy the id out — the dispatched operator redraws/rebuilds rows. */
  char session_id[128];
  BLI_strncpy(session_id, rt->history_rows[index].session_id, sizeof(session_id));
  rt->history_confirm_id[0] = '\0';
  mixie_chat_history_dispatch_session_op(
      C, region, "mixie_chat.open_history_session", session_id);
  mixie_chat_history_set_visible(C, false);
}

/** Arm-to-confirm delete of a row: first call arms (red "Delete?"),
 * second call on the same row dispatches the delete operator. */
static void history_arm_or_delete_row(bContext *C, ARegion *region, MixieChatRuntime *rt, int index)
{
  if (index < 0 || index >= int(rt->history_rows.size())) {
    return;
  }
  char session_id[128];
  BLI_strncpy(session_id, rt->history_rows[index].session_id, sizeof(session_id));
  if (STREQ(rt->history_confirm_id, session_id)) {
    rt->history_confirm_id[0] = '\0';
    mixie_chat_history_dispatch_session_op(
        C, region, "mixie_chat.delete_history_session", session_id);
  }
  else {
    BLI_strncpy(rt->history_confirm_id, session_id, sizeof(rt->history_confirm_id));
    ED_region_tag_redraw(region);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hover (region cursor callback)
 * \{ */

bool mixie_chat_history_cursor(
    wmWindow *win, MixieChatRuntime *rt, ARegion *region, float mouse_x, float mouse_y)
{
  if (!rt->history_overlay_active) {
    return false;
  }

  bool needs_redraw = false;
  bool any_hovered = false;
  const bool in_list = BLI_rctf_isect_pt(&rt->history_list_bounds, mouse_x, mouse_y);
  for (HistoryRowHit &row : rt->history_rows) {
    const bool was_hovered = row.is_hovered;
    const bool was_delete = row.delete_hovered;
    row.is_hovered = in_list && BLI_rctf_isect_pt(&row.bounds, mouse_x, mouse_y);
    row.delete_hovered = row.is_hovered &&
                         BLI_rctf_isect_pt(&row.delete_bounds, mouse_x, mouse_y);
    needs_redraw |= (was_hovered != row.is_hovered) || (was_delete != row.delete_hovered);
    any_hovered |= row.is_hovered;
  }

  const bool close_hovered = BLI_rctf_isect_pt(&rt->history_close_bounds, mouse_x, mouse_y);
  needs_redraw |= (close_hovered != rt->history_close_hovered);
  rt->history_close_hovered = close_hovered;

  if (needs_redraw) {
    ED_region_tag_redraw(region);
  }
  const bool over_search = BLI_rctf_isect_pt(&rt->history_search_bounds, mouse_x, mouse_y);
  WM_cursor_set(win,
                over_search ? WM_CURSOR_TEXT_EDIT :
                              ((any_hovered || close_hovered) ? WM_CURSOR_HAND :
                                                                WM_CURSOR_DEFAULT));
  return true; /* Overlay is modal — suppress hover on elements behind it. */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Keyboard
 * \{ */

static bool history_handle_key(bContext *C,
                               ARegion *region,
                               MixieChatRuntime *rt,
                               const wmEvent *event)
{
  const int row_count = int(rt->history_rows.size());

  switch (event->type) {
    case EVT_ESCKEY:
      /* ESC: disarm a pending delete, then clear the search, then close. */
      if (rt->history_confirm_id[0] != '\0') {
        rt->history_confirm_id[0] = '\0';
        ED_region_tag_redraw(region);
      }
      else if (rt->history_search[0] != '\0') {
        rt->history_search[0] = '\0';
        history_on_search_edit(rt);
        ED_region_tag_redraw(region);
      }
      else {
        mixie_chat_history_set_visible(C, false);
      }
      return true;

    case EVT_RETKEY:
    case EVT_PADENTER: {
      /* Enter opens the keyboard selection; while searching with no
       * selection it opens the first (best) match. */
      int index = rt->history_sel;
      if (index < 0 && rt->history_search[0] != '\0' && row_count > 0) {
        index = 0;
      }
      history_open_row(C, region, rt, index);
      return true;
    }

    case EVT_UPARROWKEY:
    case EVT_DOWNARROWKEY: {
      if (row_count == 0) {
        return true;
      }
      const bool down = (event->type == EVT_DOWNARROWKEY);
      if (rt->history_sel < 0) {
        rt->history_sel = down ? 0 : row_count - 1;
      }
      else {
        rt->history_sel = std::clamp(rt->history_sel + (down ? 1 : -1), 0, row_count - 1);
      }
      rt->history_confirm_id[0] = '\0';
      history_scroll_selection_into_view(rt);
      ED_region_tag_redraw(region);
      return true;
    }

    case EVT_PAGEUPKEY:
    case EVT_PAGEDOWNKEY: {
      const float dir = (event->type == EVT_PAGEDOWNKEY) ? 1.0f : -1.0f;
      rt->history_scroll_target = std::clamp(
          rt->history_scroll_target + dir * rt->history_view_h, 0.0f, history_max_scroll(rt));
      ED_region_tag_redraw(region);
      return true;
    }

    case EVT_DELKEY:
      history_arm_or_delete_row(C, region, rt, rt->history_sel);
      return true;

    case EVT_BACKSPACEKEY: {
      const int len = int(strlen(rt->history_search));
      if (len > 0) {
        const char *prev = BLI_str_find_prev_char_utf8(rt->history_search + len,
                                                       rt->history_search);
        rt->history_search[prev - rt->history_search] = '\0';
        history_on_search_edit(rt);
        ED_region_tag_redraw(region);
      }
      return true;
    }

    default:
      break;
  }

  /* Printable input appends to the always-focused search query. */
  if (event->utf8_buf[0] != '\0' && uchar(event->utf8_buf[0]) >= 32 &&
      (event->modifier & (KM_CTRL | KM_ALT | KM_OSKEY)) == 0)
  {
    const int char_len = BLI_str_utf8_size_safe(event->utf8_buf);
    const int len = int(strlen(rt->history_search));
    if (len + char_len < int(sizeof(rt->history_search))) {
      memcpy(rt->history_search + len, event->utf8_buf, size_t(char_len));
      rt->history_search[len + char_len] = '\0';
      history_on_search_edit(rt);
      ED_region_tag_redraw(region);
    }
  }
  return true; /* Modal: no key press leaks to the chat behind the scrim. */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Events (called first from the region UI handler)
 * \{ */

bool mixie_chat_history_handle_event(bContext *C, const wmEvent *event)
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
  if (!rt->history_overlay_active) {
    return false;
  }

  if (ISKEYBOARD(event->type)) {
    if (event->val == KM_PRESS) {
      return history_handle_key(C, region, rt, event);
    }
    return true; /* Consume releases too — the overlay is modal. */
  }

  const float mx = float(event->mval[0]);
  const float my = float(event->mval[1]);
  const bool inside_panel = BLI_rctf_isect_pt(&rt->history_panel_bounds, mx, my);
  const bool scrollable = (rt->history_content_h > rt->history_view_h + 0.5f);

  /* Wheel: pixel-stepped scroll target (the draw eases toward it) inside
   * the panel; consumed everywhere while open so the chat behind the
   * scrim never scrolls. */
  if (event->type == WHEELUPMOUSE || event->type == WHEELDOWNMOUSE) {
    if (inside_panel && scrollable) {
      const float step = HIST_WHEEL_STEP_PX * UI_SCALE_FAC;
      rt->history_scroll_target += (event->type == WHEELDOWNMOUSE) ? step : -step;
      rt->history_scroll_target = std::clamp(
          rt->history_scroll_target, 0.0f, history_max_scroll(rt));
      ED_region_tag_redraw(region);
    }
    return true;
  }

  /* Trackpad pan: 1:1 pixel deltas into the scroll target. A positive
   * delta (fingers swipe up under natural scrolling) advances the list
   * toward older rows — matching the platform scroll convention and the
   * wheel mapping. */
  if (event->type == MOUSEPAN) {
    if (inside_panel && scrollable) {
      rt->history_scroll_target += float(event->xy[1] - event->prev_xy[1]);
      rt->history_scroll_target = std::clamp(
          rt->history_scroll_target, 0.0f, history_max_scroll(rt));
      ED_region_tag_redraw(region);
    }
    return true;
  }

  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    if (!inside_panel) {
      /* Click-away closes and consumes the click. */
      mixie_chat_history_set_visible(C, false);
      return true;
    }

    if (BLI_rctf_isect_pt(&rt->history_close_bounds, mx, my)) {
      mixie_chat_history_set_visible(C, false);
      return true;
    }

    bool over_delete = false;
    const int index = history_hit_row(rt, mx, my, &over_delete);
    if (index >= 0) {
      if (over_delete) {
        rt->history_sel = index;
        history_arm_or_delete_row(C, region, rt, index);
      }
      else {
        history_open_row(C, region, rt, index);
      }
    }
    else if (rt->history_confirm_id[0] != '\0') {
      /* Click on header/search/blank space disarms a pending delete. */
      rt->history_confirm_id[0] = '\0';
      ED_region_tag_redraw(region);
    }
    /* Clicks inside the panel (rows, header, blank space) never fall
     * through to the chat behind it. */
    return true;
  }

  return false;
}

/** \} */
