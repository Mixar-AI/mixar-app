/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The camera-move math the Director's two native movers share.
 *
 * `view3d_director_nudge.cc` (hold a key, move) and
 * `view3d_director_walk.cc` (the Cinema walk) integrate the same directions
 * at the same speed; only what starts and ends them differs. One copy, so
 * W can never mean one thing to the nudge and another to the walk — and so
 * that both answer #director_pointer_on_stage the same way.
 */

#pragma once

#include "BLI_math_matrix_types.hh"
#include "BLI_math_vector_types.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/** Identifiers are frozen: the nudge's RNA enum is built from these. */
enum DirectorMoveDirection {
  DIRECTOR_MOVE_FORWARD = 0,
  DIRECTOR_MOVE_BACK = 1,
  DIRECTOR_MOVE_LEFT = 2,
  DIRECTOR_MOVE_RIGHT = 3,
  DIRECTOR_MOVE_UP = 4,
  DIRECTOR_MOVE_DOWN = 5,
};

/** Bit for \a direction in a held-keys mask. */
unsigned int director_move_bit(int direction);

/** W/A/S/D/Q/E -> #DirectorMoveDirection, or -1. */
int director_move_from_key(int event_type);

/**
 * Unit world-space direction for every held key. W/S and A/D ride the
 * camera's own axes — forward is its local -Z, the way walk flies with
 * gravity off — while Q/E move on world Z. The SUM is normalised so a
 * diagonal (two keys held) travels at walk speed rather than faster.
 */
float3 director_move_vector(const float4x4 &matrix, unsigned int held);

/** Blender's own walk speed, with a fallback for an unset preference. */
float director_walk_speed();

/**
 * The Cinema walk's mouse-look (`view3d_director_walk_aim.cc`): turn
 * \a matrix by \a dx / \a dy pixels of drag — yaw about world Z, pitch about
 * its own right axis, refusing the poles. False when nothing changed.
 */
bool director_walk_aim(float4x4 &matrix, float dx, float dy);

/** The active shot's camera; \a r_locked reports the take's LOCKED state.
 * One resolver for every native camera writer, so they can never disagree
 * on which object moves. */
struct Object *director_move_camera(struct Scene *scene, bool *r_locked);

/**
 * Is \a event's pointer over the free STAGE of the Cinema viewport — the
 * part with no card, dock or header painted on it?
 *
 * A window-level modal handler sees every event before the regions do, so a
 * mover that claims them all leaves the whole surface dead. Shared, because
 * both movers have to answer it the same way.
 */
bool director_pointer_on_stage(struct bContext *C, const struct wmEvent *event);

}  // namespace blender
