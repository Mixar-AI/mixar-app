/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <algorithm>

namespace blender::ui {
/** Bounded row flow in host-resolved units. Oversized items get one full row;
 * callers must fit their contents or substitute a compact control. */
struct MixarFlowRect {
  float xmin, xmax, ymin, ymax;
};
struct MixarFlow {
  float x = 0, x0 = 0, x_max = 0, y_top = 0, y_floor = 0;
  float row_height = 0, row_pitch = 0, gap = 0;
  bool out_of_room = false;

  bool place(float desired_width, MixarFlowRect &rect)
  {
    if (out_of_room) {
      return false;
    }
    const float width = std::min(desired_width, x_max - x0);
    float next_x = x, next_top = y_top;
    if (next_x + width > x_max && next_x > x0) {
      next_x = x0;
      next_top -= row_pitch;
    }
    if (width <= 0 || row_height <= 0 || next_top - row_height < y_floor ||
        next_x + width > x_max)
    {
      out_of_room = true;
      return false;
    }
    rect = {next_x, next_x + width, next_top - row_height, next_top};
    x = rect.xmax + gap;
    y_top = next_top;
    return true;
  }
};

/** Host-resolved distances; no DPI scaling or feature state in the layout layer. */
struct MixarComposerMetrics {
  float action_height;
  float bottom_padding;
  float gap;
  float minimum_field_height;

  float minimum_height() const
  {
    return action_height + bottom_padding + gap + minimum_field_height;
  }
};

struct MixarComposerLayout {
  float action_bottom, action_top;
  float field_bottom, field_top;
  bool editable;
};

/** Reserve the action row first. A short composer never exposes an overlapping field. */
inline MixarComposerLayout mixar_composer_layout(float bottom,
                                                float top,
                                                const MixarComposerMetrics &metrics)
{
  top = std::max(bottom, top);
  const float action_height = std::max(0.0f, metrics.action_height);
  const float action_bottom = std::clamp(top - action_height,
                                       bottom,
                                       bottom + std::max(0.0f, metrics.bottom_padding));
  const float action_top = std::min(top, action_bottom + action_height);
  const float field_bottom = std::min(top, action_top + std::max(0.0f, metrics.gap));
  const bool editable = top - field_bottom >= metrics.minimum_field_height && top > field_bottom;
  return {action_bottom, action_top, editable ? field_bottom : top, top, editable};
}

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
