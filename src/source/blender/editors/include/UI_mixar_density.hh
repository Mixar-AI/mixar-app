/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "UI_mixar_types.hh"

namespace blender::ui {

/** Artboard spacing for a density, not pixels. Hosts multiply by their resolved
 * unit exactly once. Compact is the denser chrome recipe; Default is the
 * generation-pane chip. List rows keep their own feature metrics. */
constexpr MixarDensityMetrics mixar_density_unscaled(const MixarDensity density)
{
  switch (density) {
    case MixarDensity::Default:
      return {44.0f, 20.0f, 12.0f, 18.0f, 8.0f, 14.0f};
    case MixarDensity::Compact:
      return {32.0f, 12.0f, 8.0f, 16.0f, 6.0f, 10.0f};
  }
  return {44.0f, 20.0f, 12.0f, 18.0f, 8.0f, 14.0f};
}

constexpr MixarDensityMetrics mixar_density_metrics(const MixarDensity density,
                                                    const float host_unit)
{
  const MixarDensityMetrics raw = mixar_density_unscaled(density);
  return {raw.control_height * host_unit,
          raw.padding * host_unit,
          raw.gap * host_unit,
          raw.icon * host_unit,
          raw.icon_gap * host_unit,
          raw.radius * host_unit};
}

constexpr float mixar_density_scale(const MixarDensity density)
{
  return mixar_density_unscaled(density).control_height /
         mixar_density_unscaled(MixarDensity::Default).control_height;
}

}  // namespace blender::ui
