/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

struct rcti;
namespace blender {
struct ARegion;
namespace ui {
struct Button;
struct Block;
bool mixar_scenes_toggle_is_button(const Button &button);
void mixar_scenes_toggle_layout(ARegion *region, Block *block);
void mixar_scenes_toggle_draw(const Button &button, const rcti &bounds);
}  // namespace ui
}  // namespace blender
