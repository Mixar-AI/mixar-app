/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "UI_mixar_density.hh"

namespace blender {
struct bContext;
struct ARegion;
}

namespace blender::ed::mixie {
/* Already-resolved host geometry. Both drawing and content bounds use it. */
inline ui::MixarDensityMetrics moodboard_chrome_metrics(const float unit)
{
  return ui::mixar_density_metrics(ui::MixarDensity::Compact, unit);
}
void mixie_moodboard_chrome_draw(const bContext *C, ARegion *region);
}  // namespace blender::ed::mixie
