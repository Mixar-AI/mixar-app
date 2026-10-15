/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * sRGB transfer helpers for the Scenes drawer's viewport snapshots
 * (`view3d_scenes_drawer_thumbs.cc`), kept apart for the 500-line rule.
 */

#pragma once

#include <algorithm>
#include <cmath>

namespace blender::view3d_scenes_drawer {

/** Encode one linear channel for display (sRGB piecewise curve). */
inline float srgb_encode(const float v)
{
  const float c = std::clamp(v, 0.0f, 1.0f);
  return c <= 0.0031308f ? c * 12.92f : 1.055f * std::pow(c, 1.0f / 2.4f) - 0.055f;
}

/** The overlay texture is sRGB-encoded storage read back raw: decode a byte
 * to linear the way sampling it in a shader would. */
inline float srgb_decode_byte(const unsigned char b)
{
  static float lut[256];
  static bool ready = false;
  if (!ready) {
    for (int i = 0; i < 256; i++) {
      const float c = float(i) / 255.0f;
      lut[i] = c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f);
    }
    ready = true;
  }
  return lut[b];
}

}  // namespace blender::view3d_scenes_drawer
