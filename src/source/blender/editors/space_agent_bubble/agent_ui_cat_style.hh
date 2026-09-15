/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <algorithm>
#include <array>
#include <cstddef>

namespace blender {

using std::size_t;

/** All cats share the ink silhouette; eyes and ear proportions give each a
 * personality. */
struct MixieCatStyle {
  const char *name;
  std::array<float, 4> eyes;
  std::array<float, 4> chip_shadow;
  std::array<float, 4> chip_light;
  float ear_left;
  float ear_right;
  float cheek_width;
  float tilt;
};

/* Reserve green for Free: every paid/trial palette uses a separate non-green hue. */
constexpr std::array<MixieCatStyle, 6> MIXIE_CAT_STYLES = {{
    {"Emerald", {0.00f, 0.78f, 0.28f, 1.0f},
     {32 / 255.0f, 88 / 255.0f, 54 / 255.0f, 1.0f}, /* #205836 */
     {58 / 255.0f, 132 / 255.0f, 87 / 255.0f, 1.0f}, /* #3A8457 */
     1.00f, 1.00f, 1.00f, 12.0f},
    {"Amber", {1.00f, 0.68f, 0.18f, 1.0f},
     {110 / 255.0f, 73 / 255.0f, 36 / 255.0f, 1.0f}, /* #6E4924 */
     {174 / 255.0f, 125 / 255.0f, 62 / 255.0f, 1.0f}, /* #AE7D3E */
     0.78f, 0.94f, 1.06f, 7.0f},
    {"Rose", {1.00f, 0.30f, 0.62f, 1.0f},
     {113 / 255.0f, 49 / 255.0f, 79 / 255.0f, 1.0f}, /* #71314F */
     {173 / 255.0f, 98 / 255.0f, 130 / 255.0f, 1.0f}, /* #AD6282 */
     1.08f, 0.80f, 0.96f, -5.0f},
    {"Lilac", {0.72f, 0.57f, 0.98f, 1.0f},
     {81 / 255.0f, 64 / 255.0f, 111 / 255.0f, 1.0f}, /* #51406F */
     {137 / 255.0f, 113 / 255.0f, 175 / 255.0f, 1.0f}, /* #8971AF */
     0.88f, 0.88f, 1.04f, 10.0f},
    {"Sky", {0.28f, 0.68f, 1.00f, 1.0f},
     {38 / 255.0f, 79 / 255.0f, 108 / 255.0f, 1.0f}, /* #264F6C */
     {77 / 255.0f, 130 / 255.0f, 168 / 255.0f, 1.0f}, /* #4D82A8 */
     1.05f, 1.05f, 0.96f, -8.0f},
    {"Coral", {1.00f, 0.32f, 0.22f, 1.0f},
     {116 / 255.0f, 63 / 255.0f, 53 / 255.0f, 1.0f}, /* #743F35 */
     {181 / 255.0f, 114 / 255.0f, 88 / 255.0f, 1.0f}, /* #B57258 */
     0.92f, 0.76f, 1.03f, 4.0f},
}};

/** Soft activity light preserves the chip hue instead of adding green. */
inline std::array<float, 4> mixie_cat_chip_color(std::array<float, 4> color,
                                               const float pulse)
{
  const float light = 0.12f * std::clamp(pulse, 0.0f, 1.0f);
  for (int channel = 0; channel < 3; channel++) {
    color[channel] += (1.0f - color[channel]) * light;
  }
  return color;
}

inline const MixieCatStyle &mixie_cat_style(const int ordinal)
{
  return MIXIE_CAT_STYLES[size_t(ordinal < 0 ? 0 : ordinal) % MIXIE_CAT_STYLES.size()];
}

/** Map ``users.subscription_type`` onto MIXIE_CAT_STYLES for the MAIN chat cat.
 *
 * Reserved backend tiers: 0 is free, 4 is trial (`modules/plans`). Paid
 * identities are the remaining stable integers. Unmapped, negative, or
 * unknown values return Emerald — today's default — not a wrap. Parallel
 * cards keep using #mixie_cat_style, which still wraps by ordinal.
 */
inline int mixie_cat_style_index_for_tier(const int tier)
{
  switch (tier) {
    case 0:
      return 0; /* Free → Emerald */
    case 1:
      return 1; /* Amber */
    case 2:
      return 2; /* Rose */
    case 3:
      return 3; /* Lilac */
    case 4:
      return 4; /* Trial → Sky */
    case 5:
      return 5; /* Coral */
    default:
      return 0;
  }
}

inline const MixieCatStyle &mixie_cat_style_for_tier(const int tier)
{
  return MIXIE_CAT_STYLES[size_t(mixie_cat_style_index_for_tier(tier))];
}

}  // namespace blender
