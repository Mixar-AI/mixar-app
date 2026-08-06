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

namespace {

bool point_inside(const rctf &rect, const wmEvent *event)
{
  return BLI_rctf_isect_pt(&rect, float(event->mval[0]), float(event->mval[1]));
}

int beat_at_event(const DirectorTimelineRuntime &runtime, const wmEvent *event)
{
  for (const DirectorTimelineBeatHit &hit : runtime.beat_hits) {
    if (point_inside(hit.bounds, event)) {
      return hit.index;
    }
  }
  return -1;
}

bool dispatch_int_operator(bContext *C, const char *idname, const char *property, const int value)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (!ot) {
    return false;
  }
  PointerRNA op_ptr;
  WM_operator_properties_create_ptr(&op_ptr, ot);
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
  PointerRNA op_ptr;
  WM_operator_properties_create_ptr(&op_ptr, ot);
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
  PointerRNA op_ptr;
  WM_operator_properties_create_ptr(&op_ptr, ot);
  RNA_float_set(&op_ptr, "frames_per_pixel", runtime->view_span_frames / width);
  RNA_float_set(
      &op_ptr, "origin_px", float(region->winrct.xmin) + runtime->viewport_bounds.xmin);
  RNA_float_set(&op_ptr, "start_frame", runtime->view_start_frame);
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::InvokeRegionWin, &op_ptr, event);
  WM_operator_properties_free(&op_ptr);
  return (result & OPERATOR_RUNNING_MODAL) != 0;
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
  runtime->view_start_frame = std::max(float(state.scene_frame_start),
                                       anchor_frame - anchor_t * new_span);
  runtime->view_span_frames = new_span;
  runtime->view_user_modified = true;
}

void pan_frames(const DirectorViewState &state,
                DirectorTimelineRuntime *runtime,
                const float delta_frames)
{
  runtime->view_start_frame = std::max(float(state.scene_frame_start),
                                       runtime->view_start_frame + delta_frames);
  runtime->view_user_modified = true;
}

void update_hover(ARegion *region,
                  const DirectorViewState &state,
                  DirectorTimelineRuntime *runtime,
                  const wmEvent *event)
{
  const int hovered_beat = beat_at_event(*runtime, event);
  const bool strip_hovered = !state.locked && hovered_beat < 0 &&
                             point_inside(runtime->strip_bounds, event);
  if (hovered_beat != runtime->hovered_beat || strip_hovered != runtime->strip_hovered) {
    runtime->hovered_beat = hovered_beat;
    runtime->strip_hovered = strip_hovered;
    ED_region_tag_redraw(region);
  }
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

  if (event->type == MOUSEMOVE) {
    update_hover(region, state, runtime, event);
    return WM_UI_HANDLER_CONTINUE;
  }
  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    const int beat_index = beat_at_event(*runtime, event);
    if (beat_index >= 0) {
      if (dispatch_int_operator(C, "mixar.director_jump_beat", "index", beat_index)) {
        ED_region_tag_redraw(region);
        return WM_UI_HANDLER_BREAK;
      }
    }
    else if (!state.locked && point_inside(runtime->strip_bounds, event) &&
             begin_strip_drag(C, event, runtime))
    {
      return WM_UI_HANDLER_BREAK;
    }
    else if (point_inside(runtime->viewport_bounds, event) &&
             begin_scrub(C, event, region, runtime))
    {
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
    if (event->modifier & KM_SHIFT) {
      const float direction = event->type == WHEELUPMOUSE ? -1.0f : 1.0f;
      pan_frames(state, runtime, direction * runtime->view_span_frames * 0.08f);
    }
    else {
      zoom_at_event(state, runtime, event, event->type == WHEELUPMOUSE ? 0.82f : 1.22f);
    }
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
