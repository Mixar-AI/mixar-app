/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>
#include <array>

#include "MEM_guardedalloc.h"

#include "BLI_utildefines.h"

#include "DNA_screen_types.h"

#include "UI_mixar_custom_motion.hh"
#include "UI_mixar_motion.hh"

#include "agent_ui_motion.hh"

namespace blender {
namespace {
struct ControlMotion {
  ui::MixarMotionValue hover, press, selected;
  bool initialized = false;
  bool sampled = false;
};
struct AgentIslandMotion {
  std::array<ControlMotion, int(AgentIslandControl::Count)> controls;
  MixieCatMotion cat;
  const void *cat_scene = nullptr;
};
}  // namespace

MixieCatPose agent_ui_cat_motion_sample(ARegion *region,
                                        const MixieCatActivity activity,
                                        const double now,
                                        const void *scene)
{
  if (!region->regiondata) {
    region->regiondata = MEM_new<AgentIslandMotion>("Agent island motion");
  }
  auto &motion = *static_cast<AgentIslandMotion *>(region->regiondata);
  if (motion.cat_scene != scene) {
    motion.cat = {};
    motion.cat_scene = scene;
  }
  return motion.cat.sample(now, activity);
}

void agent_ui_motion_begin(ARegion *region)
{
  if (ELEM(region->regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOLS) && region->regiondata) {
    for (ControlMotion &motion : static_cast<AgentIslandMotion *>(region->regiondata)->controls) {
      motion.sampled = false;
    }
  }
}

void agent_ui_motion_end(ARegion *region)
{
  if (ELEM(region->regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOLS) && region->regiondata) {
    for (ControlMotion &motion : static_cast<AgentIslandMotion *>(region->regiondata)->controls) {
      if (!motion.sampled) {
        motion = {};
      }
    }
  }
}

AgentIslandFeedback agent_ui_motion_sample(ARegion *region,
                                           const AgentIslandControl control,
                                           const rctf &window_rect,
                                           const bool selected)
{
  /* The island is painted in three clipped regions. Only its actual chrome
   * owners keep state: the transcript region belongs to the chat runtime. */
  if (!ELEM(region->regiontype, RGN_TYPE_HEADER, RGN_TYPE_TOOLS) ||
      window_rect.ymax <= region->winrct.ymin || window_rect.ymin >= region->winrct.ymax)
  {
    return {0.0f, 0.0f, float(selected)};
  }
  if (!region->regiondata) {
    region->regiondata = MEM_new<AgentIslandMotion>("Agent island motion");
  }
  auto &motion = static_cast<AgentIslandMotion *>(region->regiondata)->controls[int(control)];
  motion.sampled = true;
  if (!motion.initialized) {
    motion.hover.settle(0.0f);
    motion.press.settle(0.0f);
    motion.selected.settle(float(selected));
    motion.initialized = true;
  }
  rctf local = window_rect;
  BLI_rctf_translate(&local, -float(region->winrct.xmin), -float(region->winrct.ymin));
  const ui::MixarCustomButtonState state = ui::mixar_region_button_state(region, local);
  if (state.disabled) {
    motion.hover.settle(0.0f);
    motion.press.settle(0.0f);
  }
  return {ui::mixar_motion_step(
              motion.hover, float(state.hover), ui::mixar_motion::hover_seconds, region),
          ui::mixar_motion_step(motion.press,
                                float(state.press),
                                state.press ? ui::mixar_motion::press_seconds :
                                              ui::mixar_motion::hover_seconds,
                                region),
          ui::mixar_motion_step(
              motion.selected, float(selected), ui::mixar_motion::selection_seconds, region)};
}

void agent_ui_motion_color(const float base[4],
                           const float selected[4],
                           const AgentIslandFeedback feedback,
                           float result[4])
{
  for (int channel = 0; channel < 3; channel++) {
    const float value = base[channel] + (selected[channel] - base[channel]) * feedback.selected;
    result[channel] = std::clamp(
        value + 0.055f * feedback.hover - 0.035f * feedback.press, 0.0f, 1.0f);
  }
  result[3] = base[3] + (selected[3] - base[3]) * feedback.selected;
}

void agent_ui_motion_region_free(ARegion *region)
{
  if (region->regiondata) {
    MEM_delete(static_cast<AgentIslandMotion *>(region->regiondata));
  }
  region->regiondata = nullptr;
}

void *agent_ui_motion_region_duplicate(void * /*regiondata*/)
{
  return nullptr;
}
}  // namespace blender
