/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 *
 * Canvas geometry that the draw pass, the hit-test and the drag all resolve
 * through: resize handles and canvas frames.
 *
 * Split out of `mixie_intern.hh` for the 500-line rule. That header includes
 * this one, so every translation unit sees these declarations exactly where it
 * saw them before and no include list had to change.
 */

#pragma once

/* rctf is taken by reference and returned by pointer throughout. */
#include "DNA_vec_types.h"

#include "RNA_types.hh"

namespace blender {
struct Scene;
}  // namespace blender
using Scene = blender::Scene;

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Resize Handles (mixie_moodboard_resize_handles.cc)
 *
 * The ONE definition of a resize handle on this canvas. Every resizable thing
 * -- a reference image, a movie, a text box, an inference card -- wears the
 * same four corner squares and resizes by the same rule: the OPPOSITE corner
 * is anchored and the gesture is a uniform scale about it. Draw, hit-test and
 * drag all resolve through here, so the squares the user aims at cannot drift
 * from the region that responds, and no two surfaces can grow different
 * behaviour -- which is exactly what had happened: a node card had one
 * bottom-right wedge that only ever grew down-right, while a picture had
 * eight handles.
 *
 * CORNERS ONLY. The four edge-midpoint handles are gone: they meant "stretch
 * one axis", which on a picture or a generated result is a distortion nobody
 * asks for, and they crowded the corners that do the work.
 * \{ */

#define MOODBOARD_RESIZE_HANDLE_COUNT 4
/* Counter-clockwise from the bottom-left. Renumbering these means renumbering
 * the anchor rule with them; the values are runtime-only (never RNA), so the
 * order is free to change as long as both move together. */
#define MOODBOARD_HANDLE_BOTTOM_LEFT 0
#define MOODBOARD_HANDLE_BOTTOM_RIGHT 1
#define MOODBOARD_HANDLE_TOP_RIGHT 2
#define MOODBOARD_HANDLE_TOP_LEFT 3

/** Where the four corner squares sit, in the rect's own space. */
void moodboard_resize_handle_positions(const rctf &rect,
                                       float r_pos[MOODBOARD_RESIZE_HANDLE_COUNT][2]);
/** Handle index under a point already mapped into the rect's space, or -1. */
int moodboard_resize_handle_at(const rctf &rect,
                               float local_x,
                               float local_y,
                               float tolerance);
/** The corner held fixed while \a handle is dragged (the diagonal opposite). */
void moodboard_resize_handle_anchor(const rctf &rect,
                                    int handle,
                                    float *r_anchor_x,
                                    float *r_anchor_y);
/** Uniform scale factor from the anchor's diagonal -- one number for both
 * axes, which is what keeps the aspect locked. */
float moodboard_resize_scale_factor(const rctf &rect,
                                    int handle,
                                    float local_x,
                                    float local_y);
/** \a rect at a new size, grown or shrunk away from the anchored corner. */
void moodboard_resize_place(const rctf &rect,
                            int handle,
                            float new_width,
                            float new_height,
                            rctf *r_rect);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Canvas Frames (mixie_moodboard_frame_geometry.cc)
 *
 * ONE definition of a frame's geometry, shared by the draw pass, the action
 * row and the hit-test -- so the pixels the user aims at and the region that
 * responds can never drift apart at any zoom.
 * \{ */

/** Which part of a frame a press landed on. */
enum MoodboardFramePart {
  MOODBOARD_FRAME_PART_NONE = 0,
  /** The thick top strip: the frame's drag handle and primary click target. */
  MOODBOARD_FRAME_PART_TOP,
  /** Left / right / bottom border. Selects and drags like the top strip. */
  MOODBOARD_FRAME_PART_BORDER,
  /** Inside, away from every edge. A press here is a marquee, not a move. */
  MOODBOARD_FRAME_PART_INTERIOR,
};

/** Canvas rect of one frame. */
void moodboard_frame_rect(PointerRNA *frame, rctf *r_rect);
/** The thick top strip inside the frame's top edge, in canvas units. */
void moodboard_frame_top_strip(const rctf &frame_rect, rctf *r_strip);
/**
 * Which part of \a frame_rect the canvas point lands on. \a view_scale
 * converts the hit slop from pixels, so the grab zone stays aimable when the
 * border itself is drawn sub-pixel thin.
 */
MoodboardFramePart moodboard_frame_part_at(const rctf &frame_rect,
                                           float mouse_x,
                                           float mouse_y,
                                           float view_scale,
                                           bool collapsed);
/**
 * The frame under the cursor, SMALLEST first, and which part of it was hit.
 *
 * Smallest-area wins, exactly the tie-break the Python membership resolver
 * uses, so clicking and containment can never disagree about which frame an
 * area belongs to. A LOCKED frame is skipped entirely: that is what the lock
 * means -- only its members can be reached.
 *
 * Returns the frame's collection index, or -1.
 */
int moodboard_find_frame_at(PointerRNA *scene_ptr,
                            float mouse_x,
                            float mouse_y,
                            float view_scale,
                            MoodboardFramePart *r_part,
                            rctf *r_rect);
/**
 * Select the frame under \a mouse_x / \a mouse_y, its empty INTERIOR included.
 *
 * The click-time counterpart of #moodboard_find_frame_at: a plain click
 * anywhere on a frame selects it, while MOVING one is still only possible from
 * its border or title strip. It cannot live in the frame select operator --
 * that installs a modal, and claiming the interior there would take the press
 * away from a member's own drag and from the marquee over open space inside
 * the frame -- so it is called from the branch that already knows the gesture
 * ended as a click (box select's tiny-box case), after the selection has been
 * cleared. Returns whether a frame was selected.
 */
bool moodboard_frame_select_at_point(PointerRNA *scene_ptr,
                                     float mouse_x,
                                     float mouse_y,
                                     float view_scale);
/** The palette pastel at \a index, wrapped. Borrowed float[3]. */
const float *moodboard_frame_palette_color(int index);
/** The colour a frame actually wears: its custom colour, else its pastel. */
void moodboard_frame_color(PointerRNA *frame, float r_color[3]);
/**
 * Is an in-place frame rename running on this frame?
 * (mixie_moodboard_ops_frame_select.cc; runtime state keyed on the scene's
 * session uid, exactly like the media rename -- never scene data.)
 */
bool moodboard_frame_rename_is_active(const Scene *scene, const char *frame_id);
void moodboard_frame_rename_end();

/** \} */

}  // namespace blender::ed::mixie
