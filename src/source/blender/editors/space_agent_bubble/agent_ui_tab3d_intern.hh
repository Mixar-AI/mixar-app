/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Shared internals of the island's 3D tab (agent_ui_tab3d.cc +
 * agent_ui_tab3d_params.cc). Tokens are ISLAND units measured off
 * `3d.svg` (island origin at artboard 267,340 — the same frame grid as
 * agent_ui_theme.hh; this header only ADDS tokens, the shared ones stay
 * in the theme header).
 */

#pragma once

#include "BLI_rect.h"
#include "RNA_types.hh"

#include "agent_ui_pane_kit.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct bContext;
namespace ui {
struct Block;
}

/* -------------------------------------------------------------------- */
/** \name Design tokens (island units) — 3d.svg
 * \{ */

/* Pane metrics/colours come from the pane kit; this header keeps only
 * the params-strip API below. */
/** \} */

/* -------------------------------------------------------------------- */
/** \name Shared painter helpers (agent_ui_tab3d.cc)
 * \{ */

/* Painter primitives live in the pane kit (agent_ui_pane_kit.hh). */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Params strip (agent_ui_tab3d_params.cc)
 * \{ */

/**
 * Paint + bind the schema params of the ACTIVE (service, model) as island
 * chips, flowing left-to-right from (\a x0, \a y0_top) in region pixels,
 * wrapping by the row pitch, never below \a y_floor. Enum params with <= 4
 * items render as a segmented control (each segment a `wm.context_set_enum`),
 * larger enums as a dropdown chip opening `wm.context_menu_enum`; booleans as
 * an ON/OFF chip on `wm.context_toggle`; ints/floats as a chip hosting a real
 * embossed NumSlider bound straight to the group property.
 *
 * \param group_ptr: the WindowManager param-group instance (engine-registered).
 * \param group_path: bpy.context-relative path to it, for the context ops.
 * \param chips_block: unembossed block for the painted controls.
 * \param slider_block: embossed block for NumSlider widgets.
 */
float agent_ui_tab3d_params_draw(const bContext *C,
                                PointerRNA *group_ptr,
                                const char *group_path,
                                ui::Block *chips_block,
                                ui::Block *slider_block,
                                float x0,
                                float row_start_x,
                                float y0_top,
                                float x_max,
                                float y_floor,
                                float u);

/** \} */

}  // namespace blender
