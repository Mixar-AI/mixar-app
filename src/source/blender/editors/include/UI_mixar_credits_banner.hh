/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup editorui
 *
 * Out-of-credits banner (`MIXAR_OT_credits_banner`): a whole-window overlay
 * opened from Python when the user runs out of credits.
 */

#pragma once

namespace blender {

/** Register the banner operator and its QA targets (once, at startup). */
void ED_mixar_credits_banner_register();

}  // namespace blender
