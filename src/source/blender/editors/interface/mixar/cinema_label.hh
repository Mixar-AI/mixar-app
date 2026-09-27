/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

struct rcti;
struct rctf;

namespace blender::ui {
/** Shared Cinema Mode button typography for the Zen toolbar and Engine topbar. */
void mixar_cinema_background(const rctf &bounds, float radius, float selected, float emphasis);
/** Gradient label with an optional leading icon (start colour) and a small raised
 * "V1" marker (end colour); the three are fitted together inside `bounds`. */
void mixar_cinema_label(const rcti &bounds,
                        const char *label,
                        float selected,
                        bool disabled = false,
                        int icon_id = 0);
}  // namespace blender::ui
