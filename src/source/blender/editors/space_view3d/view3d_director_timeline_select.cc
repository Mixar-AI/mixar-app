/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Multi-keyframe selection on the Director timeline: click, Shift+click,
 * B-armed box select, A / Alt+A, and the drag and delete that act on the
 * result — the gesture set the Dope Sheet trains every Blender user in.
 *
 * The selection lives in the region's runtime, beside the hit rects it refers
 * to, because it is view state: a .blend must not carry which keyframes
 * happened to be selected, and an index means nothing once the shot or the
 * beat count changes (`director_timeline_selection_sync` drops it then).
 *
 * The gestures live here; the MOVES live in Python
 * (`mixar.director_drag_beats`, `mixar.director_remove_beats`), so the native
 * layer still only reads Director RNA and invokes Python operators.
 */

#include <algorithm>
#include <string>
#include <utility>

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

/** The selection as the operators' `indices` property wants it. */
std::string selection_string(const DirectorTimelineRuntime &runtime)
{
  std::string text;
  for (const int index : runtime.selected) {
    if (!text.empty()) {
      text += ',';
    }
    text += std::to_string(index);
  }
  return text;
}

void select_only(DirectorTimelineRuntime *runtime, const int index)
{
  runtime->selected.clear();
  if (index >= 0) {
    runtime->selected.append(index);
  }
}

/** Whether \a index is in \a selected. `std::find` rather than a container
 * helper: this file is built against whatever `blender::Vector` the pinned
 * upstream ships, and the standard algorithm is the same either way. */
bool contains(const blender::Vector<int> &selected, const int index)
{
  return std::find(selected.begin(), selected.end(), index) != selected.end();
}

void select_toggle(DirectorTimelineRuntime *runtime, const int index)
{
  if (!contains(runtime->selected, index)) {
    runtime->selected.append(index);
    return;
  }
  blender::Vector<int> kept;
  for (const int existing : runtime->selected) {
    if (existing != index) {
      kept.append(existing);
    }
  }
  runtime->selected = std::move(kept);
}

void select_all(DirectorTimelineRuntime *runtime, const int beat_count)
{
  runtime->selected.clear();
  for (int index = 0; index < beat_count; index++) {
    runtime->selected.append(index);
  }
}

bool dispatch_with_indices(bContext *C,
                           const char *idname,
                           const DirectorTimelineRuntime &runtime,
                           const float frames_per_pixel,
                           const wmEvent *event)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (ot == nullptr || runtime.selected.is_empty()) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&op_ptr, "indices", selection_string(runtime).c_str());
  if (frames_per_pixel > 0.0f) {
    RNA_float_set(&op_ptr, "frames_per_pixel", frames_per_pixel);
  }
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C,
      ot,
      event ? blender::wm::OpCallContext::InvokeRegionWin :
              blender::wm::OpCallContext::ExecDefault,
      &op_ptr,
      event);
  WM_operator_properties_free(&op_ptr);
  return (result & (OPERATOR_FINISHED | OPERATOR_RUNNING_MODAL)) != 0;
}

/** Select every beat whose handle intersects the dragged box. */
void select_in_box(const DirectorTimelineRuntime &runtime,
                   DirectorTimelineRuntime *out,
                   const rctf &box)
{
  if (!out->box_extend) {
    out->selected.clear();
  }
  for (const DirectorTimelineBeatHit &hit : runtime.beat_hits) {
    if (!BLI_rctf_isect(&box, &hit.bounds, nullptr)) {
      continue;
    }
    if (!contains(out->selected, hit.index)) {
      out->selected.append(hit.index);
    }
  }
}

}  // namespace

bool director_timeline_is_selected(const DirectorTimelineRuntime &runtime, const int index)
{
  return contains(runtime.selected, index);
}

void director_timeline_selection_sync(DirectorTimelineRuntime *runtime,
                                      const void *shot_identity,
                                      const int beat_count)
{
  if (runtime->shot_identity != shot_identity || runtime->content_count != beat_count) {
    runtime->selected.clear();
    runtime->box_arming = false;
    runtime->box_dragging = false;
    return;
  }
  /* An index past the end can survive a reorder that kept the count. */
  blender::Vector<int> kept;
  for (const int index : runtime->selected) {
    if (index >= 0 && index < beat_count) {
      kept.append(index);
    }
  }
  runtime->selected = std::move(kept);
}

bool view3d_director_timeline_selection(const bContext *C, blender::Vector<int> *r_selected)
{
  r_selected->clear();
  const ScrArea *area = CTX_wm_area(C);
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    return false;
  }
  /* The dock's OWN region, not whatever region `C` currently names — this is
   * called from a popup, whose region is a temporary of its own. Read-only:
   * never `_ensure`, which would allocate a runtime onto a region that has
   * not drawn yet. */
  const ARegion *dock = BKE_area_find_region_type(const_cast<ScrArea *>(area), RGN_TYPE_CHANNELS);
  if (dock == nullptr || dock->regiondata == nullptr) {
    return false;
  }
  const DirectorTimelineRuntime *runtime = static_cast<const DirectorTimelineRuntime *>(
      dock->regiondata);
  for (const int index : runtime->selected) {
    r_selected->append(index);
  }
  return !r_selected->is_empty();
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
                                       const int hovered_beat)
{
  const int beat_count = int(state.beats.size());
  if (!state.has_shot || beat_count == 0) {
    return false;
  }

  /* ---- Box select, armed by B (the key the Dope Sheet uses) ---- */
  if (event->type == EVT_BKEY && event->val == KM_PRESS && !state.locked) {
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
        select_in_box(*runtime, runtime, box);
      }
      else if (!runtime->box_extend) {
        /* A click on empty timeline clears the selection, as it does in every
         * Blender editor. Shift+click keeps what is there. */
        runtime->selected.clear();
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
    if (event->modifier & KM_ALT) {
      runtime->selected.clear();
    }
    else {
      select_all(runtime, beat_count);
    }
    ED_region_tag_redraw(region);
    return true;
  }

  /* ---- Click and Shift+click on a handle ---- */
  if (event->type == LEFTMOUSE && event->val == KM_PRESS && hovered_beat >= 0) {
    if (event->modifier & KM_SHIFT) {
      /* Extending is a selection gesture only: it must never also start a
       * drag, or building a selection would retime what is already in it. */
      select_toggle(runtime, hovered_beat);
      ED_region_tag_redraw(region);
      return true;
    }
    if (!director_timeline_is_selected(*runtime, hovered_beat)) {
      /* A plain click on an unselected handle makes it THE selection, the
       * way it does in every Blender editor. */
      select_only(runtime, hovered_beat);
      ED_region_tag_redraw(region);
    }
    /* Only a multi-selection needs the multi-drag; a single handle keeps the
     * existing single-beat drag, which also jumps the playhead on invoke. */
    if (!state.locked && runtime->selected.size() > 1) {
      const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
      if (width > 0.0f &&
          dispatch_with_indices(C,
                                "mixar.director_drag_beats",
                                *runtime,
                                runtime->view_span_frames / width,
                                event))
      {
        runtime->view_user_modified = true;
        return true;
      }
    }
    return false;
  }

  /* ---- Duplicate ---- */
  /* Shift+D, the gesture the Dope Sheet and the viewport both train. Unlike
   * theirs it does not start a grab: the copies land after the shot's last
   * keyframe with their spacing kept, because two Director keys on one frame
   * would be unrecoverable — beats and native keys are matched BY FRAME. */
  if (event->type == EVT_DKEY && event->val == KM_PRESS && (event->modifier & KM_SHIFT) &&
      !state.locked && !runtime->selected.is_empty())
  {
    if (dispatch_with_indices(C, "mixar.director_duplicate_beats", *runtime, 0.0f, nullptr)) {
      /* Hand the copies straight to the drag, the way Shift+D does
       * everywhere in Blender. A duplicate that lands a beat further on and
       * stops there is a duplicate the director then has to go and find; what
       * they wanted was this pose, HERE.
       *
       * The copies are appended, so they are every index past the old count.
       * `content_count` is corrected too, or the next draw's sync sees a
       * changed count and drops the selection out from under the drag. */
      const int before = beat_count;
      int after = before;
      PointerRNA shot_ptr = {};
      if (view3d_director_active_shot_pointer(CTX_data_scene(C), &shot_ptr)) {
        if (PropertyRNA *beats = RNA_struct_find_property(&shot_ptr, "beats")) {
          after = RNA_property_collection_length(&shot_ptr, beats);
        }
      }
      runtime->selected.clear();
      for (int index = before; index < after; index++) {
        runtime->selected.append(index);
      }
      runtime->content_count = after;
      ED_region_tag_redraw(region);
      const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
      if (!runtime->selected.is_empty() && width > 0.0f) {
        /* Esc cancels the MOVE, not the duplicate — the copies stay where
         * they were placed, which is what Blender's own duplicate-grab does. */
        if (dispatch_with_indices(C,
                                  "mixar.director_drag_beats",
                                  *runtime,
                                  runtime->view_span_frames / width,
                                  event))
        {
          runtime->view_user_modified = true;
        }
      }
      return true;
    }
  }

  /* ---- Delete a multi-selection ---- */
  if (ELEM(event->type, EVT_XKEY, EVT_DELKEY, EVT_BACKSPACEKEY) && event->val == KM_PRESS &&
      !state.locked && runtime->selected.size() > 1)
  {
    if (dispatch_with_indices(C, "mixar.director_remove_beats", *runtime, 0.0f, nullptr)) {
      runtime->selected.clear();
      ED_region_tag_redraw(region);
      return true;
    }
  }
  return false;
}

}  // namespace blender
