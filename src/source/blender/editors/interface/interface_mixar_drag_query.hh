/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar: ask whether the button under the cursor owns the current press
 * because it is waiting to start its own drag.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;

/**
 * True when the region's active (hovered) button carries drag data.
 *
 * Blender answers a LEFTMOUSE press over such a button with
 * #WM_UI_HANDLER_CONTINUE (`ui_do_but_EXIT`) so a region keymap can still
 * select while the button waits to see whether the gesture becomes a drag.
 * Any handler that runs later — a window-level keymap in particular — must
 * therefore stand down rather than treat that press as its own.
 */
bool UI_mixar_region_active_but_is_draggable(ARegion *region);

}  // namespace blender
