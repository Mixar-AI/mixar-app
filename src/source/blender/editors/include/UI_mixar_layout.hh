/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <algorithm>

namespace blender::ui {
/** A bounded half-open item range. No feature state or pixel scaling. */
struct MixarVisibleRange {
  int first = 0;
  int size = 0;
  int end() const
  {
    return first + size;
  }
};

inline MixarVisibleRange mixar_list_range(int total, int capacity, int offset)
{
  total = std::max(0, total);
  capacity = std::clamp(capacity, 0, total);
  if (capacity == 0) {
    return {};
  }
  return {std::clamp(offset, 0, total - capacity), capacity};
}

inline int mixar_page_count(int total, int capacity)
{
  return total > 0 && capacity > 0 ? 1 + (total - 1) / capacity : 1;
}

inline MixarVisibleRange mixar_page_range(int total, int capacity, int page)
{
  if (total <= 0 || capacity <= 0) {
    return {};
  }
  const int first = std::clamp(page, 0, mixar_page_count(total, capacity) - 1) * capacity;
  return {first, std::min(capacity, total - first)};
}
}  // namespace blender::ui
