/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

namespace blender {
struct bContext;
struct wmOperatorType;
namespace ui {
struct Block;
}
void MIXIE_OT_moodboard_drop_template(wmOperatorType *ot);
namespace ed::mixie {
void moodboard_template_drag_buttons(const bContext *C, ui::Block *block);
void moodboard_template_dropboxes();
}
}  // namespace blender
