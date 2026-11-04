/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLI_rect.h"

namespace blender {
struct ARegion;
struct ScrArea;

/** Notification lane in viewport pixels: left, bottom, right, stack top, chrome ceiling.
 * An empty stack returns its resting anchor with zero height. Read-only. */
void ED_agent_panel_bounds(const ScrArea *area, const ARegion *viewport, int bounds[5]);
/** Shared task/notification close glyph and rounded hover wash. Bounds are inclusive. */
void ED_agent_panel_draw_close(const rcti &bounds, float alpha, bool hovered);
}  // namespace blender
