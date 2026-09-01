/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Scribble ink overlay — shared helpers: the RNA bridge to the
 * Python-owned visibility/busy properties, the stroke store, the frozen
 * strokes-JSON serialization, the `mixie_chat.ink_commit` dispatch, the
 * process-global idle-commit timer, and MIXIE_CHAT_OT_ink_flush (the
 * commit-now entry point Python uses before closing the overlay from a
 * header toggle, where C++ gets no event to flush on).
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_ink_intern.hh"
#include "mixie_chat_intern.hh"

/* Frozen contract with the Python validator (core/scribble.py). */
static_assert(CHAT_INK_MAX_POINTS == 4096, "lockstep with SCRIBBLE_MAX_POINTS");
static_assert(CHAT_INK_MAX_STROKES == 64, "lockstep with SCRIBBLE_MAX_STROKES");

/* -------------------------------------------------------------------- */
/** \name RNA Bridge (Python-owned properties)
 * \{ */

static bool ink_read_wm_bool(wmWindowManager *wm, const char *identifier)
{
  if (!wm) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, identifier);
  if (!prop) {
    return false;
  }
  return RNA_property_boolean_get(&wm_ptr, prop);
}

bool mixie_chat_ink_read_visible(wmWindowManager *wm)
{
  return ink_read_wm_bool(wm, "mixie_chat_ink_visible");
}

bool mixie_chat_ink_feature_available(wmWindowManager *wm)
{
  /* The auto-open paths must not pre-latch a dead overlay (and eat the
   * press) before the deferred Python UI pass registers the props. */
  if (!wm) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  return RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_visible") != nullptr;
}

bool mixie_chat_ink_read_busy(wmWindowManager *wm)
{
  return ink_read_wm_bool(wm, "mixie_chat_ink_busy");
}

void mixie_chat_ink_set_visible(bContext *C, bool visible)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_visible");
  if (!prop) {
    return; /* Python side not registered — feature off. */
  }
  if (visible) {
    /* Three-way overlay exclusivity, same contract the Python toggles keep:
     * opening ink closes the rules + history overlays (and vice versa). */
    for (const char *other : {"mixie_chat_rules_visible", "mixie_chat_history_visible"}) {
      PropertyRNA *other_prop = RNA_struct_find_property(&wm_ptr, other);
      if (other_prop && RNA_property_boolean_get(&wm_ptr, other_prop)) {
        RNA_property_boolean_set(&wm_ptr, other_prop, false);
      }
    }
  }
  RNA_property_boolean_set(&wm_ptr, prop, visible);
  /* Repaint every chat surface (editor + floating bubble). */
  WM_main_add_notifier(NC_SPACE | ND_SPACE_MIXIE_CHAT, nullptr);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Stroke Store
 * \{ */

void mixie_chat_ink_reset_runtime(MixieChatRuntime *rt)
{
  rt->ink_point_count = 0;
  rt->ink_stroke_count = 0;
  rt->ink_stroke_live = false;
  rt->ink_last_penup_time = 0.0;
  rt->ink_store_full = false;
  BLI_rctf_init(&rt->ink_close_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->ink_clear_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  rt->ink_close_hovered = false;
  rt->ink_clear_hovered = false;
}

void mixie_chat_ink_begin_session(MixieChatRuntime *rt)
{
  mixie_chat_ink_reset_runtime(rt);
  rt->ink_anim_start = BLI_time_now_seconds();
}

bool mixie_chat_ink_stroke_begin(MixieChatRuntime *rt, float x, float y, float p)
{
  if (rt->ink_stroke_live) {
    return false;
  }
  if (rt->ink_stroke_count >= CHAT_INK_MAX_STROKES ||
      rt->ink_point_count >= CHAT_INK_MAX_POINTS)
  {
    rt->ink_store_full = true;
    return false;
  }
  rt->ink_stroke_starts[rt->ink_stroke_count++] = rt->ink_point_count;
  float *pt = rt->ink_points[rt->ink_point_count++];
  pt[0] = x;
  pt[1] = y;
  pt[2] = std::clamp(p, 0.0f, 1.0f);
  rt->ink_stroke_live = true;
  return true;
}

void mixie_chat_ink_stroke_extend(MixieChatRuntime *rt, float x, float y, float p)
{
  if (!rt->ink_stroke_live || rt->ink_point_count <= 0) {
    return;
  }
  if (rt->ink_point_count >= CHAT_INK_MAX_POINTS) {
    rt->ink_store_full = true;
    return;
  }
  const float *last = rt->ink_points[rt->ink_point_count - 1];
  const float dx = x - last[0];
  const float dy = y - last[1];
  const float min_dist = INK_MIN_SAMPLE_DIST * UI_SCALE_FAC;
  if (dx * dx + dy * dy < min_dist * min_dist) {
    return;
  }
  float *pt = rt->ink_points[rt->ink_point_count++];
  pt[0] = x;
  pt[1] = y;
  pt[2] = std::clamp(p, 0.0f, 1.0f);
}

void mixie_chat_ink_stroke_end(MixieChatRuntime *rt)
{
  if (!rt->ink_stroke_live) {
    return;
  }
  rt->ink_stroke_live = false;
  rt->ink_last_penup_time = BLI_time_now_seconds();
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Serialization + Commit Dispatch
 * \{ */

std::string mixie_chat_ink_serialize(const MixieChatRuntime *rt, int winx, int winy)
{
  /* Only COMPLETED strokes serialize — a live stroke (pen still down) stays
   * on the canvas and joins the next batch. */
  const int stroke_count = rt->ink_stroke_count - (rt->ink_stroke_live ? 1 : 0);
  if (stroke_count <= 0) {
    return "";
  }

  std::string out;
  out.reserve(size_t(INK_JSON_MAX));
  char buf[64];
  SNPRINTF(buf, "{\"w\":%d,\"h\":%d,\"strokes\":[", winx, winy);
  out += buf;

  for (int s = 0; s < stroke_count; s++) {
    const int start = rt->ink_stroke_starts[s];
    const int end = (s + 1 < rt->ink_stroke_count) ? rt->ink_stroke_starts[s + 1] :
                                                     rt->ink_point_count;
    if (s > 0) {
      out += ',';
    }
    out += '[';
    for (int i = start; i < end; i++) {
      const float *pt = rt->ink_points[i];
      SNPRINTF(buf,
               "%s[%d,%d,%.2f]",
               (i > start) ? "," : "",
               int(std::lround(pt[0])),
               int(std::lround(pt[1])),
               double(pt[2]));
      out += buf;
    }
    out += ']';
  }
  out += "]}";

  /* The store caps make this unreachable, but the Python validator hard
   * rejects oversize payloads — never hand it one. */
  if (out.size() >= size_t(INK_JSON_MAX)) {
    return "";
  }
  return out;
}

void mixie_chat_ink_commit(bContext *C, ARegion *region, MixieChatRuntime *rt)
{
  const std::string payload = mixie_chat_ink_serialize(rt, region->winx, region->winy);
  if (!payload.empty()) {
    wmOperatorType *ot = WM_operatortype_find("mixie_chat.ink_commit", true);
    if (ot) {
      PointerRNA op_ptr;
      WM_operator_properties_create_ptr(&op_ptr, ot);
      RNA_string_set(&op_ptr, "strokes_json", payload.c_str());
      WM_operator_name_call_ptr(
          C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
      WM_operator_properties_free(&op_ptr);
    }
  }

  /* Clear the committed strokes; a live in-progress stroke (the race where
   * the pen touched down as the idle timer fired) is compacted to the
   * front of the store and keeps capturing. */
  if (rt->ink_stroke_live && rt->ink_stroke_count > 0) {
    const int live_start = rt->ink_stroke_starts[rt->ink_stroke_count - 1];
    const int live_len = rt->ink_point_count - live_start;
    memmove(rt->ink_points[0], rt->ink_points[live_start], sizeof(float[3]) * size_t(live_len));
    rt->ink_stroke_starts[0] = 0;
    rt->ink_stroke_count = 1;
    rt->ink_point_count = live_len;
  }
  else {
    rt->ink_point_count = 0;
    rt->ink_stroke_count = 0;
  }
  rt->ink_store_full = false;
  ED_region_tag_redraw(region);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Idle-Commit Timer (process-global, like the chat anim pump)
 *
 * A plain wmTimer whose TIMER events reach the region UI handler (timer
 * events are "always pass"); the handler converts pending strokes once
 * INK_IDLE_COMMIT_SEC passed since the last pen-up. Global because at most
 * one scribble session is meaningfully live and region-exit has no runtime
 * access for cleanup (same reasoning as g_chat_anim_timer).
 * \{ */

static wmTimer *g_ink_idle_timer = nullptr;

void mixie_chat_ink_idle_timer_ensure(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  wmWindow *win = CTX_wm_window(C);
  if (!wm || !win) {
    return;
  }
  /* Window-bound wmTimers deliver TIMER events only to their own window's
   * queue, and the docked chat and the Agent Bubble are separate wmWindows
   * — so the timer FOLLOWS the last pen-up: writing in another window
   * rebinds it there. The abandoned window's pending ink (rare: it needs
   * un-paused writing in two windows at once) still converts via the
   * close-path flush-all. */
  if (g_ink_idle_timer != nullptr && g_ink_idle_timer->win != win) {
    WM_event_timer_remove(wm, nullptr, g_ink_idle_timer);
    g_ink_idle_timer = nullptr;
  }
  if (g_ink_idle_timer == nullptr) {
    g_ink_idle_timer = WM_event_timer_add(wm, win, TIMER, INK_IDLE_TIMER_STEP);
  }
}

void mixie_chat_ink_idle_timer_remove(wmWindowManager *wm)
{
  if (wm == nullptr || g_ink_idle_timer == nullptr) {
    return;
  }
  WM_event_timer_remove(wm, nullptr, g_ink_idle_timer);
  g_ink_idle_timer = nullptr;
}

bool mixie_chat_ink_idle_timer_matches(const wmEvent *event)
{
  return g_ink_idle_timer != nullptr && event->type == TIMER &&
         event->customdata == g_ink_idle_timer;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name MIXIE_CHAT_OT_ink_flush
 *
 * Commit-now for every chat surface with pending ink. Python calls this
 * BEFORE clearing `mixie_chat_ink_visible` from paths where C++ sees no
 * event (the header toggle, the rules/history toggles enforcing overlay
 * exclusivity) — the draw-side closing edge must never dispatch operators,
 * so without this flush a header-close would silently drop unconverted
 * writing.
 * \{ */

void mixie_chat_ink_flush_all_surfaces(bContext *C)
{
  /* EVERY chat surface, not just the one under the cursor: the visibility
   * bool is WM-global, so the docked chat and the Agent Bubble latch the
   * canvas together — closing from one must not drop the other's ink. */
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  LISTBASE_FOREACH (wmWindow *, win, &wm->windows) {
    bScreen *screen = WM_window_get_active_screen(win);
    if (!screen) {
      continue;
    }
    LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
      if (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE) {
        continue;
      }
      SpaceMixieChat *smixie = static_cast<SpaceMixieChat *>(area->spacedata.first);
      if (!smixie) {
        continue;
      }
      MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
      if (rt->ink_point_count <= 0) {
        continue;
      }
      LISTBASE_FOREACH (ARegion *, region, &area->regionbase) {
        if (region->regiontype == RGN_TYPE_WINDOW) {
          mixie_chat_ink_commit(C, region, rt);
          break;
        }
      }
    }
  }
}

static wmOperatorStatus ink_flush_exec(bContext *C, wmOperator * /*op*/)
{
  mixie_chat_ink_flush_all_surfaces(C);
  return OPERATOR_FINISHED;
}

void MIXIE_CHAT_OT_ink_flush(wmOperatorType *ot)
{
  ot->name = "Flush Scribble Ink";
  ot->idname = "MIXIE_CHAT_OT_ink_flush";
  ot->description = "Convert any pending handwritten strokes on the scribble canvas now";
  ot->exec = ink_flush_exec;
  ot->flag = OPTYPE_INTERNAL;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name MIXIE_CHAT_OT_ink_release_composer
 *
 * Force-exit any active composer text-edit on every chat surface. Python
 * calls this right before appending recognized text to
 * `scene.mixie_chat_input`: an active text-edit holds a private edit
 * buffer that is applied wholesale back into the property on the next
 * keystroke, which would silently erase a transcription that landed
 * mid-edit. Exiting costs nothing — TEXTEDIT_UPDATE applies every
 * keystroke to the property as it is typed.
 * \{ */

static wmOperatorStatus ink_release_composer_exec(bContext *C, wmOperator * /*op*/)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return OPERATOR_CANCELLED;
  }
  LISTBASE_FOREACH (wmWindow *, win, &wm->windows) {
    bScreen *screen = WM_window_get_active_screen(win);
    if (!screen) {
      continue;
    }
    LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
      if (area->spacetype != SPACE_MIXIE_CHAT && area->spacetype != SPACE_AGENT_BUBBLE) {
        continue;
      }
      LISTBASE_FOREACH (ARegion *, region, &area->regionbase) {
        if (region->regiontype == RGN_TYPE_TOOLS) {
          UI_region_free_active_but_all(C, region);
        }
      }
    }
  }
  return OPERATOR_FINISHED;
}

void MIXIE_CHAT_OT_ink_release_composer(wmOperatorType *ot)
{
  ot->name = "Release Chat Composer Focus";
  ot->idname = "MIXIE_CHAT_OT_ink_release_composer";
  ot->description =
      "Exit any active chat composer text edit so recognized handwriting can append safely";
  ot->exec = ink_release_composer_exec;
  ot->flag = OPTYPE_INTERNAL;
}

/** \} */
