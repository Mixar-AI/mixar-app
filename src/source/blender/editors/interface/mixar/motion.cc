/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "../interface_intern.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BLI_listbase.h"
#include "BLI_time.h"
#include "BLI_timer.h"
#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "UI_mixar_motion.hh"
#include "WM_api.hh"

#include <unordered_map>

namespace blender::ui {
namespace {
std::unordered_map<ARegion *, double> pending;
char timer_identity;
uint64_t ticks = 0, redraws = 0;

void timer_free(uintptr_t /*id*/, void * /*data*/)
{
  pending.clear();
}

double redraw_tick(uintptr_t /*id*/, void * /*data*/)
{
  ticks++;
  const double now = BLI_time_now_seconds();
  std::unordered_map<ARegion *, double> live;
  auto visit = [&](ARegion *region) {
    const auto found = pending.find(region);
    if (found == pending.end()) {
      return;
    }
    /* region came from a live screen, never from the retained pointer. Tag
     * once at/after the deadline too, so a missed frame still lands exactly. */
    ED_region_tag_redraw(region);
    redraws++;
    if (found->second > now) {
      live.emplace(region, found->second);
    }
  };
  if (G_MAIN) {
    for (wmWindowManager &manager : G_MAIN->wm) {
      for (wmWindow &window : manager.windows) {
        bScreen *screen = WM_window_get_active_screen(&window);
        if (!screen) {
          continue;
        }
        for (ARegion &region : screen->regionbase) {
          visit(&region); /* Popups and menus have no ScrArea. */
        }
        for (ScrArea &area : screen->areabase) {
          for (ARegion &region : area.regionbase) {
            visit(&region);
          }
        }
        for (ScrArea &area : window.global_areas.areabase) {
          for (ARegion &region : area.regionbase) {
            visit(&region);
          }
        }
      }
    }
  }
  pending = std::move(live); /* Closing/replacing a surface drops its request. */
  return pending.empty() ? -1.0 : mixar_motion::frame_seconds;
}
}  // namespace

void mixar_motion_request(ARegion *region, const double deadline)
{
  if (!region) {
    return;
  }
  const uintptr_t id = uintptr_t(&timer_identity);
  if (!BLI_timer_is_registered(id)) {
    pending.clear();
    BLI_timer_register(id, redraw_tick, nullptr, timer_free, mixar_motion::frame_seconds, false);
  }
  double &until = pending[region];
  until = std::max(until, deadline);
}

float mixar_motion_step(MixarMotionValue &motion,
                        const float target,
                        const double seconds,
                        ARegion *region)
{
  const double now = BLI_time_now_seconds();
  const float value = motion.sample(target, now, seconds);
  if (motion.active(now)) {
    mixar_motion_request(region, motion.started + motion.duration);
  }
  return value;
}

void mixar_button_motion_update(Button &button, ARegion *region)
{
  const auto &style = button.mixar_style;
  if (style.theme == MixarTheme::Native || style.component == MixarComponent::None) {
    button.mixar_motion.reset();
    return;
  }
  button.mixar_motion.ensure();
  auto &motion = *button.mixar_motion;
  if (button.optype) {
    motion.operator_identity = button.optype;
  }
  const bool disabled = (button.flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
  const bool toggle = ELEM(button.type,
                           ButtonType::Toggle,
                           ButtonType::ToggleN,
                           ButtonType::IconToggle,
                           ButtonType::IconToggleN,
                           ButtonType::Checkbox,
                           ButtonType::CheckboxN,
                           ButtonType::Row,
                           ButtonType::ListRow);
  const bool native_selection = (button.flag & UI_SELECT_DRAW) ||
                                (toggle && (button.flag & UI_SELECT));
  const bool cinema_selection = style.card == MixarCardElement::CinemaRow &&
                                (style.cinema == MixarCinemaRowKind::Active ||
                                 (style.cinema == MixarCinemaRowKind::Segment &&
                                  (button.flag & BUT_ACTIVE_DEFAULT)));
  const float selected = style.lit || native_selection || cinema_selection ? 1.0f : 0.0f;
  if (disabled) {
    motion.hover.settle(0.0f);
    motion.press.settle(0.0f);
    motion.selected.settle(selected);
    return;
  }
  const bool pressed =
      !toggle && (button.flag & UI_SELECT) &&
      ELEM(button.type, ButtonType::But, ButtonType::Menu, ButtonType::Block, ButtonType::Popover);
  mixar_motion_step(
      motion.hover, (button.flag & UI_HOVER) ? 1.0f : 0.0f, mixar_motion::hover_seconds, region);
  mixar_motion_step(motion.press,
                    pressed ? 1.0f : 0.0f,
                    pressed ? mixar_motion::press_seconds : mixar_motion::hover_seconds,
                    region);
  mixar_motion_step(motion.selected, selected, mixar_motion::selection_seconds, region);
}

MixarInteraction mixar_button_motion(const Button &button)
{
  if (!button.mixar_motion) {
    return {};
  }
  const auto &motion = *button.mixar_motion;
  return {motion.hover.value, motion.press.value, motion.selected.value};
}

MixarMotionStats mixar_motion_stats()
{
  return {uint64_t(pending.size()), ticks, redraws};
}

MixarMotionRebuild::MixarMotionRebuild(Block &block)
{
  if (!block.oldblock) {
    return;
  }
  auto &previous = block.oldblock->buttons_ptrs;
  if (std::none_of(previous.begin(),
                   previous.end(),
                   [](const auto &button) { return bool(button->mixar_motion); }))
  {
    return;
  }
  auto matches = [](const Button &next, const Button &old) {
    if (!old.mixar_motion || next.type != old.type || !button_rna_equals(&next, &old)) {
      return false;
    }
    const auto &a = next.mixar_style;
    const auto &b = old.mixar_style;
    return a.theme == b.theme && a.component == b.component && a.card == b.card &&
           a.variant == b.variant && (*old.mixar_motion).operator_identity == next.optype &&
           (next.rnaprop != nullptr || next.str == old.str);
  };
  /* Same ordinal is the common path. Moved/inserted controls use semantic
   * identity within this one old block, and moving storage consumes it once.
   * Native matching remains unchanged; already-executed operators are never
   * resurrected, and no callback, value or edit state is transferred here. */
  states_.resize(block.buttons_ptrs.size());
  for (int64_t i = 0; i < block.buttons_ptrs.size(); i++) {
    Button &next = *block.buttons_ptrs[i];
    if (i < previous.size() && matches(next, *previous[i])) {
      states_[i] = std::move(previous[i]->mixar_motion);
      continue;
    }
    for (auto &old : previous) {
      if (matches(next, *old)) {
        states_[i] = std::move(old->mixar_motion);
        break;
      }
    }
  }
}

void MixarMotionRebuild::apply(Block &block)
{
  for (int64_t i = 0; i < int64_t(states_.size()); i++) {
    block.buttons_ptrs[i]->mixar_motion = std::move(states_[i]);
  }
}
}  // namespace blender::ui
