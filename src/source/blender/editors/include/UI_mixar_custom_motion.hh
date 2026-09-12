/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLI_rect.h"

namespace blender {
struct ARegion;
}

namespace blender::ui {
/** Custom paint reads the real button's interaction, using its existing
 * region-local rectangle. This does not perform a second hit test. */
struct MixarCustomButtonState {
  bool hover = false;
  bool press = false;
  bool disabled = false;
};
MixarCustomButtonState mixar_region_button_state(const ARegion *region, const rctf &rect);
}  // namespace blender::ui
