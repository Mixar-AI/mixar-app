/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Production input ownership and provenance, accessed only on the main thread. */
#include <chrono>
#include <cstring>
#include <string>
#include <unordered_map>

#include "BLI_listbase.h"

#include "DNA_windowmanager_types.h"
#include "WM_api.hh"
#include "WM_mixar.hh"
#include "WM_types.hh"

namespace blender {
namespace {
using Clock = std::chrono::steady_clock;
bool enabled = false;
std::string owner;
Clock::time_point deadline;
int generation = 1;
std::unordered_map<const wmEvent *, int> pending;
std::unordered_map<wmWindow *, std::unordered_map<int, wmEvent>> held;

bool live_window(wmWindowManager *wm, wmWindow *candidate)
{
  for (wmWindow &win : wm->windows) {
    if (&win == candidate) {
      return true;
    }
  }
  return false;
}

void revoke(wmWindowManager *wm)
{
  if (owner.empty() && held.empty()) {
    return;
  }
  owner.clear();
  generation = generation == INT32_MAX ? 1 : generation + 1;
  /* Only release inputs that actually reached handlers, never a queued press.
   * Releases are cleanup events, not agent events. They survive revocation.
   * Do not send Escape into a possibly human-owned modal. */
  for (auto &[win, inputs] : held) {
    if (!live_window(wm, win)) {
      continue;
    }
    for (auto &[type, press] : inputs) {
      wmEvent release = press;
      release.val = KM_RELEASE;
      release.modifier = wmEventModifierFlag(0);
      release.utf8_buf[0] = '\0';
      Mixar_event_add_synthetic(win, &release);
    }
  }
  held.clear();
}
}  // namespace

void Mixar_ui_control_enable(wmWindowManager *wm, const bool value)
{
  if (!value) {
    revoke(wm);
  }
  enabled = value;
}

bool Mixar_ui_control_enabled()
{
  return enabled;
}

bool Mixar_ui_control_begin(wmWindowManager *wm, const char *token)
{
  Mixar_ui_control_generation(wm);
  if (!enabled || !token || strlen(token) < 32 || (!owner.empty() && owner != token)) {
    return false;
  }
  owner = token;
  deadline = Clock::now() + std::chrono::seconds(15);
  return true;
}

void Mixar_ui_control_end(wmWindowManager *wm, const char *token)
{
  if (token && owner == token) {
    revoke(wm);
  }
}

int Mixar_ui_control_generation(wmWindowManager *wm)
{
  if (!owner.empty() && Clock::now() >= deadline) {
    revoke(wm);
  }
  return generation;
}

int Mixar_ui_control_pending()
{
  return int(pending.size());
}

bool Mixar_ui_control_input(wmWindowManager *wm, wmWindow *win,
                            const char *token, const wmEvent *event)
{
  Mixar_ui_control_generation(wm);
  if (!enabled || owner.empty() || owner != token || !live_window(wm, win) ||
      Mixar_window_resize_dispatch_active())
  {
    return false;
  }
  wmEvent *queued = Mixar_event_add_synthetic(win, event);
  pending[queued] = generation;
  return true;
}

bool Mixar_ui_control_event_valid(wmWindow *win, const wmEvent *event)
{
  const auto found = pending.find(event);
  if (found == pending.end()) {
    return true;
  }
  if (!enabled || owner.empty() || found->second != generation || Clock::now() >= deadline) {
    return false;
  }
  if (ISKEYBOARD_OR_BUTTON(event->type)) {
    if (event->val == KM_PRESS) {
      held[win][int(event->type)] = *event;
    }
    else if (event->val == KM_RELEASE) {
      const auto inputs = held.find(win);
      if (inputs != held.end()) {
        inputs->second.erase(int(event->type));
      }
    }
  }
  return true;
}

void Mixar_ui_control_event_forget(const wmEvent *event)
{
  pending.erase(event);
}

void Mixar_ui_control_human_input(wmWindowManager *wm)
{
  if (owner.empty()) {
    generation = generation == INT32_MAX ? 1 : generation + 1;
  }
  else {
    revoke(wm);
  }
}
}  // namespace blender
