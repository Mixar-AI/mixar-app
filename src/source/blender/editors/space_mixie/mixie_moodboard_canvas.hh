/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 *
 * Public entry point for painting the moodboard canvas into an arbitrary
 * region.
 *
 * The canvas itself (`mixie_draw_moodboard_mode`) is host-agnostic: it derives
 * its entire view from the `ARegion` it is handed, so a region belonging to
 * another space can host it. That is what the Zen Mode sliding drawer in
 * `space_view3d` does. This header exists so that caller does not have to
 * include `mixie_intern.hh`, which is private to this module.
 *
 * Follow the same contract `mixie_draw_moodboard_mode` documents: call it with
 * a region whose View2D already covers the canvas, from inside a draw pass
 * (it paints; it does not tag redraws).
 */

#pragma once

/* Declared where the rest of this module declares them: inside `blender`.
 * A `struct ARegion;` at global scope would land on mixie_intern.hh's
 * `using ARegion = blender::ARegion;` and fail to compile. */
namespace blender {
struct ARegion;
struct bContext;
}  // namespace blender

namespace blender::ed::mixie {

/** Paint the moodboard canvas (grid, links, images, textboxes, graph nodes)
 * into `region`, clipped to it by the region's own View2D mask. */
void mixie_moodboard_canvas_draw(const bContext *C, ARegion *region);

}  // namespace blender::ed::mixie
