/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

namespace blender {
struct ARegion;
struct bContext;
namespace ed::mixie {
void moodboard_first_use_draw(const bContext *C, ARegion *region);
}  // namespace ed::mixie
}  // namespace blender
