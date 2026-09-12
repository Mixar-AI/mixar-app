/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <cstdint>

namespace blender {
/** Read-only native mascot scheduling counters for the QA harness. */
struct AgentBubbleMotionStats {
  uint64_t ticks, redraws, fast_frames, quiet_frames;
  bool scheduled, awaiting_draw;
  double next_frame_seconds;
};
AgentBubbleMotionStats ED_agent_bubble_motion_stats();
}  // namespace blender
