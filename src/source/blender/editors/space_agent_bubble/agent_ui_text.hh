/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include "DNA_userdef_types.h"
#include "UI_interface.hh"
#include "UI_interface_c.hh"

namespace blender {
/** Island labels are 20% larger and follow Blender's widget font preference.
 * Read the unscaled style: DPI and interface scale apply exactly once below. */
inline float agent_ui_font_preference_scale()
{
  const uiStyle *style = ui::style_get();
  const float points = style ? style->widget.points : UI_DEFAULT_TEXT_POINTS;
  return 1.2f * points / UI_DEFAULT_TEXT_POINTS;
}

/** Keep typography fixed across window resizes, following Blender's font
 * preference, interface scale and display DPI instead of responsive geometry.
 * Measurement, fitting and painting must all receive the same text unit. */
inline float agent_ui_text_unit()
{
  return (616.0f / 1310.0f) * UI_SCALE_FAC * agent_ui_font_preference_scale();
}
}  // namespace blender
