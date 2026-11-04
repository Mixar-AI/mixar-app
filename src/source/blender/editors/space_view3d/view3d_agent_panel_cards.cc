/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Parallel Agents panel: animation clocks and region lifecycle.
 * Card geometry and input bounds live in view3d_agent_panel_layout.cc.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_map.hh"
#include "BLI_rect.h"
#include "BLI_set.hh"
#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_view2d_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_agent_panel.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Animation
 * \{ */

float view3d_agent_panel_exit_progress(const AgentPanelCard &card)
{
  if (card.seen_exit_at == 0.0) {
    return 0.0f;
  }
  if (!card.dismissing && card.status != AgentCardStatus::Done) {
    return 0.0f;
  }
  /* A dismissal is a direct answer to a click and leaves at once; a finished
   * card dwells first so its check mark registers. */
  const double dwell = card.dismissing ? 0.0 : AGENT_PANEL_DONE_DWELL_SECONDS;
  const double elapsed = BLI_time_now_seconds() - card.seen_exit_at - dwell;
  if (elapsed <= 0.0) {
    return 0.0f;
  }
  return ui::mixar_motion::ease_out(float(elapsed / AGENT_PANEL_EXIT_SECONDS));
}

float view3d_agent_panel_reveal(const AgentPanelRuntime *runtime, const int card_index)
{
  if (card_index < 0 || card_index >= runtime->cards.size()) {
    return 1.0f;
  }
  const double elapsed = BLI_time_now_seconds() - runtime->cards[card_index].reveal_started_at;
  if (elapsed <= 0.0) {
    return 0.0f;
  }
  return ui::mixar_motion::ease_out(float(elapsed / AGENT_PANEL_REVEAL_SECONDS));
}

bool view3d_agent_panel_is_animating(const AgentPanelRuntime *runtime)
{
  if (runtime->cards.is_empty()) {
    return false;
  }
  const double now = BLI_time_now_seconds();
  for (const AgentPanelCard &card : runtime->cards) {
    if (now < card.reveal_started_at + AGENT_PANEL_REVEAL_SECONDS || card.slide.active(now) ||
        card.row.active(now) || card.slide.value != card.slide.target ||
        card.row.value != card.row.target)
    {
      return true;
    }
    /* A running agent's elapsed clock has to keep ticking. */
    if (card.status == AgentCardStatus::Running) {
      return true;
    }
    /* A card is on its way out, or waiting to start leaving. */
    if ((card.dismissing || card.status == AgentCardStatus::Done) &&
        view3d_agent_panel_exit_progress(card) < 1.0f)
    {
      return true;
    }
  }
  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Runtime Lifecycle
 * \{ */

ARegion *view3d_agent_panel_region_find(const ScrArea *area)
{
  if (!area || area->spacetype != SPACE_VIEW3D) {
    return nullptr;
  }
  for (ARegion &region_iter : area->regionbase) {
    ARegion *region = &region_iter;
    if (region->regiontype == RGN_TYPE_EXECUTE) {
      return region;
    }
  }
  return nullptr;
}

AgentPanelRuntime *view3d_agent_panel_runtime_ensure(ARegion *region)
{
  if (region->regiondata == nullptr) {
    region->regiondata = MEM_new<AgentPanelRuntime>("AgentPanelRuntime");
    region->flag |= RGN_FLAG_TEMP_REGIONDATA;
  }
  return static_cast<AgentPanelRuntime *>(region->regiondata);
}

void view3d_agent_panel_tick_timer_ensure(const bContext *C, AgentPanelRuntime *runtime)
{
  if (runtime->tick_timer != nullptr) {
    return;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  wmWindow *win = CTX_wm_window(C);
  if (wm == nullptr || win == nullptr) {
    return;
  }
  runtime->tick_timer = WM_event_timer_add(wm, win, TIMERNOTIFIER, AGENT_PANEL_TICK_INTERVAL);
}

void view3d_agent_panel_tick_timer_remove(wmWindowManager *wm, AgentPanelRuntime *runtime)
{
  if (runtime == nullptr || runtime->tick_timer == nullptr) {
    return;
  }
  if (wm != nullptr) {
    WM_event_timer_remove(wm, runtime->tick_timer->win, runtime->tick_timer);
  }
  runtime->tick_timer = nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region Type Registration
 * \{ */

void view3d_agent_panel_space_listener(const wmSpaceTypeListenerParams *params)
{
  /* Cheap: one category compare, then a flag. `ED_area_tag_refresh` only sets
   * `do_refresh`; the refresh itself runs in the event loop's own pass, never
   * inside a draw. */
  const wmNotifier *wmn = params->notifier;
  if (ELEM(wmn->category, NC_WINDOW, NC_SCREEN)) {
    ED_area_tag_refresh(params->area);
    /* A region the refresh brings back has no `regiondata` until it draws —
     * and until it draws it has no cards, no hit rects and no QA targets. The
     * refresh alone does not tag it, so a panel could exist at full size and
     * paint nothing at all. */
    ED_area_tag_redraw_regiontype(params->area, RGN_TYPE_EXECUTE);
  }
}

static void agent_panel_region_listener(const wmRegionListenerParams *params)
{
  /* The animation tick arrives here, and this is the only place that can act
   * on it: `wm_draw.cc` clears `region->runtime->do_draw` immediately AFTER
   * `ED_region_do_draw` returns, so a redraw tagged from inside the draw
   * callback is wiped before it can take effect. Tagging from a listener —
   * outside the draw — is what actually produces the next frame, which makes
   * the tick interval the animation's real frame rate.
   *
   * Gated on the runtime, so a settled panel costs a pointer read. */
  ARegion *region = params->region;
  const AgentPanelRuntime *runtime = static_cast<const AgentPanelRuntime *>(region->regiondata);
  if (runtime != nullptr && view3d_agent_panel_is_animating(runtime)) {
    ED_region_tag_redraw(region);
  }
}

static bool agent_panel_region_poll(const RegionPollParams *params)
{
  /* Polls run every event-loop cycle, so this stays a single RNA read: the
   * Python mirror maintains the count, and the panel exists exactly while
   * the running (or last) turn fanned out to parallel agents. */
  return view3d_agent_panel_card_count(params->context) > 0;
}

static void agent_panel_region_free(ARegion *region)
{
  if (region->regiondata != nullptr) {
    AgentPanelRuntime *runtime = static_cast<AgentPanelRuntime *>(region->regiondata);
    /* The timer is owned by the window manager and removed in the region
     * exit callback, which always runs first; clear the pointer regardless
     * so a stale one can never be dereferenced. */
    runtime->tick_timer = nullptr;
    MEM_delete(runtime);
    region->regiondata = nullptr;
  }
}

static void *agent_panel_region_duplicate(void * /*poin*/)
{
  /* Runtime is per-region; copies (area split/duplicate) start fresh. */
  return nullptr;
}

static void agent_panel_region_cursor(wmWindow *win, ScrArea * /*area*/, ARegion *region)
{
  auto *runtime = static_cast<AgentPanelRuntime *>(region->regiondata);
  if (!runtime) { return; }
  const int mouse[2] = {win->runtime->eventstate->xy[0] - region->winrct.xmin,
                        win->runtime->eventstate->xy[1] - region->winrct.ymin};
  const AgentPanelHit hit = view3d_agent_panel_hit_test(runtime, mouse, nullptr);
  const bool control = ELEM(hit, AgentPanelHit::Eye, AgentPanelHit::Action, AgentPanelHit::Chevron);
  WM_cursor_set(win, control ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
  ED_region_tag_redraw(region);
}

void view3d_agent_panel_region_register(SpaceType *st)
{
  /* Fully custom GPU drawing — no ED_KEYMAP_UI, whose ui_region_handler could
   * consume LEFTMOUSE before our keymap (same reasoning as the Mixie Chat
   * main region). */
  ARegionType *art = MEM_new_zeroed<ARegionType>("spacetype view3d agent panel region");
  art->regionid = RGN_TYPE_EXECUTE;
  art->prefsizey = AGENT_PANEL_PREFSIZEY;
  art->keymapflag = 0;
  art->poll = agent_panel_region_poll;
  art->init = view3d_agent_panel_region_init;
  art->exit = view3d_agent_panel_region_exit;
  art->draw = view3d_agent_panel_region_draw;
  art->free = agent_panel_region_free;
  art->duplicate = agent_panel_region_duplicate;
  art->listener = agent_panel_region_listener;
  art->cursor = agent_panel_region_cursor;
  /* Re-evaluate controls on moves within this region, including settled cards. */
  art->event_cursor = true;
  BLI_addhead(&st->regiontypes, art);
}

/** \} */

}  // namespace blender
