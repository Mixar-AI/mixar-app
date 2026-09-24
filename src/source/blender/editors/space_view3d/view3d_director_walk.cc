/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The Cinema walk: `mixar.director_walk`.
 *
 * Blender's own `view3d.walk` is a viewport navigation mode, and two of its
 * rules are wrong for directing:
 *
 * - **Every mouse motion turns the camera.** Moving the pointer to reach a
 *   card, or simply resting a hand on the mouse, re-aims the shot. A
 *   director wants to drive to a position and then look — so here the camera
 *   turns only while the LEFT BUTTON IS HELD, and a still button means a
 *   still frame however much the pointer moves.
 * - **A left click confirms and exits.** That makes the one gesture a
 *   director reaches for — click and drag to look — the gesture that ends
 *   the walk. Here the left button is the look handle and never an exit —
 *   and neither is anything else on the keyboard or mouse: Esc and the right
 *   button are not exits either. The top strip's Walk chip is the ONE switch
 *   that starts and stops a walk, so its lit state can never disagree with
 *   whether one is running.
 * - **It owns every event in the window.** A modal handler runs before the
 *   regions do, so a walk that answers RUNNING_MODAL to each one leaves the
 *   whole surface dead: no card highlights, no tooltip, no button can be
 *   clicked while walking. The look handle is only a handle over the STAGE
 *   — the free part of the Cinema viewport — and anywhere else the pointer
 *   belongs to whatever is painted under it
 *   (#director_pointer_on_stage). The MOVEMENT KEYS answer the same
 *   question: W over the outliner, the chat, a moodboard or another
 *   workspace's viewport is that editor's W, not the camera's.
 *
 * Forking upstream's walk to change those rules would mean carrying
 * 1500 lines of navigation (gravity, teleport, jump, view-height, its own
 * modal keymap) that Cinema Mode does not use, and re-porting it on every
 * Blender bump. The movement half already exists natively here — the
 * hold-to-move nudge integrates W/A/S/D/Q/E at Blender's walk speed through
 * the world matrix as one undo step — so this is that, kept alive between
 * key presses, plus mouse-look. It shares the direction math with the nudge
 * (`view3d_director_camera_move.hh`) so a key can never mean two things;
 * the mouse-look's own math is `view3d_director_walk_aim.cc`.
 *
 * What it deliberately keeps from Blender: the walk SPEED preference, Shift
 * to sprint, Alt to creep, and the local -Z / world-Z axis split. What it
 * does not have: gravity, jumping and teleport, none of which a camera does.
 *
 * Python still owns the session around it (`MIXAR_OT_director_navigate`
 * supervises the exit, publishes `walk_active` for the top strip's hints and
 * captures a keyframe when Auto Key is on), exactly as it did around
 * `view3d.walk`. It also STOPS it — and is the only thing that does, short
 * of leaving the mode or losing the camera: the strip's Walk chip is a
 * toggle, and `walk_stop_requested` is how the second click reaches a modal
 * Python cannot cancel (#director_walk_stop_requested).
 */

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "BLI_math_matrix_types.hh"
#include "BLI_math_vector.hh"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_object.hh"
#include "BKE_report.hh"

#include "DEG_depsgraph.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_director.hh"
#include "view3d_director_camera_move.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Constants
 * \{ */

/** One integration step per timer tick. */
constexpr double WALK_TIMER_STEP = 1.0 / 60.0;
/** A stalled tick (window drag, heavy redraw) must not bank up distance. */
constexpr double WALK_MAX_STEP_SECONDS = 0.1;
/** Shift sprints, the way Blender's own walk does. */
constexpr float WALK_FAST_FACTOR = 4.0f;
/** Alt creeps, the way Blender's own walk does: the sprint's inverse, for
 * the last few centimetres of a framing. */
constexpr float WALK_SLOW_FACTOR = 1.0f / WALK_FAST_FACTOR;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Modal data
 * \{ */

struct DirectorWalkData {
  /** Resolved at invoke and re-resolved every tick, so a shot switch or a
   * deleted camera ends the walk instead of writing through a stale
   * pointer. */
  Object *camera = nullptr;
  /** Running WORLD matrix; both halves of the walk write into it. */
  float4x4 matrix;
  /** Bitmask over #DirectorMoveDirection. */
  unsigned int held = 0;
  /** The left button is DOWN: mouse motion aims the camera. */
  bool looking = false;
  double last_tick = 0.0;
  bool moved = false;
  wmTimer *timer = nullptr;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Writing the camera
 * \{ */

void walk_commit(bContext *C, DirectorWalkData *data, Object *camera)
{
  /* Through the WORLD matrix so a parented camera moves the distance asked
   * for rather than what its parent's transform makes of it; `use_compat`
   * keeps Euler continuity with the rotation already there, which is what
   * stops a keyed camera flipping the long way round later. */
  BKE_object_apply_mat4(camera, data->matrix.ptr(), true, true);
  DEG_id_tag_update(&camera->id, ID_RECALC_TRANSFORM);
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, camera);
  if (ARegion *region = CTX_wm_region(C)) {
    ED_region_tag_redraw(region);
  }
  data->moved = true;
}

/**
 * The speed modifier held on \a event: Shift sprints, Alt creeps. Shift wins
 * when both are held, as it does in Blender's own walk. Read from the
 * modifier state rather than from key events, so the Alt press itself is
 * never claimed and still reaches whatever else listens for it.
 */
float walk_speed_factor(const wmEvent *event)
{
  if ((event->modifier & KM_SHIFT) != 0) {
    return WALK_FAST_FACTOR;
  }
  if ((event->modifier & KM_ALT) != 0) {
    return WALK_SLOW_FACTOR;
  }
  return 1.0f;
}

/** Travel \a seconds' worth along the held directions. */
void walk_move(bContext *C,
               DirectorWalkData *data,
               Object *camera,
               const double seconds,
               const float speed_factor)
{
  const float3 direction = director_move_vector(data->matrix, data->held);
  if (seconds <= 0.0 || math::length_squared(direction) == 0.0f) {
    return;
  }
  const float speed = director_walk_speed() * speed_factor;
  data->matrix.location() += direction * (speed * float(seconds));
  walk_commit(C, data, camera);
}

/**
 * Take the camera's own pose back before a move or a look begins.
 *
 * The walk integrates into a running matrix rather than reading the camera
 * each tick, because a tick can land before the depsgraph has evaluated the
 * last one's write. But between bursts nothing of the walk's is in flight,
 * and the camera may have been moved by something else: a scrub or a
 * keyframe jump in the timeline, playback, a paired phone, an undo. Driving
 * on from the running matrix snapped the camera back to wherever the walk
 * last left it, so using the timeline mid-walk was undone by the next W.
 *
 * False when the camera is no longer the walk's to move (a shot switch, a
 * deleted camera, a locked take): the caller ends the walk rather than read
 * through a stale pointer.
 */
bool walk_resync(bContext *C, DirectorWalkData *data)
{
  bool locked = false;
  Object *camera = director_move_camera(CTX_data_scene(C), &locked);
  if (camera == nullptr || camera != data->camera || locked) {
    return false;
  }
  data->matrix = camera->object_to_world();
  return true;
}

/** Aim by \a dx / \a dy pixels of drag (#director_walk_aim), then write it. */
void walk_look(bContext *C, DirectorWalkData *data, Object *camera, const float dx, const float dy)
{
  if (director_walk_aim(data->matrix, dx, dy)) {
    walk_commit(C, data, camera);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator callbacks
 * \{ */

bool director_walk_poll(bContext *C)
{
  if (!view3d_director_is_directing(CTX_data_scene(C))) {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  return area && region && area->spacetype == SPACE_VIEW3D &&
         region->regiontype == RGN_TYPE_WINDOW;
}

void director_walk_exit(bContext *C, wmOperator *op)
{
  DirectorWalkData *data = static_cast<DirectorWalkData *>(op->customdata);
  if (!data) {
    return;
  }
  if (data->timer) {
    WM_event_timer_remove(CTX_wm_manager(C), CTX_wm_window(C), data->timer);
  }
  MEM_delete(data);
  op->customdata = nullptr;
}

/** One undo step for the whole walk; nothing to undo if it never moved. */
wmOperatorStatus director_walk_finish(bContext *C, wmOperator *op)
{
  const DirectorWalkData *data = static_cast<DirectorWalkData *>(op->customdata);
  const bool moved = data && data->moved;
  director_walk_exit(C, op);
  return moved ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

void director_walk_cancel(bContext *C, wmOperator *op)
{
  director_walk_exit(C, op);
}

wmOperatorStatus director_walk_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  bool locked = false;
  Object *camera = director_move_camera(CTX_data_scene(C), &locked);
  if (!camera) {
    BKE_report(op->reports, RPT_INFO, "No shot camera to walk");
    return OPERATOR_CANCELLED;
  }
  if (locked) {
    BKE_report(op->reports, RPT_INFO, "This take is locked; start a new take to move the camera");
    return OPERATOR_CANCELLED;
  }

  DirectorWalkData *data = MEM_new<DirectorWalkData>(__func__);
  data->camera = camera;
  data->matrix = camera->object_to_world();
  data->last_tick = BLI_time_now_seconds();
  data->timer = WM_event_timer_add(CTX_wm_manager(C), CTX_wm_window(C), TIMER, WALK_TIMER_STEP);
  op->customdata = data;

  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

/**
 * Has the session asked this walk to stop?
 *
 * The top strip's Walk chip paints lit while walking and publishes "stop",
 * so it is a toggle; without a channel to ask through, clicking it started a
 * SECOND walk on top of the first. `walk_stop_requested` is that channel,
 * and it is cleared here so the request cannot outlive the walk it stopped.
 */
bool director_walk_stop_requested(bContext *C)
{
  PointerRNA state_ptr;
  if (!view3d_director_state_pointer(CTX_data_scene(C), &state_ptr)) {
    return false;
  }
  PropertyRNA *prop = RNA_struct_find_property(&state_ptr, "walk_stop_requested");
  if (prop == nullptr || !RNA_property_boolean_get(&state_ptr, prop)) {
    return false;
  }
  RNA_property_boolean_set(&state_ptr, prop, false);
  return true;
}

wmOperatorStatus director_walk_tick(bContext *C,
                                    wmOperator *op,
                                    DirectorWalkData *data,
                                    const float speed_factor)
{
  if (director_walk_stop_requested(C)) {
    return director_walk_finish(C, op);
  }
  /* The walk belongs to a Cinema session and to the viewport it started in.
   * Leaving the mode, or switching to a workspace that does not contain that
   * area, used to leave the modal running on the window with its timer and
   * its held keys — invisible, and still the camera's. `CTX_wm_area` is the
   * invoke-time area, validated against the live screen every event
   * (`wm_handler_op_context_get_if_valid`), so a null one IS "my viewport is
   * gone". */
  if (!view3d_director_is_directing(CTX_data_scene(C)) || CTX_wm_area(C) == nullptr) {
    return director_walk_finish(C, op);
  }
  const double now = BLI_time_now_seconds();
  const double dt = std::clamp(now - data->last_tick, 0.0, WALK_MAX_STEP_SECONDS);
  data->last_tick = now;
  if (data->held == 0) {
    /* Standing still is a state, not an exit: the walk runs until the Walk
     * chip stops it, so a director can stop, look, and drive on. */
    return OPERATOR_RUNNING_MODAL;
  }
  bool locked = false;
  Object *camera = director_move_camera(CTX_data_scene(C), &locked);
  if (camera != data->camera || locked) {
    /* Shot switched, camera removed, or the take got locked mid-walk. */
    return director_walk_finish(C, op);
  }
  walk_move(C, data, camera, dt, speed_factor);
  return OPERATOR_RUNNING_MODAL;
}

wmOperatorStatus director_walk_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  DirectorWalkData *data = static_cast<DirectorWalkData *>(op->customdata);
  if (!data) {
    return OPERATOR_CANCELLED;
  }

  if (event->type == TIMER) {
    if (event->customdata != data->timer) {
      return OPERATOR_PASS_THROUGH;
    }
    return director_walk_tick(C, op, data, walk_speed_factor(event));
  }

  /* No key or button ends the walk; the Walk chip is the one switch.
   *
   * Esc and the right button used to, alongside the chip — so the chip's lit
   * state was one of three ways the walk could end, and the mode's default
   * state (Cinema Mode opens walking) was one stray Esc from gone. They pass
   * through now like every other key the walk does not use. The LEFT button
   * never ended it either: it is the look handle, and confirming on it made
   * the one gesture a director reaches for the gesture that quit. */

  if (event->type == LEFTMOUSE) {
    if (event->val == KM_PRESS) {
      if (!director_pointer_on_stage(C, event)) {
        /* A card, the dock, the header: the click is the button's, not a
         * look-drag. Passing it through is what keeps the whole surface
         * usable while the walk runs. */
        return OPERATOR_PASS_THROUGH;
      }
      if (data->held == 0 && !walk_resync(C, data)) {
        return director_walk_finish(C, op);
      }
      data->looking = true;
      return OPERATOR_RUNNING_MODAL;
    }
    /* The release ends the drag it started — and only that drag. A release
     * the walk never claimed belongs to whatever claimed the press. */
    const bool was_looking = data->looking;
    data->looking = false;
    return was_looking ? OPERATOR_RUNNING_MODAL : OPERATOR_PASS_THROUGH;
  }

  if (event->type == MOUSEMOVE) {
    if (!data->looking) {
      /* A still button is a still frame, however far the pointer travels —
       * and the motion still reaches the regions, so cards highlight and
       * tooltips appear exactly as they do when the walk is not running. */
      return OPERATOR_PASS_THROUGH;
    }
    bool locked = false;
    Object *camera = director_move_camera(CTX_data_scene(C), &locked);
    if (camera != data->camera || locked) {
      return director_walk_finish(C, op);
    }
    walk_look(C,
              data,
              camera,
              float(event->xy[0] - event->prev_xy[0]),
              float(event->xy[1] - event->prev_xy[1]));
    return OPERATOR_RUNNING_MODAL;
  }

  const int direction = director_move_from_key(event->type);
  if (direction < 0) {
    /* Not ours: the viewport keeps working underneath. */
    return OPERATOR_PASS_THROUGH;
  }
  const unsigned int bit = director_move_bit(direction);
  if (event->val == KM_PRESS) {
    /* Only from the STAGE. A modal handler sits on the window, so without
     * this the camera keys drove the shot from wherever the pointer happened
     * to be — the outliner, the properties editor, the chat, a moodboard,
     * another workspace's 3D viewport — and W meant "walk" in editors that
     * have their own W. It is the same question the look handle asks, so a
     * press over a card or a text field goes to the card or the field. */
    if (!director_pointer_on_stage(C, event)) {
      return OPERATOR_PASS_THROUGH;
    }
    /* The first key of a burst, with no look-drag running either: nothing
     * of the walk's is in flight, so the camera's own pose is the truth. */
    if (data->held == 0 && !data->looking && !walk_resync(C, data)) {
      return director_walk_finish(C, op);
    }
    data->held |= bit;
    return OPERATOR_RUNNING_MODAL;
  }
  if (event->val == KM_RELEASE) {
    /* A release is taken whatever the modifiers, so a key cannot stick —
     * and a key the walk never claimed is passed on, so whoever took the
     * press sees its release. Holding W and then moving the pointer off the
     * stage keeps walking: the KEY is held, and that is what moves. */
    const bool was_held = (data->held & bit) != 0;
    data->held &= ~bit;
    return was_held ? OPERATOR_RUNNING_MODAL : OPERATOR_PASS_THROUGH;
  }
  return OPERATOR_PASS_THROUGH;
}

/** \} */

}  // namespace

void MIXAR_OT_director_walk(wmOperatorType *ot)
{
  ot->name = "Walk Camera";
  ot->idname = "MIXAR_OT_director_walk";
  ot->description =
      "Drive the shot camera: W A S D to move, Q E for height, Shift to sprint, Alt to "
      "creep, hold the left mouse button to look. The Walk button starts and stops it";

  ot->invoke = director_walk_invoke;
  ot->modal = director_walk_modal;
  ot->cancel = director_walk_cancel;
  ot->poll = director_walk_poll;

  /* One undo step for the whole walk, never grouped with the next one.
   *
   * NOT OPTYPE_BLOCKING: that takes a GHOST cursor grab for the operator's
   * whole run, and this walk deliberately shares the window with the Cinema
   * cards — the director drives, then reaches for a control, then drives on.
   * A grab is for a gesture that owns the pointer, which a look-drag only
   * does while the button is down. */
  ot->flag = OPTYPE_UNDO;
}

}  // namespace blender
