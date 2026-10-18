/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

namespace blender {

/* Coordinates and dimensions are framebuffer pixels. Bits match xdg resize edges. */
inline int agent_bubble_resize_edges(int x, int y, int width, int height, int margin)
{
  if (x < 0 || y < 0 || x >= width || y >= height) {
    return 0;
  }
  const int horizontal = x < margin ? 4 : x >= width - margin ? 8 : 0;
  const int vertical = y < margin ? 2 : y >= height - margin ? 1 : 0;
  return horizontal | vertical;
}

}  // namespace blender
