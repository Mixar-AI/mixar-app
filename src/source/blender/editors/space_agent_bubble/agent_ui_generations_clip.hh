/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLF_api.hh"
#include "BLI_rect.h"
#include "GPU_state.hh"

namespace blender {
/** Restrict painting to a scroll viewport, preserving the region's scissor. */
class GenViewportClip {
  int previous_[4];

 public:
  explicit GenViewportClip(const rctf &view)
  {
    BLF_batch_draw_flush();
    GPU_scissor_get(previous_);
    rcti rect = {int(view.xmin), int(view.xmax), int(view.ymin), int(view.ymax)};
    const rcti parent = {previous_[0],
                         previous_[0] + previous_[2],
                         previous_[1],
                         previous_[1] + previous_[3]};
    if (!BLI_rcti_isect(&rect, &parent, &rect)) {
      rect = {};
    }
    GPU_scissor(rect.xmin, rect.ymin, BLI_rcti_size_x(&rect), BLI_rcti_size_y(&rect));
  }

  ~GenViewportClip()
  {
    BLF_batch_draw_flush();
    GPU_scissor(previous_[0], previous_[1], previous_[2], previous_[3]);
  }
};
}  // namespace blender
