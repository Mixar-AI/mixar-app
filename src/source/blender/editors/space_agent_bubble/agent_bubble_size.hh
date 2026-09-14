/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <algorithm>

namespace blender {
struct AgentBubbleSize {
  int width;
  int height;
};
/* Logical OS units, before backing-pixel conversion. Keep the tab strip,
 * status pill, and viewport margins inside the host on smaller displays. */
inline AgentBubbleSize agent_bubble_fit_size(AgentBubbleSize desired, AgentBubbleSize host)
{
  if (host.width <= 0 || host.height <= 0) {
    return desired;
  }
  const int available_width = std::max(1, host.width - 48);
  const int available_height = std::max(1, host.height - 112);
  desired.width = std::min(desired.width, available_width);
  desired.height = std::min(desired.height, available_height);
  /* Chrome is width-relative. Keep its minimum aspect ratio drawable when
   * an unusually short host would otherwise clip away the composer. */
  desired.width = std::min(desired.width, desired.height * 3);
  return desired;
}
}  // namespace blender
