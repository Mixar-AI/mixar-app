/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLI_rect.h"
#include "agent_ui_cat_activity.hh"

namespace blender {
struct ARegion;

enum class AgentIslandControl {
  Agent,
  ThreeD,
  Media,
  Splat,
  Generations,
  Queue,
  History,
  NewChat,
  Upload,
  Scribble,
  Reading,
  Clear,
  Voice,
  Generate,
  Count,
};

struct AgentIslandFeedback {
  float hover = 0.0f;
  float press = 0.0f;
  float selected = 0.0f;
};

/** One chrome paint: hidden controls discard their transient feedback. */
void agent_ui_motion_begin(ARegion *region);
void agent_ui_motion_end(ARegion *region);
AgentIslandFeedback agent_ui_motion_sample(ARegion *region,
                                           AgentIslandControl control,
                                           const rctf &window_rect,
                                           bool selected = false);
/** Blend only paint. Label, icon, layout, and native button geometry stay fixed. */
void agent_ui_motion_color(const float base[4],
                           const float selected[4],
                           AgentIslandFeedback feedback,
                           float result[4]);
void agent_ui_motion_region_free(ARegion *region);
MixieCatPose agent_ui_cat_motion_sample(
    ARegion *region, MixieCatActivity activity, double now, const void *scene, float chip_pixels);
double agent_ui_cat_motion_next_frame(const ARegion *region);
void *agent_ui_motion_region_duplicate(void *regiondata);
}  // namespace blender
