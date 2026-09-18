/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Hold-to-move camera motion for the Cinema Mode W/A/S/D and Q/E hints.
 *
 * `mixar.director_nudge_camera` used to be a Python operator fired once per
 * OS key repeat, each repeat paying an undo push, a depsgraph evaluation and
 * a redraw. This is the same contract as ONE modal operator: the first press
 * starts it, a 60 Hz timer integrates every held direction at Blender's own
 * walk speed, releasing every key (or Esc / RMB) ends it, and the whole held
 * motion is a single undo step (`OPTYPE_UNDO`, never grouped).
 *
 * It never keys anything: the camera moves and the existing auto-key /
 * capture flow records it off the transform updates, exactly as walk does.
 *
 * The keymap contract lives in `director/ui/keymap.py`: the binding sits in
 * the global "User Interface" keymap, so the POLL is what scopes it — a
 * directing session inside a 3D viewport's WINDOW region. The poll must NOT
 * require a camera: it decides whether the key is ABSORBED, and a take with
 * no camera (or a locked one) still has to swallow S rather than leak it to
 * `transform.resize`; `invoke` handles those cases.
 */

#include <algorithm>

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
#include "DNA_userdef_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_director.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Contract Constants
 * \{ */

/** Identifiers are frozen: `keymap.py` sets `direction` on every item. */
enum DirectorNudgeDirection {
  NUDGE_FORWARD = 0,
  NUDGE_BACK = 1,
  NUDGE_LEFT = 2,
  NUDGE_RIGHT = 3,
  NUDGE_UP = 4,
  NUDGE_DOWN = 5,
};

static const EnumPropertyItem nudge_direction_items[] = {
    {NUDGE_FORWARD, "FORWARD", 0, "Forward", "Move the camera along its view direction"},
    {NUDGE_BACK, "BACK", 0, "Back", "Move the camera against its view direction"},
    {NUDGE_LEFT, "LEFT", 0, "Left", "Strafe the camera left"},
    {NUDGE_RIGHT, "RIGHT", 0, "Right", "Strafe the camera right"},
    {NUDGE_UP, "UP", 0, "Up", "Raise the camera along the world Z axis"},
    {NUDGE_DOWN, "DOWN", 0, "Down", "Lower the camera along the world Z axis"},
    {0, nullptr, 0, nullptr, nullptr},
};

/** One integration step per timer tick. */
constexpr double NUDGE_TIMER_STEP = 1.0 / 60.0;
/** A stalled tick (window drag, heavy redraw) must not bank up distance. */
constexpr double NUDGE_MAX_STEP_SECONDS = 0.1;
/** Grace after the last release so quick re-taps stay one undo step. */
constexpr double NUDGE_RELEASE_GRACE_SECONDS = 0.15;
/** Blender's preference is the one answer to "how fast is WASD". */
constexpr float NUDGE_DEFAULT_WALK_SPEED = 3.0f;
/** Gap that turns a repeated key into a fresh press for the locked report. */
constexpr double NUDGE_LOCKED_REPORT_GAP_SECONDS = 0.15;
/** What a single tap is worth: a press-and-release inside one event batch
 * never sees a timer tick, and a tap that moves nothing reads as broken. */
constexpr double NUDGE_TAP_SECONDS = 0.05;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Shared Helpers
 * \{ */

struct DirectorNudgeData {
  /** The camera resolved at invoke; re-resolved every tick so a shot switch
   * or camera removal mid-hold ends the move instead of touching a stale
   * pointer. */
  Object *camera = nullptr;
  /** Running WORLD matrix: rotation never changes, only the translation. */
  float4x4 matrix;
  /** Bitmask over #DirectorNudgeDirection. */
  unsigned int held = 0;
  double last_tick = 0.0;
  double idle_since = 0.0;
  bool moved = false;
  wmTimer *timer = nullptr;
};

/** Key -> direction, the SAME mapping `keymap.py` binds. */
static int nudge_direction_from_key(const int event_type)
{
  switch (event_type) {
    case EVT_WKEY:
      return NUDGE_FORWARD;
    case EVT_SKEY:
      return NUDGE_BACK;
    case EVT_AKEY:
      return NUDGE_LEFT;
    case EVT_DKEY:
      return NUDGE_RIGHT;
    case EVT_EKEY:
      return NUDGE_UP;
    case EVT_QKEY:
      return NUDGE_DOWN;
    default:
      return -1;
  }
}

static unsigned int nudge_bit(const int direction)
{
  return 1u << unsigned(direction);
}

/** The active shot's camera; `r_locked` reports the take's LOCKED state. */
static Object *nudge_shot_camera(Scene *scene, bool *r_locked)
{
  /* One resolver for every native camera writer (nudge, aerial map, its
   * placement modal), so they can never disagree on which object moves. */
  return view3d_director_shot_camera(scene, r_locked);
}

static float nudge_walk_speed()
{
  const float speed = U.walk_navigation.walk_speed;
  return speed > 0.0f ? speed : NUDGE_DEFAULT_WALK_SPEED;
}

/**
 * Unit world-space direction for every held key. W/S and A/D ride the
 * camera's own axes — forward is its local -Z, the way walk flies with
 * gravity off — while Q/E move on world Z. The SUM is normalised so a
 * diagonal (two keys held) travels at walk speed rather than faster.
 */
static float3 nudge_direction_vector(const float4x4 &matrix, const unsigned int held)
{
  const float3 right = math::normalize(matrix.x_axis());
  const float3 forward = -math::normalize(matrix.z_axis());
  const float3 up(0.0f, 0.0f, 1.0f);

  float3 sum(0.0f);
  if (held & nudge_bit(NUDGE_FORWARD)) {
    sum += forward;
  }
  if (held & nudge_bit(NUDGE_BACK)) {
    sum -= forward;
  }
  if (held & nudge_bit(NUDGE_RIGHT)) {
    sum += right;
  }
  if (held & nudge_bit(NUDGE_LEFT)) {
    sum -= right;
  }
  if (held & nudge_bit(NUDGE_UP)) {
    sum += up;
  }
  if (held & nudge_bit(NUDGE_DOWN)) {
    sum -= up;
  }
  /* Opposed keys cancel; a diagonal is normalised back to walk speed. */
  return math::normalize(sum);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator Callbacks
 * \{ */

/**
 * Directing, with the cursor in a 3D viewport's main region. Deliberately no
 * camera lookup — see the file comment: absorbing the key is the point.
 */
static bool director_nudge_poll(bContext *C)
{
  if (!view3d_director_is_directing(CTX_data_scene(C))) {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  return area && region && area->spacetype == SPACE_VIEW3D &&
         region->regiontype == RGN_TYPE_WINDOW;
}

static void director_nudge_exit(bContext *C, wmOperator *op)
{
  DirectorNudgeData *data = static_cast<DirectorNudgeData *>(op->customdata);
  if (!data) {
    return;
  }
  if (data->timer) {
    WM_event_timer_remove(CTX_wm_manager(C), CTX_wm_window(C), data->timer);
  }
  MEM_delete(data);
  op->customdata = nullptr;
}

/** One undo step for the whole held motion; nothing to undo if it never moved. */
static wmOperatorStatus director_nudge_finish(bContext *C, wmOperator *op)
{
  const DirectorNudgeData *data = static_cast<DirectorNudgeData *>(op->customdata);
  const bool moved = data && data->moved;
  director_nudge_exit(C, op);
  return moved ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static void director_nudge_cancel(bContext *C, wmOperator *op)
{
  director_nudge_exit(C, op);
}

static void nudge_apply(bContext *C,
                        DirectorNudgeData *data,
                        Object *camera,
                        unsigned int held,
                        double seconds);

static wmOperatorStatus director_nudge_invoke(bContext *C,
                                              wmOperator *op,
                                              const wmEvent * /*event*/)
{
  bool locked = false;
  Object *camera = nudge_shot_camera(CTX_data_scene(C), &locked);
  if (!camera) {
    /* Absorbed: the key must not fall through to its Blender meaning. */
    return OPERATOR_CANCELLED;
  }
  if (locked) {
    /* Still absorbed. Report once per burst so a held key cannot flood the
     * status bar: every OS auto-repeat is a fresh invoke on a locked take. */
    static double last_report = 0.0;
    const double now = BLI_time_now_seconds();
    if (now - last_report > NUDGE_LOCKED_REPORT_GAP_SECONDS) {
      BKE_report(
          op->reports, RPT_INFO, "This take is locked; start a new take to move the camera");
    }
    last_report = now;
    return OPERATOR_CANCELLED;
  }

  DirectorNudgeData *data = MEM_new<DirectorNudgeData>(__func__);
  data->camera = camera;
  data->matrix = camera->object_to_world();
  data->held = nudge_bit(RNA_enum_get(op->ptr, "direction"));
  data->last_tick = BLI_time_now_seconds();
  data->timer = WM_event_timer_add(
      CTX_wm_manager(C), CTX_wm_window(C), TIMER, NUDGE_TIMER_STEP);
  op->customdata = data;
  /* The press itself is worth a tap: a quick press-and-release must move. */
  nudge_apply(C, data, camera, data->held, NUDGE_TAP_SECONDS);

  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

/** Move \a seconds' worth of travel along the held directions in \a held. */
static void nudge_apply(bContext *C,
                        DirectorNudgeData *data,
                        Object *camera,
                        const unsigned int held,
                        const double seconds)
{
  const float3 direction = nudge_direction_vector(data->matrix, held);
  if (seconds <= 0.0 || math::length_squared(direction) == 0.0f) {
    return;
  }
  data->matrix.location() += direction * (nudge_walk_speed() * float(seconds));
  /* Written through the WORLD matrix so a parented camera moves the distance
   * asked for rather than the distance its parent's transform makes of it;
   * `use_compat` keeps Euler continuity with the current rotation. */
  BKE_object_apply_mat4(camera, data->matrix.ptr(), true, true);
  DEG_id_tag_update(&camera->id, ID_RECALC_TRANSFORM);
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, camera);
  if (ARegion *region = CTX_wm_region(C)) {
    ED_region_tag_redraw(region);
  }
  data->moved = true;
}

static wmOperatorStatus director_nudge_tick(bContext *C, wmOperator *op, DirectorNudgeData *data)
{
  const double now = BLI_time_now_seconds();
  const double dt = std::clamp(now - data->last_tick, 0.0, NUDGE_MAX_STEP_SECONDS);
  data->last_tick = now;

  if (data->held == 0) {
    if (now - data->idle_since > NUDGE_RELEASE_GRACE_SECONDS) {
      return director_nudge_finish(C, op);
    }
    return OPERATOR_RUNNING_MODAL;
  }

  bool locked = false;
  Object *camera = nudge_shot_camera(CTX_data_scene(C), &locked);
  if (camera != data->camera || locked) {
    /* Shot switched, camera removed, or the take got locked mid-hold. */
    return director_nudge_finish(C, op);
  }

  nudge_apply(C, data, camera, data->held, dt);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus director_nudge_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  DirectorNudgeData *data = static_cast<DirectorNudgeData *>(op->customdata);
  if (!data) {
    return OPERATOR_CANCELLED;
  }

  if (event->type == TIMER) {
    if (event->customdata != data->timer) {
      return OPERATOR_PASS_THROUGH;
    }
    return director_nudge_tick(C, op, data);
  }

  if (ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)) {
    if (event->val == KM_PRESS) {
      return director_nudge_finish(C, op);
    }
    return OPERATOR_PASS_THROUGH;
  }

  const int direction = nudge_direction_from_key(event->type);
  if (direction < 0) {
    /* Not ours: the viewport keeps working underneath (orbit, zoom, ...). */
    return OPERATOR_PASS_THROUGH;
  }

  if (event->val == KM_PRESS) {
    if (event->modifier != 0) {
      /* Ctrl+S and friends keep their meaning while a key is held. */
      return OPERATOR_PASS_THROUGH;
    }
    /* OS auto-repeat re-sends PRESS for a held key; only a FRESH press is
     * worth a tap step — after that the timer owns the motion. */
    const unsigned int bit = nudge_bit(direction);
    if ((data->held & bit) == 0) {
      data->held |= bit;
      bool locked = false;
      Object *camera = nudge_shot_camera(CTX_data_scene(C), &locked);
      if (camera == data->camera && !locked) {
        nudge_apply(C, data, camera, bit, NUDGE_TAP_SECONDS);
      }
    }
    return OPERATOR_RUNNING_MODAL;
  }
  if (event->val == KM_RELEASE) {
    /* Releases are taken regardless of modifiers so a key can never stick. */
    data->held &= ~nudge_bit(direction);
    if (data->held == 0) {
      data->idle_since = BLI_time_now_seconds();
    }
    return OPERATOR_RUNNING_MODAL;
  }
  return OPERATOR_PASS_THROUGH;
}

static void MIXAR_OT_director_nudge_camera(wmOperatorType *ot)
{
  ot->name = "Move Camera";
  ot->idname = "MIXAR_OT_director_nudge_camera";
  ot->description = "Move the shot camera walk-style while the key is held";

  ot->invoke = director_nudge_invoke;
  ot->modal = director_nudge_modal;
  ot->cancel = director_nudge_cancel;
  ot->poll = director_nudge_poll;

  /* OPTYPE_UNDO, never UNDO_GROUPED: the whole held motion is ONE undo step
   * because it is ONE operator call. Not BLOCKING — the viewport must keep
   * receiving the events this modal passes through. */
  ot->flag = OPTYPE_UNDO;

  RNA_def_enum(ot->srna,
               "direction",
               nudge_direction_items,
               NUDGE_FORWARD,
               "Direction",
               "Direction the first press moves the camera in");
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Registration
 * \{ */

void view3d_director_operatortypes()
{
  WM_operatortype_append(MIXAR_OT_director_nudge_camera);
  WM_operatortype_append(MIXAR_OT_director_place_camera);
}

/** \} */

}  // namespace blender
