/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <algorithm>
#include <string_view>

namespace blender::ed::mixie::socket_style {

inline constexpr float IMAGE[3] = {0.29f, 0.76f, 0.83f};
inline constexpr float VIDEO[3] = {0.67f, 0.57f, 0.87f};
inline constexpr float MESH[3] = {0.40f, 0.78f, 0.64f};
inline constexpr float MIXED[3] = {0.60f, 0.65f, 0.72f};
inline constexpr float NEUTRAL[3] = {0.56f, 0.60f, 0.65f};

/** The backend publishes comma-separated type identifiers, never substrings. */
inline const float *type_color(std::string_view types)
{
  unsigned kinds = 0;
  while (!types.empty()) {
    const size_t end = types.find(',');
    const std::string_view type = types.substr(0, end);
    if (type == "IMAGE") {
      kinds |= 1;
    }
    else if (type == "VIDEO") {
      kinds |= 2;
    }
    else if (type == "MESH") {
      kinds |= 4;
    }
    else {
      return NEUTRAL;
    }
    if (end == std::string_view::npos) {
      break;
    }
    types.remove_prefix(end + 1);
    if (types.empty()) {
      return NEUTRAL;
    }
  }
  switch (kinds) {
    case 0:
      return NEUTRAL;
    case 1:
      return IMAGE;
    case 2:
      return VIDEO;
    case 4:
      return MESH;
    default:
      return MIXED;
  }
}

/** Canvas centers keep their geometry; only the affordance size is bounded. */
inline float radius_px(float zoom, float ui_scale, bool output)
{
  const float minimum = (output ? 8.0f : 6.0f) * ui_scale;
  const float maximum = (output ? 10.0f : 8.0f) * ui_scale;
  return std::clamp((output ? 15.0f : 12.0f) * zoom, minimum, maximum);
}

inline float hit_radius_px(float zoom, float ui_scale, bool output)
{
  return std::max(12.0f * ui_scale, radius_px(zoom, ui_scale, output) + 4.0f * ui_scale);
}

}  // namespace blender::ed::mixie::socket_style
