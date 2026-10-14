/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Key selection on the Director timeline: Shift+click, B-armed and body-drag
 * box select, A / Alt+A, and Shift+D — the gesture set the Dope Sheet trains
 * every Blender user in.
 *
 * The selection is Blender's own key selection, not dock state. These
 * gestures only hit-test the key columns the draw published and hand their
 * frames to `mixar.director_select_keys`, so what the dock selects the
 * Timeline and the Dope Sheet show selected, and the other way round. A
 * plain click on a key belongs to `mixar.director_drag_keys`, which selects
 * on its press (view3d_director_timeline_interaction.cc).
 */

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <string>

#include "BLI_rect.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_director_timeline.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Hand \a frames to `mixar.director_select_keys` in \a mode. */
bool select_keys(bContext *C, const blender::Span<float> frames, const char *mode)
{
  wmOperatorType *ot = WM_operatortype_find("mixar.director_select_keys", true);
  if (ot == nullptr) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&op_ptr, "frames", director_timeline_frames_string(frames).c_str());
  RNA_enum_set_identifier(C, &op_ptr, "mode", mode);
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  return (result & OPERATOR_FINISHED) != 0;
}

/** The columns whose hit rect meets the dragged box. */
blender::Vector<float> frames_in_box(const DirectorTimelineRuntime &runtime, const rctf &box)
{
  blender::Vector<float> frames;
  for (const DirectorTimelineKeyHit &hit : runtime.key_hits) {
    if (BLI_rctf_isect(&box, &hit.bounds, nullptr)) {
      frames.append(hit.frame);
    }
  }
  return frames;
}

/** Shift+D: duplicate the beats on the selected keys, then drag the copies. */
bool duplicate_selected(bContext *C, DirectorTimelineRuntime *runtime, const wmEvent *event)
{
  blender::Vector<int> beats;
  if (!view3d_director_timeline_selection(C, &beats)) {
    return false;
  }
  wmOperatorType *ot = WM_operatortype_find("mixar.director_duplicate_beats", true);
  if (ot == nullptr) {
    return false;
  }
  std::string indices;
  for (const int index : beats) {
    if (!indices.empty()) {
      indices += ',';
    }
    indices += std::to_string(index);
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&op_ptr, "indices", indices.c_str());
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  if ((result & OPERATOR_FINISHED) == 0) {
    return false;
  }
  /* The copies are the selection now (the operator makes them so). Hand
   * them straight to the drag, the way Shift+D does everywhere in Blender: a
   * duplicate that lands a beat further on and stops there is a duplicate
   * the director then has to go and find. Esc cancels the MOVE, not the
   * duplicate — Blender's own duplicate-grab behaves the same way. */
  wmOperatorType *drag = WM_operatortype_find("mixar.director_drag_keys", true);
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  if (drag != nullptr && width > 0.0f) {
    PointerRNA drag_ptr = WM_operator_properties_create_ptr(drag);
    RNA_boolean_set(&drag_ptr, "use_frame", false);
    RNA_float_set(&drag_ptr, "frames_per_pixel", runtime->view_span_frames / width);
    const wmOperatorStatus moved = WM_operator_name_call_ptr(
        C, drag, blender::wm::OpCallContext::InvokeRegionWin, &drag_ptr, event);
    WM_operator_properties_free(&drag_ptr);
    if (moved & OPERATOR_RUNNING_MODAL) {
      runtime->view_user_modified = true;
    }
  }
  return true;
}

}  // namespace

std::string director_timeline_frames_string(const blender::Span<float> frames)
{
  /* Thousandths, written as integers: integer formatting never reads the C
   * locale, so a decimal comma can never reach the operator's parser — and
   * floating-point `std::to_chars` is unavailable on the older macOS
   * deployment targets Blender builds for. */
  std::string text;
  for (const float frame : frames) {
    const long long milli = std::llround(double(frame) * 1000.0);
    const long long magnitude = milli < 0 ? -milli : milli;
    const long long fraction = magnitude % 1000;
    if (!text.empty()) {
      text += ',';
    }
    if (milli < 0) {
      text += '-';
    }
    text += std::to_string(magnitude / 1000);
    text += '.';
    text += char('0' + fraction / 100);
    text += char('0' + (fraction / 10) % 10);
    text += char('0' + fraction % 10);
  }
  return text;
}

void director_timeline_box_begin(DirectorTimelineRuntime *runtime, const wmEvent *event)
{
  runtime->box_arming = false;
  runtime->box_dragging = true;
  runtime->box_extend = (event->modifier & KM_SHIFT) != 0;
  runtime->box_start[0] = runtime->box_end[0] = event->mval[0];
  runtime->box_start[1] = runtime->box_end[1] = event->mval[1];
}

bool director_timeline_box_rect(const DirectorTimelineRuntime &runtime, rctf *r_rect)
{
  if (!runtime.box_dragging) {
    return false;
  }
  r_rect->xmin = float(std::min(runtime.box_start[0], runtime.box_end[0]));
  r_rect->xmax = float(std::max(runtime.box_start[0], runtime.box_end[0]));
  r_rect->ymin = float(std::min(runtime.box_start[1], runtime.box_end[1]));
  r_rect->ymax = float(std::max(runtime.box_start[1], runtime.box_end[1]));
  return true;
}

bool director_timeline_selection_event(bContext *C,
                                       ARegion *region,
                                       const DirectorViewState &state,
                                       DirectorTimelineRuntime *runtime,
                                       const wmEvent *event,
                                       const DirectorTimelineKeyHit *hovered_key)
{
  if (!state.has_shot || state.shot_camera == nullptr) {
    return false;
  }

  /* ---- Box select, armed by B (the key the Dope Sheet uses) ---- */
  if (event->type == EVT_BKEY && event->val == KM_PRESS) {
    runtime->box_arming = true;
    return true;
  }
  if (runtime->box_arming && ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE) &&
      event->val == KM_PRESS)
  {
    /* Armed and thought better of it: B must not leave a box waiting for the
     * next unrelated click. */
    runtime->box_arming = false;
    return true;
  }
  if (runtime->box_arming && event->type == LEFTMOUSE && event->val == KM_PRESS) {
    /* Through the shared start, so B-then-drag and a plain body drag cannot
     * disagree about the anchor or about what Shift means. */
    director_timeline_box_begin(runtime, event);
    return true;
  }
  if (runtime->box_dragging) {
    /* The release can land OUTSIDE this region: a region handler is only
     * offered events while the pointer is over its own region, so a drag
     * let go over the viewport never delivers its LEFTMOUSE up here and the
     * rubber band stayed glued to the cursor until the next unrelated
     * click. The next event the pointer brings back says the button has
     * already been let go, and that closes the box on the last corner we
     * did see — which is where the band was drawn. */
    const bool released_elsewhere = event->prev_type == LEFTMOUSE &&
                                    event->prev_val == KM_RELEASE;
    const bool released_here = event->type == LEFTMOUSE && event->val == KM_RELEASE;
    if (event->type == MOUSEMOVE && !released_elsewhere) {
      runtime->box_end[0] = event->mval[0];
      runtime->box_end[1] = event->mval[1];
      ED_region_tag_redraw(region);
      return true;
    }
    if (released_here || released_elsewhere) {
      rctf box;
      const bool dragged = std::abs(runtime->box_end[0] - runtime->box_start[0]) > 2 ||
                           std::abs(runtime->box_end[1] - runtime->box_start[1]) > 2;
      if (dragged && director_timeline_box_rect(*runtime, &box)) {
        select_keys(C, frames_in_box(*runtime, box), runtime->box_extend ? "EXTEND" : "SET");
      }
      else if (!runtime->box_extend) {
        /* A click on empty timeline clears the selection, as it does in every
         * Blender editor. Shift+click keeps what is there. */
        select_keys(C, {}, "NONE");
      }
      runtime->box_dragging = false;
      ED_region_tag_redraw(region);
      /* A release we only heard about second hand is not this event: the
       * pointer is moving again and whatever it is doing now is not ours. */
      return released_here;
    }
    if (ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE) && event->val == KM_PRESS) {
      runtime->box_dragging = false;
      ED_region_tag_redraw(region);
      return true;
    }
    return false;
  }

  /* ---- Select all / none ---- */
  if (event->type == EVT_AKEY && event->val == KM_PRESS) {
    select_keys(C, {}, (event->modifier & KM_ALT) ? "NONE" : "ALL");
    ED_region_tag_redraw(region);
    return true;
  }

  /* ---- Shift+click on a key ---- */
  if (event->type == LEFTMOUSE && event->val == KM_PRESS && hovered_key != nullptr &&
      (event->modifier & KM_SHIFT))
  {
    /* Extending is a selection gesture only: it must never also start a
     * drag, or building a selection would retime what is already in it. */
    const float frame = hovered_key->frame;
    select_keys(C, blender::Span<float>(&frame, 1), "TOGGLE");
    ED_region_tag_redraw(region);
    return true;
  }

  /* ---- Duplicate ---- */
  /* Shift+D, the gesture the Dope Sheet and the viewport both train. The
   * copies land after the shot's last keyframe with their spacing kept
   * (`core/duplicate.py`), then ride the drag. */
  if (event->type == EVT_DKEY && event->val == KM_PRESS && (event->modifier & KM_SHIFT) &&
      !state.locked)
  {
    if (duplicate_selected(C, runtime, event)) {
      ED_region_tag_redraw(region);
      return true;
    }
  }
  return false;
}

}  // namespace blender
