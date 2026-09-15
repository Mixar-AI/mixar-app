/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include "UI_interface.hh"

namespace blender {
/** Preserve the 616-point default's typography at every window size. Unlike
 * layout scale, this only follows the user's interface scale and display DPI.
 * Measurement, fitting and painting must all receive the same text unit. */
inline float agent_ui_text_unit()
{
  return (616.0f / 1310.0f) * UI_SCALE_FAC;
}
}  // namespace blender
