/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "mixie_chat_anim_pump.hh"

#include "BKE_context.hh"
#include "BLI_time.h"
#include "ED_agent_bubble_motion.hh"
#include "WM_api.hh"
#include "WM_types.hh"

namespace blender {
namespace {
constexpr double CHAT_ANIM_PUMP_FPS = 30.0;
constexpr double CHAT_ANIM_PUMP_IDLE_GRACE = 0.5;

wmTimer *timer = nullptr;
/* Region exit clears both before its window or manager is freed. */
wmWindowManager *owner = nullptr;
double last_request = 0.0;
uint64_t ticks = 0;
}  // namespace

void mixie_chat_anim_pump_shutdown(wmWindowManager *wm)
{
  if (wm == nullptr || timer == nullptr) {
    return;
  }
  WM_event_timer_remove(wm, nullptr, timer);
  timer = nullptr;
  owner = nullptr;
}

void mixie_chat_anim_pump_request(const bContext *C, const bool anim_active)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  const double now = BLI_time_now_seconds();
  if (anim_active) {
    last_request = now;
    if (timer == nullptr && CTX_wm_window(C) != nullptr) {
      timer = WM_event_timer_add_notifier(
          wm, CTX_wm_window(C), NC_SPACE | ND_SPACE_MIXIE_CHAT_TICK, 1.0 / CHAT_ANIM_PUMP_FPS);
      owner = wm;
    }
  }
  else if (timer != nullptr && now - last_request > CHAT_ANIM_PUMP_IDLE_GRACE) {
    mixie_chat_anim_pump_shutdown(wm);
  }
}

void mixie_chat_anim_pump_tick()
{
  if (timer == nullptr) {
    return;
  }
  ticks++;
  /* Native hiding does not exit a region, and hidden windows do not draw.
   * Waiting for draw(false) therefore strands a repeating timer indefinitely
   * after a collapse during streaming, history, or a slide-in. The notifier
   * still reaches its listener: expire here without requiring another paint.
   * The listener tags one last frame so an interrupted visible animation can
   * settle, or re-arm normally if it is still live. */
  if (BLI_time_now_seconds() - last_request > CHAT_ANIM_PUMP_IDLE_GRACE) {
    mixie_chat_anim_pump_shutdown(owner);
  }
}

AgentChatAnimationStats ED_agent_chat_animation_stats()
{
  return {ticks, timer != nullptr};
}
}  // namespace blender
