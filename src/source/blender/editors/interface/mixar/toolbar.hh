/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

namespace blender::ui {
struct Button;
/** Practical drag limits for Zen render samples; RNA hard limits stay unchanged. */
bool mixar_toolbar_sample_range(Button &button);
}  // namespace blender::ui
