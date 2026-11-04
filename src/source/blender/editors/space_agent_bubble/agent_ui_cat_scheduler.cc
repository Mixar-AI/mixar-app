/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>

#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "BLI_time.h"
#include "BLI_timer.h"
#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_agent_bubble_motion.hh"
#include "ED_screen.hh"
#include "WM_api.hh"

#include "agent_ui_cat_cadence.hh"
#include "agent_ui_cat_scheduler.hh"

#if defined(__APPLE__) || defined(_WIN32)
extern "C" bool Mixar_WindowCanAnimate(void *window_handle);
#endif

namespace blender {
namespace {
char timer_identity;
/* Borrowed identities only. Every access is resolved against live windows and
 * regions first, including availability checks after file load/window close. */
const void *owner_ghost = nullptr;
const void *owner_host = nullptr;
const ARegion *owner_region = nullptr;
bool awaiting_draw = false;
double due = 0.0;
AgentBubbleMotionStats stats{};

uintptr_t timer_id()
{
  return uintptr_t(&timer_identity);
}

ARegion *live_region(wmWindowManager *wm)
{
  if (!wm || !owner_ghost || !owner_region) {
    return nullptr;
  }
  /* AppKit can detach a child as its host miniaturizes. The semantic host
   * identity remains authoritative even when the OS parent chain is empty. */
  if (owner_host) {
    bool host_visible = false;
    for (wmWindow &window : wm->windows) {
      if (window.runtime->ghostwin == owner_host) {
#if defined(__APPLE__) || defined(_WIN32)
        host_visible = Mixar_WindowCanAnimate(window.runtime->ghostwin);
#endif
        break;
      }
    }
    if (!host_visible) {
      return nullptr;
    }
  }
  for (wmWindow &window : wm->windows) {
    if (window.runtime->ghostwin != owner_ghost) {
      continue;
    }
#if defined(__APPLE__) || defined(_WIN32)
    if (!Mixar_WindowCanAnimate(window.runtime->ghostwin)) {
      return nullptr;
    }
#else
    return nullptr;
#endif
    bScreen *screen = WM_window_get_active_screen(&window);
    if (!screen) {
      return nullptr;
    }
    for (ScrArea &area : screen->areabase) {
      if (area.spacetype != SPACE_AGENT_BUBBLE) {
        continue;
      }
      for (ARegion &region : area.regionbase) {
        if (&region == owner_region && region.regiontype == RGN_TYPE_HEADER &&
            region.runtime->visible)
        {
          return &region;
        }
      }
    }
  }
  return nullptr;
}

double redraw_once(uintptr_t /*id*/, void * /*data*/)
{
  stats.ticks++;
  if (G_MAIN) {
    for (wmWindowManager &manager : G_MAIN->wm) {
      if (ARegion *region = live_region(&manager)) {
        ED_region_tag_redraw(region);
        stats.redraws++;
        awaiting_draw = true;
        break;
      }
    }
  }
  /* The next actual paint schedules its next useful frame. A hidden or closed
   * surface cannot leave a recurring timer behind. */
  return -1.0;
}

void arm(double seconds)
{
  const double next = BLI_time_now_seconds() + seconds;
  if (BLI_timer_is_registered(timer_id())) {
    if (due <= next) {
      return;
    }
    BLI_timer_unregister(timer_id());
  }
  due = next;
  BLI_timer_register(timer_id(), redraw_once, nullptr, nullptr, seconds, false);
}
}  // namespace

void agent_ui_cat_schedule(const wmWindow *window,
                           ARegion *region,
                           const void *host,
                           const double seconds)
{
  if (!window || !window->runtime->ghostwin) {
    return;
  }
  if (owner_region != region || owner_ghost != window->runtime->ghostwin) {
    agent_ui_cat_scheduler_forget();
  }
  owner_ghost = window->runtime->ghostwin;
  owner_host = host;
  owner_region = region;
  awaiting_draw = false;
  if (seconds <= MIXIE_CAT_FRAME_SECONDS + 1e-6) {
    stats.fast_frames++;
  }
  else {
    stats.quiet_frames++;
  }
  if (G_MAIN) {
    for (wmWindowManager &manager : G_MAIN->wm) {
      if (live_region(&manager)) {
        arm(seconds);
        break;
      }
    }
  }
}

void agent_ui_cat_scheduler_sync(wmWindowManager *wm, const void *pill, const bool minimized)
{
  if (!minimized || pill != owner_ghost) {
    agent_ui_cat_scheduler_forget();
    return;
  }
  if (!live_region(wm)) {
    BLI_timer_unregister(timer_id());
    awaiting_draw = false;
    return;
  }
  /* OS unhide / modal-panel dismissal may not send a region notifier. Re-arm
   * one frame on that edge using the existing hover policy's slow heartbeat. */
  if (!awaiting_draw && !BLI_timer_is_registered(timer_id())) {
    arm(MIXIE_CAT_FRAME_SECONDS);
  }
}

void agent_ui_cat_scheduler_forget(const ARegion *region)
{
  if (region && region != owner_region) {
    return;
  }
  BLI_timer_unregister(timer_id());
  owner_ghost = nullptr;
  owner_host = nullptr;
  owner_region = nullptr;
  awaiting_draw = false;
}

void agent_ui_cat_scheduler_window_freed(const void *ghostwin)
{
  if (ghostwin == owner_ghost || ghostwin == owner_host) {
    agent_ui_cat_scheduler_forget();
  }
}

AgentBubbleMotionStats ED_agent_bubble_motion_stats()
{
  AgentBubbleMotionStats result = stats;
  result.scheduled = BLI_timer_is_registered(timer_id());
  result.awaiting_draw = awaiting_draw;
  result.next_frame_seconds = result.scheduled ? std::max(0.0, due - BLI_time_now_seconds()) : 0;
  return result;
}
}  // namespace blender
