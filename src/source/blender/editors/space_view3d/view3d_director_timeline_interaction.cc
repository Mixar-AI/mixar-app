/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Mouse and trackpad interaction for the Director timeline viewport.
 */

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_director_timeline.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

bool point_inside(const rctf &rect, const wmEvent *event)
{
  return BLI_rctf_isect_pt(&rect, float(event->mval[0]), float(event->mval[1]));
}

/**
 * The key column under the pointer, or null.
 *
 * Hit rects shrink with the spacing but never below a grabbable width, so on
 * a take keyed every frame neighbouring rects overlap; the column NEAREST
 * the pointer wins, which is the one the director is aiming at.
 */
const DirectorTimelineKeyHit *key_at_event(const DirectorTimelineRuntime &runtime,
                                           const wmEvent *event)
{
  const DirectorTimelineKeyHit *best = nullptr;
  float best_distance = 0.0f;
  for (const DirectorTimelineKeyHit &hit : runtime.key_hits) {
    if (!point_inside(hit.bounds, event)) {
      continue;
    }
    const float distance = std::abs(float(event->mval[0]) - hit.x);
    if (best == nullptr || distance < best_distance) {
      best = &hit;
      best_distance = distance;
    }
  }
  return best;
}

bool dispatch_int_operator(bContext *C, const char *idname, const char *property, const int value)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (!ot) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_int_set(&op_ptr, property, value);
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  return (result & (OPERATOR_FINISHED | OPERATOR_RUNNING_MODAL)) != 0;
}

bool begin_strip_drag(bContext *C, const wmEvent *event, DirectorTimelineRuntime *runtime)
{
  wmOperatorType *ot = WM_operatortype_find("mixar.director_drag_strip", true);
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  if (!ot || width <= 0.0f) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_float_set(&op_ptr, "frames_per_pixel", runtime->view_span_frames / width);
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::InvokeRegionWin, &op_ptr, event);
  WM_operator_properties_free(&op_ptr);
  if (result & OPERATOR_RUNNING_MODAL) {
    runtime->view_user_modified = true;
    return true;
  }
  return false;
}

/**
 * A press on a key: `mixar.director_drag_keys` selects it (the Dope Sheet's
 * click rule), parks the playhead on it and, on a draft, drags the selected
 * keys. A locked take selects and views, and never moves.
 */
bool begin_key_drag(bContext *C,
                    const wmEvent *event,
                    DirectorTimelineRuntime *runtime,
                    const DirectorTimelineKeyHit &key)
{
  wmOperatorType *ot = WM_operatortype_find("mixar.director_drag_keys", true);
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  if (!ot || width <= 0.0f) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_float_set(&op_ptr, "frame", key.frame);
  RNA_float_set(&op_ptr, "frames_per_pixel", runtime->view_span_frames / width);
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::InvokeRegionWin, &op_ptr, event);
  WM_operator_properties_free(&op_ptr);
  if (result & OPERATOR_RUNNING_MODAL) {
    /* Same as strip drag: pin the view so retiming the first/last key
     * cannot re-fit the span under the cursor. */
    runtime->view_user_modified = true;
  }
  return (result & (OPERATOR_FINISHED | OPERATOR_RUNNING_MODAL)) != 0;
}

/**
 * X / Delete: the selected keys, or with none selected the key under the
 * pointer, else the one under the playhead (`mixar.director_delete_keys`).
 */
bool delete_keys(bContext *C, const DirectorTimelineKeyHit *hovered)
{
  wmOperatorType *ot = WM_operatortype_find("mixar.director_delete_keys", true);
  if (!ot) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  if (hovered != nullptr) {
    RNA_float_set(&op_ptr, "frame", hovered->frame);
    RNA_boolean_set(&op_ptr, "use_frame", true);
  }
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  return (result & OPERATOR_FINISHED) != 0;
}

bool begin_scrub(bContext *C,
                 const wmEvent *event,
                 const ARegion *region,
                 DirectorTimelineRuntime *runtime)
{
  wmOperatorType *ot = WM_operatortype_find("mixar.director_scrub", true);
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  if (!ot || width <= 0.0f) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_float_set(&op_ptr, "frames_per_pixel", runtime->view_span_frames / width);
  RNA_float_set(
      &op_ptr, "origin_px", float(region->winrct.xmin) + runtime->viewport_bounds.xmin);
  RNA_float_set(&op_ptr, "start_frame", runtime->view_start_frame);
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::InvokeRegionWin, &op_ptr, event);
  WM_operator_properties_free(&op_ptr);
  return (result & OPERATOR_RUNNING_MODAL) != 0;
}

/**
 * Earliest frame the view may start at.
 *
 * NOT `scene_frame_start`. Clamping there made the dock refuse to show any
 * frame before Start, which is exactly the stretch the range scrim dims —
 * set Start to 50 and the dimmed 1..49 could never be brought on screen. The
 * floor is frame 0, or a key or beat that sits earlier still, so one left
 * outside the range stays reachable instead of being hidden with it.
 */
float view_floor(const DirectorViewState &state)
{
  float floor_frame = 0.0f;
  for (const DirectorBeatView &beat : state.beats) {
    floor_frame = std::min(floor_frame, float(beat.frame));
  }
  float first, last;
  if (director_timeline_camera_key_range(state.shot_camera, &first, &last)) {
    floor_frame = std::min(floor_frame, std::floor(first));
  }
  return floor_frame;
}

void zoom_at_event(const DirectorViewState &state,
                   DirectorTimelineRuntime *runtime,
                   const wmEvent *event,
                   const float factor)
{
  const float width = std::max(BLI_rctf_size_x(&runtime->viewport_bounds), 1.0f);
  const float anchor_t = std::clamp(
      (float(event->mval[0]) - runtime->viewport_bounds.xmin) / width, 0.0f, 1.0f);
  const float anchor_frame = runtime->view_start_frame + anchor_t * runtime->view_span_frames;
  const float min_span = std::max(2.0f, state.fps * 0.25f);
  const float max_span = std::max(min_span, state.fps * 3600.0f);
  const float new_span = std::clamp(runtime->view_span_frames * factor, min_span, max_span);
  runtime->view_start_frame = std::max(view_floor(state), anchor_frame - anchor_t * new_span);
  runtime->view_span_frames = new_span;
  runtime->view_user_modified = true;
}

void pan_frames(const DirectorViewState &state,
                DirectorTimelineRuntime *runtime,
                const float delta_frames)
{
  runtime->view_start_frame = std::max(view_floor(state),
                                       runtime->view_start_frame + delta_frames);
  runtime->view_user_modified = true;
}

void update_hover(ARegion *region,
                  const DirectorViewState &state,
                  DirectorTimelineRuntime *runtime,
                  const wmEvent *event)
{
  /* The bar lights up only where a press would drag the whole strip: over
   * a key, the press is the key's. */
  const bool strip_hovered = !state.locked && key_at_event(*runtime, event) == nullptr &&
                             point_inside(runtime->strip_bounds, event);
  if (strip_hovered != runtime->strip_hovered) {
    runtime->strip_hovered = strip_hovered;
    ED_region_tag_redraw(region);
  }
}

/** Frame under region px \a x, for anchoring a pan or a zoom. */
float frame_at_x(const DirectorTimelineRuntime &runtime, const int x)
{
  const float width = std::max(BLI_rctf_size_x(&runtime.viewport_bounds), 1.0f);
  const float t = (float(x) - runtime.viewport_bounds.xmin) / width;
  return runtime.view_start_frame + t * runtime.view_span_frames;
}

/**
 * Middle-mouse drag panning, the way every other Blender editor pans.
 *
 * The view (`view_start_frame` / `view_span_frames`) lives in this region's
 * runtime, not in RNA, so a Python modal could not reach it — the drag is
 * tracked here instead. It is anchored on the FRAME under the press rather
 * than integrated from deltas, so a pan that hits the `scene_frame_start`
 * clamp and comes back lands exactly where it started.
 */
bool handle_pan_drag(ARegion *region,
                     const DirectorViewState &state,
                     DirectorTimelineRuntime *runtime,
                     const wmEvent *event)
{
  if (event->type == MIDDLEMOUSE) {
    if (event->val == KM_PRESS && point_inside(runtime->viewport_bounds, event)) {
      runtime->panning = true;
      runtime->pan_anchor_x = event->mval[0];
      runtime->pan_anchor_frame = frame_at_x(*runtime, event->mval[0]);
      return true;
    }
    if (event->val == KM_RELEASE && runtime->panning) {
      runtime->panning = false;
      return true;
    }
    return false;
  }
  if (!runtime->panning) {
    return false;
  }
  if (ISTIMER(event->type)) {
    /* A timer is not the user doing anything. Playback's own redraw timer
     * ticks straight through a pan, and ending the drag on it made the
     * middle mouse unusable the moment the timeline was running. */
    return false;
  }
  if (event->type != MOUSEMOVE && event->type != INBETWEEN_MOUSEMOVE) {
    /* Anything else — a window deactivate, Esc, a key — ends the drag rather
     * than leaving the region stuck in a pan the user cannot see. A fast
     * drag is delivered as INBETWEEN_MOUSEMOVE, which is the same motion,
     * so ending on it ended every pan on its first quick gesture. */
    runtime->panning = false;
    return false;
  }
  const float width = std::max(BLI_rctf_size_x(&runtime->viewport_bounds), 1.0f);
  const float t = (float(event->mval[0]) - runtime->viewport_bounds.xmin) / width;
  runtime->view_start_frame = std::max(view_floor(state),
                                       runtime->pan_anchor_frame - t * runtime->view_span_frames);
  runtime->view_user_modified = true;
  ED_region_tag_redraw(region);
  return true;
}

int timeline_ui_handler(bContext *C, const wmEvent *event, void * /*userdata*/)
{
  ARegion *region = CTX_wm_region(C);
  DirectorTimelineRuntime *runtime = region ? static_cast<DirectorTimelineRuntime *>(
                                                  region->regiondata) :
                                              nullptr;
  DirectorViewState state;
  if (!region || !runtime || !view3d_director_state_read(CTX_data_scene(C), &state) ||
      !state.active)
  {
    return WM_UI_HANDLER_CONTINUE;
  }

  /* Pan first: a middle-mouse drag owns every event until it ends. */
  if (handle_pan_drag(region, state, runtime, event)) {
    return WM_UI_HANDLER_BREAK;
  }
  const DirectorTimelineKeyHit *key = key_at_event(*runtime, event);
  /* Then the selection gestures (view3d_director_timeline_select.cc). They
   * are asked BEFORE the press paths below because those are the fallback:
   * a Shift+click, a box drag, A or Shift+D is consumed there, and
   * everything else falls through unchanged. */
  if (director_timeline_selection_event(C, region, state, runtime, event, key)) {
    return WM_UI_HANDLER_BREAK;
  }
  if (event->type == MOUSEMOVE) {
    update_hover(region, state, runtime, event);
    return WM_UI_HANDLER_CONTINUE;
  }
  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    /* Every key is a handle — each recorded sample as much as a beat. The
     * keys are the precision target and are asked first. */
    if (key != nullptr) {
      if (begin_key_drag(C, event, runtime, *key)) {
        ED_region_tag_redraw(region);
        return WM_UI_HANDLER_BREAK;
      }
    }
    /* The TICK ITSELF is a handle: grab the playhead line or its frame pill
     * anywhere in the dock and it scrubs, the way a playhead behaves in every
     * editor that has one. Asked after the keys, which are the precision
     * target and must win where the line crosses them, and before the strip,
     * so a grab within a few pixels of the line is never a retime. The rects
     * are the ones the draw published, so the grab can never drift from the
     * line the director is aiming at. */
    else if (director_timeline_playhead_grab(
                 *runtime, float(event->mval[0]), float(event->mval[1])) &&
             begin_scrub(C, event, region, runtime))
    {
      return WM_UI_HANDLER_BREAK;
    }
    /* Between keys, the bar slides the camera's whole animation. */
    else if (!state.locked && point_inside(runtime->strip_bounds, event) &&
             begin_strip_drag(C, event, runtime))
    {
      return WM_UI_HANDLER_BREAK;
    }
    /* Away from the tick, the playhead is dragged from the RULER ROW and
     * nowhere else.
     *
     * A press anywhere in the viewport used to scrub, which left no gesture
     * for selecting keyframes and meant reaching for a keyframe and missing
     * it moved the playhead instead. The Dope Sheet divides its region the
     * same way: scrub on the ruler, select in the body. */
    else if (point_inside(runtime->ruler_bounds, event) &&
             begin_scrub(C, event, region, runtime))
    {
      return WM_UI_HANDLER_BREAK;
    }
    else if (point_inside(runtime->viewport_bounds, event)) {
      /* The body: drag to box-select, click to clear the selection. The
       * running drag belongs to `director_timeline_selection_event`, which
       * is asked before this branch on every following event. */
      director_timeline_box_begin(runtime, event);
      return WM_UI_HANDLER_BREAK;
    }
    return WM_UI_HANDLER_CONTINUE;
  }
  if (event->type == RIGHTMOUSE && event->val == KM_PRESS && state.has_shot) {
    /* The strip menu, about the beat on the key under the pointer if it
     * carries one. */
    const int beat_index = key != nullptr ? key->beat : -1;
    if ((key != nullptr || point_inside(runtime->strip_bounds, event)) &&
        dispatch_int_operator(C, "mixar.director_strip_menu", "index", beat_index))
    {
      return WM_UI_HANDLER_BREAK;
    }
    return WM_UI_HANDLER_CONTINUE;
  }
  /* Standard delete keys remove keys when the pointer is over the timeline.
   * The `mixar.director_block_input` guard (Object Mode / WINDOW keymap)
   * swallows X/Del while directing to protect scene objects, but it never
   * sees keys pressed over this CHANNELS region — so the timeline must
   * handle its own deletion. Locked takes stay read-only. */
  if (ELEM(event->type, EVT_XKEY, EVT_DELKEY, EVT_BACKSPACEKEY) && event->val == KM_PRESS &&
      state.has_shot && !state.locked)
  {
    if (delete_keys(C, key)) {
      ED_region_tag_redraw(region);
      return WM_UI_HANDLER_BREAK;
    }
    return WM_UI_HANDLER_CONTINUE;
  }

  if (!point_inside(runtime->viewport_bounds, event)) {
    return WM_UI_HANDLER_CONTINUE;
  }
  if (event->type == MOUSESMARTZOOM) {
    runtime->view_initialized = false;
    runtime->view_user_modified = false;
    ED_region_tag_redraw(region);
    return WM_UI_HANDLER_BREAK;
  }
  if (ELEM(event->type, WHEELUPMOUSE, WHEELDOWNMOUSE)) {
    /* Plain wheel zooms, Shift or Ctrl + wheel pans — the same assignment
     * Blender's own animation editors use, so the muscle memory carries. */
    if (event->modifier & (KM_SHIFT | KM_CTRL)) {
      const float direction = event->type == WHEELUPMOUSE ? -1.0f : 1.0f;
      pan_frames(state, runtime, direction * runtime->view_span_frames * 0.08f);
    }
    else {
      zoom_at_event(state, runtime, event, event->type == WHEELUPMOUSE ? 0.82f : 1.22f);
    }
    ED_region_tag_redraw(region);
    return WM_UI_HANDLER_BREAK;
  }
  /* Home frames the whole shot, as it does in every other editor. Dropping
   * `view_initialized` hands the fit back to `sync_view`, which is the ONE
   * place that knows what "all" means for the active shot. */
  if (event->type == EVT_HOMEKEY && event->val == KM_PRESS) {
    runtime->view_initialized = false;
    runtime->view_user_modified = false;
    ED_region_tag_redraw(region);
    return WM_UI_HANDLER_BREAK;
  }
  if (ELEM(event->type, MOUSEZOOM, MOUSEPAN)) {
    const float dx = float(WM_event_absolute_delta_x(event));
    const float dy = float(WM_event_absolute_delta_y(event));
    if (event->type == MOUSEPAN && std::abs(dx) > std::abs(dy) * 1.15f) {
      const float frames_per_pixel = runtime->view_span_frames /
                                     std::max(BLI_rctf_size_x(&runtime->viewport_bounds), 1.0f);
      pan_frames(state, runtime, -dx * frames_per_pixel);
    }
    else {
      const float delta = std::abs(dy) >= std::abs(dx) ? dy : dx;
      const float factor = std::clamp(std::exp(-delta * 0.018f), 0.55f, 1.8f);
      zoom_at_event(state, runtime, event, factor);
    }
    ED_region_tag_redraw(region);
    return WM_UI_HANDLER_BREAK;
  }
  return WM_UI_HANDLER_CONTINUE;
}

void timeline_ui_handler_remove(bContext * /*C*/, void * /*userdata*/) {}

}  // namespace

DirectorTimelineRuntime *view3d_director_timeline_runtime_ensure(ARegion *region)
{
  if (!region->regiondata) {
    region->regiondata = MEM_new<DirectorTimelineRuntime>("DirectorTimelineRuntime");
    region->flag |= RGN_FLAG_TEMP_REGIONDATA;
  }
  return static_cast<DirectorTimelineRuntime *>(region->regiondata);
}

void view3d_director_timeline_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  view3d_director_timeline_runtime_ensure(region);
  WM_event_remove_ui_handler(
      &region->runtime->handlers, timeline_ui_handler, timeline_ui_handler_remove, nullptr, false);
  WM_event_add_ui_handler(nullptr,
                          &region->runtime->handlers,
                          timeline_ui_handler,
                          timeline_ui_handler_remove,
                          nullptr,
                          eWM_EventHandlerFlag(0));
}

void view3d_director_timeline_region_free(ARegion *region)
{
  DirectorTimelineRuntime *runtime = static_cast<DirectorTimelineRuntime *>(region->regiondata);
  if (runtime) {
    MEM_delete(runtime);
    region->regiondata = nullptr;
  }
}

void *view3d_director_timeline_region_duplicate(void * /*regiondata*/)
{
  return nullptr;
}
}  // namespace blender
