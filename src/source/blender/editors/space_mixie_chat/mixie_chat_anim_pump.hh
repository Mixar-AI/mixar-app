/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

namespace blender {
struct bContext;
struct wmWindowManager;

/** Draw-side animations renew a bounded request for 30 Hz main-region redraws. */
void mixie_chat_anim_pump_request(const bContext *C, bool anim_active);
/** Called by our notifier, including when a native window is hidden. */
void mixie_chat_anim_pump_tick();
void mixie_chat_anim_pump_shutdown(wmWindowManager *wm);
}  // namespace blender
