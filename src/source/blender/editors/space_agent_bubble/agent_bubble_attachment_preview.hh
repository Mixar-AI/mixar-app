/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

namespace blender {
struct bContext;
struct PointerRNA;
namespace ui {
struct Block;
}
void agent_bubble_attachment_preview_button(
    const bContext *C, ui::Block *block, PointerRNA *item, int x, int y, int size);
}  // namespace blender
