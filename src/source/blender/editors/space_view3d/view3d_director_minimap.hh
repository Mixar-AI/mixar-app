/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The aerial map: the internals shared by the render half
 * (`view3d_director_minimap.cc`) and the painter half
 * (`view3d_director_minimap_draw.cc`), and the public API — the painter
 * entry, the pixel<->world queries and the teardown — which moved here from
 * `view3d_director_cinema.hh` when that header crossed the 500-line rule.
 */

#pragma once

#include "DNA_object_types.h"
#include "DNA_vec_types.h"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct Depsgraph;
struct GPUViewport;
struct bContext;

/* The card painter takes a block. Forward-declared exactly as
 * `view3d_director_cinema.hh` does it — `blender::ui` already exists (DNA
 * declares it), but `Block` is only a name in it once someone says so. */
namespace ui {
struct Block;
}
struct DirectorViewState;

/** Objects that carry no geometry the map should trace — not drawn, not measured. */
constexpr int MINIMAP_HIDDEN_TYPES = (1 << OB_CAMERA) | (1 << OB_LAMP) | (1 << OB_SPEAKER) |
                                     (1 << OB_EMPTY) | (1 << OB_LIGHTPROBE);

/* -------------------------------------------------------------------- */
/** \name view3d_director_minimap_extents.cc
 * \{ */

struct WorldExtents {
  rctf xy = {};
  float zmin = 0.0f;
  float zmax = 0.0f;
  bool any = false;
};

/** Union of the evaluated, visible, geometry-carrying objects' world boxes. */
WorldExtents view3d_director_minimap_scene_extents(Depsgraph *depsgraph);

/**
 * The world rect the map shows: scene bounds padded by 10 % (at least 2 m),
 * grown to include the shot camera (\a camera_xy, or null) plus its marker's
 * extent (\a margin_px, dot radius + wedge length, converted to world units
 * from the PRE-margin rect's scale and corrected so it is at least that many
 * pixels in the final rect), then fitted to the \a w x \a h pixel aspect by
 * growing the shorter world axis symmetrically. \a r_inset_px receives the
 * margin's size in FINAL pixels: placements clamped that far inside the
 * rect can never push the union past the camera's current position, so the
 * rect grows only when the camera arrives at the boundary from elsewhere
 * (initial pose, nudge, walk), and then only once.
 */
rctf view3d_director_minimap_fit_world(const WorldExtents &extents,
                                       const float *camera_xy,
                                       float margin_px,
                                       int w,
                                       int h,
                                       int *r_inset_px);

/** Whether \a b differs from \a a beyond a fraction of \a a's size. */
bool view3d_director_minimap_world_changed(const rctf &a, const rctf &b);

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_director_minimap.cc
 * \{ */

/**
 * Decide whether the cached render is current for \a map (inclusive region
 * px), render if due, and restore the region's framebuffer/viewport/scissor
 * and pixel space afterwards. \a camera_xy is the shot camera's world XY or
 * null; \a margin_px the marker's extent kept inside the map. Returns whether
 * a render is available to blit; \a r_world receives the world rect that
 * render shows and \a r_inset_px the placement clamp that goes with it.
 */
bool view3d_director_minimap_update(const bContext *C,
                                    const ARegion *region,
                                    const rcti &map,
                                    const float *camera_xy,
                                    float margin_px,
                                    rctf *r_world,
                                    int *r_inset_px);

/** The viewport holding the last render (null before the first). */
GPUViewport *view3d_director_minimap_viewport();

/**
 * Publish this draw's pixel<->world transform for the placement modal.
 * \a inset_px keeps placements that far inside the rect so the marker never
 * sits on the edge; \a valid false drops the transform.
 */
void view3d_director_minimap_publish(
    const ARegion *region, const rcti &map, const rctf &world, int inset_px, bool valid);

/** Free buffers queued for release; needs a bound GPU context (call from a draw). */
void view3d_director_minimap_garbage_flush();

/** \} */

/* -------------------------------------------------------------------- */
/** \name Aerial map (view3d_director_minimap.cc)
 *
 * The right column's preview card is a LIVE top-down orthographic render of
 * the scene (world XY, +X right, +Y up) with the shot camera marked on it.
 * The render is an offscreen pass cached in a file-static and re-run only
 * when the map's world extents, the depsgraph or the card size change; the
 * marker, the track-target dot and the caption are painted every redraw.
 * The painter publishes its pixel<->world transform so the placement modal
 * (`MIXAR_OT_director_place_camera`, bound to LEFTMOUSE in
 * `director/ui/keymap.py`) can map a press back to world XY. No invisible
 * button is laid over the map: a uiBut would swallow the press before the
 * keymap sees it.
 * \{ */

/** Paint the card at \a card (design `PREVIEW_Y`, `CINEMA_PREVIEW_H`). */
void cinema_draw_minimap(ui::Block *block,
                         const bContext *C,
                         const ARegion *region,
                         const DirectorViewState &state,
                         const rctf &card);

/**
 * World XY under region-local pixel (\a x, \a y) on \a region's map, clamped
 * to the map's placeable area. False when \a region drew no map this frame.
 */
bool view3d_director_minimap_world_from_region_px(const ARegion *region,
                                                  int x,
                                                  int y,
                                                  float r_xy[2]);

/** Whether region-local pixel (\a x, \a y) lies on \a region's drawn map. */
bool view3d_director_minimap_contains(const ARegion *region, int x, int y);

/**
 * Drop the map's transform for \a region, and with \a free_gpu (only from a
 * draw, where a GPU context is bound) free its render buffers when \a region
 * owns them. Called by the overlay on every draw that shows no map.
 */
void view3d_director_minimap_release(const ARegion *region, bool free_gpu);

/**
 * Queue every GPU buffer for release and forget the transform. Needs no GPU
 * context: the queue is flushed by the next map draw or by
 * #view3d_director_minimap_region_free.
 */
void view3d_director_minimap_free();

/** \} */

}  // namespace blender
