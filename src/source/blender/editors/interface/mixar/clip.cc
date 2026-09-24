/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "../interface_intern.hh"
#include "UI_mixar.hh"
#include "GPU_state.hh"

namespace blender::ui {

void mixar_block_clip_set(Block *block, const rctf &rect)
{
  block->mixar_clip_rect = rect;
}

bool mixar_block_clip_pixelrect(const ARegion *region, const Block *block, rcti *rect)
{
  if (!block->mixar_clip_rect) {
    return true;
  }
  const rcti clip = rect_to_pixelrect(region, block, &*block->mixar_clip_rect);
  return BLI_rcti_isect(rect, &clip, rect) && BLI_rcti_size_x(rect) > 0 &&
         BLI_rcti_size_y(rect) > 0;
}

void mixar_block_clip_apply(const ARegion *region, const Block *block)
{
  if (!block->mixar_clip_rect) {
    return;
  }
  int scissor[4];
  GPU_scissor_get(scissor);
  rcti clipped = {scissor[0], scissor[0] + scissor[2],
                  scissor[1], scissor[1] + scissor[3]};
  if (mixar_block_clip_pixelrect(region, block, &clipped)) {
    GPU_scissor(clipped.xmin, clipped.ymin,
                BLI_rcti_size_x(&clipped), BLI_rcti_size_y(&clipped));
  }
  else {
    GPU_scissor(0, 0, 0, 0);
  }
}

}  // namespace blender::ui
