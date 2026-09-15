/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <array>

namespace blender {

/** All cats share the ink silhouette; eyes and ear proportions give each a
 * personality. */
struct MixieCatStyle {
  const char *name;
  std::array<float, 4> eyes;
  float ear_left;
  float ear_right;
  float cheek_width;
  float tilt;
};

constexpr std::array<MixieCatStyle, 6> MIXIE_CAT_STYLES = {{
    {"Emerald", {0.00f, 0.78f, 0.28f, 1.0f}, 1.00f, 1.00f, 1.00f, 12.0f},
    {"Amber", {1.00f, 0.68f, 0.18f, 1.0f}, 0.78f, 0.94f, 1.06f, 7.0f},
    {"Lagoon", {0.15f, 0.83f, 0.77f, 1.0f}, 1.08f, 0.80f, 0.96f, -5.0f},
    {"Lilac", {0.72f, 0.57f, 0.98f, 1.0f}, 0.88f, 0.88f, 1.04f, 10.0f},
    {"Sky", {0.28f, 0.68f, 1.00f, 1.0f}, 1.05f, 1.05f, 0.96f, -8.0f},
    {"Lime", {0.65f, 0.87f, 0.26f, 1.0f}, 0.92f, 0.76f, 1.03f, 4.0f},
}};

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
      return 2; /* Lagoon */
    case 3:
      return 3; /* Lilac */
    case 4:
      return 4; /* Trial → Sky */
    case 5:
      return 5; /* Lime */
    default:
      return 0;
  }
}

inline const MixieCatStyle &mixie_cat_style_for_tier(const int tier)
{
  return MIXIE_CAT_STYLES[size_t(mixie_cat_style_index_for_tier(tier))];
}

}  // namespace blender
