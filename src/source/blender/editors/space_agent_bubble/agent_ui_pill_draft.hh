/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

namespace blender {
void agent_ui_draw_pill_draft(const char *draft, float left, float right,
                              float height, float font_size, const char *voice_status);
void agent_ui_pill_draft_clear();
void agent_ui_pill_draft_qa_register();
}  // namespace blender
