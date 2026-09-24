/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include "DNA_userdef_types.h"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar_text.hh"

namespace blender {
/** Same pixel size as ordinary Blender widget text, without an island ratio. */
inline float agent_ui_body_font_size()
{
  const uiStyle *style = ui::style_get();
  const float points = style ? style->widget.points : UI_DEFAULT_TEXT_POINTS;
  return points * UI_SCALE_FAC;
}

/** Keep typography fixed across window resizes, following Blender's font
 * preference, interface scale and display DPI instead of responsive geometry.
 * Measurement, fitting and painting must all receive the same text unit. */
inline float agent_ui_text_unit()
{
  return agent_ui_body_font_size() / ui::mixar_text_role_size(ui::MixarTextRole::Body);
}
}  // namespace blender
