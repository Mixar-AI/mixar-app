/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include <algorithm>
#include <cmath>

namespace blender::view3d_scenes_drawer {

/** Card rows keep their identities while an empty slot moves through the list. */
inline int reorder_preview_row(const int index, const int source, const int slot)
{
  const int destination = slot > source ? slot - 1 : slot;
  if (index == source) {
    return destination;
  }
  if (destination < source && index >= destination && index < source) {
    return index + 1;
  }
  if (destination > source && index > source && index <= destination) {
    return index - 1;
  }
  return index;
}

/** Time-based ease with no overshoot, including rapid direction reversals.
 * A fixed elapsed time produces the same position at every frame rate. */
inline float follow_position(const float current, const float target, const double seconds)
{
  return target + (current - target) * float(std::exp(-35.0 * std::max(0.0, seconds)));
}

constexpr double CARD_SETTLE_SECONDS = 0.18;

}  // namespace blender::view3d_scenes_drawer
