/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <cmath>

#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "UI_mixar_custom_motion.hh"

#include "interface_intern.hh"

namespace blender::ui {
MixarCustomButtonState mixar_region_button_state(const ARegion *region, const rctf &rect)
{
  if (!region || !region->runtime) {
    return {};
  }
  for (const Block &block : region->runtime->uiblocks) {
    /* The painter runs before the next block rebuild. `active` may already
     * have been cleared by free-inactive; the name map identifies the latest
     * block without retaining pointers across a redraw. */
    if (region->runtime->block_name_map.lookup_default(block.name, nullptr) != &block) {
      continue;
    }
    for (const Button &button : block.buttons()) {
      /* Native placement truncates origin and size separately. Match that rectangle,
       * not the pointer position, so disabled and modal states stay native. */
      if (std::abs(button.rect.xmin - rect.xmin) > 2.0f ||
          std::abs(button.rect.xmax - rect.xmax) > 2.0f ||
          std::abs(button.rect.ymin - rect.ymin) > 2.0f ||
          std::abs(button.rect.ymax - rect.ymax) > 2.0f)
      {
        continue;
      }
      const bool disabled = (button.flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
      return {!disabled && (button.flag & UI_HOVER) != 0,
              !disabled && (button.flag & UI_SELECT) != 0 &&
                  ELEM(button.type,
                       ButtonType::But,
                       ButtonType::Menu,
                       ButtonType::Block,
                       ButtonType::Popover),
              disabled};
    }
  }
  return {};
}
}  // namespace blender::ui
