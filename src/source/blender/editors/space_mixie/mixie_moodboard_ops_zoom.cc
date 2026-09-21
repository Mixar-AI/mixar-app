/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard zoom operator
 */

#include "mixie_moodboard_ops_common.hh"
#include "mixie_moodboard_node_layout.hh"

#include "DNA_windowmanager_types.h"
#include "DNA_workspace_types.h"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Moodboard Zoom Operator
 * \{ */

static wmOperatorStatus moodboard_zoom_invoke(bContext *C, wmOperator * /*op*/, const wmEvent *event)
{
  /* Pinch always changes the canvas view. Item size is the corner-handle
   * resize gesture; writing `scale` here made a selected picture grow in
   * board units while the user was trying to zoom. */
  ARegion *region = CTX_wm_region(C);
  if (!region) {
    return OPERATOR_PASS_THROUGH;
  }

  View2D *v2d = &region->v2d;
  const float zoom_delta = float(WM_event_absolute_delta_x(event)) * 0.01f;
  const float zoom_factor = std::max(0.1f, std::min(10.0f, 1.0f - zoom_delta));

  const float new_width = BLI_rctf_size_x(&v2d->cur) * zoom_factor;
  const float new_height = BLI_rctf_size_y(&v2d->cur) * zoom_factor;
  const float center_x = BLI_rctf_cent_x(&v2d->cur);
  const float center_y = BLI_rctf_cent_y(&v2d->cur);

  v2d->cur.xmin = center_x - new_width / 2.0f;
  v2d->cur.xmax = center_x + new_width / 2.0f;
  v2d->cur.ymin = center_y - new_height / 2.0f;
  v2d->cur.ymax = center_y + new_height / 2.0f;

  ui::view2d_curRect_validate(v2d);
  ui::view2d_curRect_changed(C, v2d);
  ED_area_tag_redraw(CTX_wm_area(C));
  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Ensure-Visible Operator
 *
 * Zooms the moodboard view out just enough that a target canvas rectangle
 * (e.g. a newly added image) becomes visible.  The current view content stays
 * visible too: the visible rect is grown to the union of itself and the target.
 * A no-op when the target is already on screen.
 * \{ */

/* Framing keeps the screen-sized title/action row above the topmost card.
 * Canvas-unit margins shrink at low zoom and cannot provide this clearance. */
static rcti framing_content_rect(const ScrArea *area, ARegion *region)
{
  rcti content = moodboard_visible_canvas_rect(area, region);
  const int title_height = int(
      (MOODBOARD_NODE_HEADER_LIFT + MOODBOARD_NODE_HEADER_ROW_H) * UI_SCALE_FAC);
  content.ymax -= std::min(title_height, std::max(BLI_rcti_size_y(&content) / 2, 0));
  return content;
}

/* Grow one region's visible rect so the target is on screen.  Returns true if
 * the view was changed. */
static void frame_in_content_rect(ARegion *region, const rcti &content, const rctf &bounds)
{
  View2D *v2d = &region->v2d;
  const float units_per_pixel = std::max(
      BLI_rctf_size_x(&bounds) / std::max(BLI_rcti_size_x(&content), 1),
      BLI_rctf_size_y(&bounds) / std::max(BLI_rcti_size_y(&content), 1));
  const float xmin = BLI_rctf_cent_x(&bounds) -
                     (BLI_rcti_cent_x(&content) - v2d->mask.xmin) * units_per_pixel;
  const float ymin = BLI_rctf_cent_y(&bounds) -
                     (BLI_rcti_cent_y(&content) - v2d->mask.ymin) * units_per_pixel;
  BLI_rctf_init(&v2d->cur, xmin, xmin + BLI_rcti_size_x(&v2d->mask) * units_per_pixel,
                ymin, ymin + BLI_rcti_size_y(&v2d->mask) * units_per_pixel);
  ui::view2d_curRect_validate(v2d);
}

static bool ensure_rect_visible_in_region(const ScrArea *area,
                                          ARegion *region,
                                          const float tx_min,
                                          const float tx_max,
                                          const float ty_min,
                                          const float ty_max)
{
  View2D *v2d = &region->v2d;

  const rcti content = framing_content_rect(area, region);
  rctf visible;
  ui::view2d_region_to_view(v2d, content.xmin, content.ymin, &visible.xmin, &visible.ymin);
  ui::view2d_region_to_view(v2d, content.xmax, content.ymax, &visible.xmax, &visible.ymax);
  /* Controls and overlapping sidebars are never usable canvas space. */
  if (tx_min >= visible.xmin && tx_max <= visible.xmax && ty_min >= visible.ymin &&
      ty_max <= visible.ymax)
  {
    return false;
  }

  /* Grow the visible rect to also contain the target, then let View2D
   * re-validate zoom/aspect limits (which can only enlarge the area, so the
   * target stays visible). */
  visible.xmin = std::min(visible.xmin, tx_min);
  visible.xmax = std::max(visible.xmax, tx_max);
  visible.ymin = std::min(visible.ymin, ty_min);
  visible.ymax = std::max(visible.ymax, ty_max);
  frame_in_content_rect(region, content, visible);
  ED_region_tag_redraw(region);
  return true;
}

/* -------------------------------------------------------------------- */
/** \name Moodboard Frame Operator
 *
 * Fit the view to the board, or to the selection. Distinct from ensure-visible
 * above, which only ever GROWS the visible rect so a new item comes on screen:
 * it cannot zoom in, so it can never actually frame anything.
 * \{ */

/* Union of every canvas rect, or of the selected items only. Returns false when
 * there is nothing to frame, so the caller can report rather than zoom to a
 * degenerate box. */
static bool moodboard_content_bounds(PointerRNA *scene_ptr,
                                     const bool selected_only,
                                     rctf *r_bounds)
{
  bool found = false;
  /* Media, action and asset nodes share one rect definition already -- the
   * graph cache -- so framing cannot drift from what is drawn. It is keyed by
   * node id, so selection is resolved by looking each id back up. */
  MoodboardGraphCache cache;
  moodboard_graph_cache_build(scene_ptr, &cache);
  for (const auto &item : cache.outputs.items()) {
    if (selected_only && !moodboard_graph_node_id_selected(scene_ptr, item.key.c_str())) {
      continue;
    }
    if (!found) {
      *r_bounds = item.value;
      found = true;
    }
    else {
      BLI_rctf_union(r_bounds, &item.value);
    }
  }

  /* Text boxes are not graph nodes and so are not in the cache. */
  PropertyRNA *boxes = RNA_struct_find_property(scene_ptr, "mixie_moodboard_textboxes");
  const int box_count = boxes ? RNA_property_collection_length(scene_ptr, boxes) : 0;
  for (int index = 0; index < box_count; index++) {
    PointerRNA box;
    RNA_property_collection_lookup_int(scene_ptr, boxes, index, &box);
    if (selected_only && !RNA_boolean_get(&box, "selected")) {
      continue;
    }
    rctf rect;
    rect.xmin = RNA_float_get(&box, "position_x");
    rect.ymin = RNA_float_get(&box, "position_y");
    rect.xmax = rect.xmin + RNA_float_get(&box, "width");
    rect.ymax = rect.ymin + RNA_float_get(&box, "height");
    if (!found) {
      *r_bounds = rect;
      found = true;
    }
    else {
      BLI_rctf_union(r_bounds, &rect);
    }
  }

  /* Frames are not graph nodes either, and an EMPTY frame is still content --
   * it is a region of the board the user deliberately claimed, so Home must
   * fit it and Frame Selected must go to it. */
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  const int frame_count = frames ? RNA_property_collection_length(scene_ptr, frames) : 0;
  for (int index = 0; index < frame_count; index++) {
    PointerRNA frame;
    RNA_property_collection_lookup_int(scene_ptr, frames, index, &frame);
    if (selected_only && !RNA_boolean_get(&frame, "selected")) {
      continue;
    }
    rctf rect;
    moodboard_frame_rect(&frame, &rect);
    if (!found) {
      *r_bounds = rect;
      found = true;
    }
    else {
      BLI_rctf_union(r_bounds, &rect);
    }
  }
  return found;
}

static wmOperatorStatus moodboard_frame_exec(bContext *C, wmOperator *op)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  const bool selected_only = RNA_boolean_get(op->ptr, "selected_only");

  rctf bounds{};
  if (!moodboard_content_bounds(&scene_ptr, selected_only, &bounds)) {
    BKE_report(op->reports,
               RPT_INFO,
               selected_only ? "Nothing selected to frame" : "The board is empty");
    return OPERATOR_CANCELLED;
  }

  /* A margin proportional to the content, floored so framing a single small
   * card does not fill the viewport with it. */
  const float margin = std::max(BLI_rctf_size_x(&bounds), BLI_rctf_size_y(&bounds)) * 0.06f;
  BLI_rctf_pad(&bounds, std::max(margin, 40.0f), std::max(margin, 40.0f));

  /* Unlike ensure-visible this SETS the rect, so the view zooms in as well as
   * out. View2D then re-validates it against the region aspect and the zoom
   * limits, which can only enlarge it -- the content stays framed. */
  frame_in_content_rect(region, framing_content_rect(CTX_wm_area(C), region), bounds);
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}

/** \} */

static wmOperatorStatus moodboard_ensure_visible_exec(bContext *C, wmOperator *op)
{
  const float x = RNA_float_get(op->ptr, "x");
  const float y = RNA_float_get(op->ptr, "y");
  const float width = RNA_float_get(op->ptr, "width");
  const float height = RNA_float_get(op->ptr, "height");
  const float margin = RNA_float_get(op->ptr, "margin");

  const float tx_min = x - margin;
  const float tx_max = x + width + margin;
  const float ty_min = y - margin;
  const float ty_max = y + height + margin;

  /* Find every moodboard region ourselves instead of relying on the context
   * region: this operator is invoked from background-download timers (generated
   * images) where there is no active region in the context. */
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return OPERATOR_CANCELLED;
  }

  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *drawer_amount_prop = RNA_struct_find_property(&wm_ptr,
                                                            "mixar_moodboard_drawer_amount");
  const float drawer_amount = drawer_amount_prop != nullptr ?
                                  RNA_property_float_get(&wm_ptr, drawer_amount_prop) :
                                  0.0f;
  PropertyRNA *drawer_target_prop = RNA_struct_find_property(&wm_ptr, "mixar_moodboard_drawer_target");
  const bool drawer_live = drawer_amount >= MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT ||
                           (drawer_target_prop && RNA_property_int_get(&wm_ptr, drawer_target_prop));

  for (wmWindow *win = static_cast<wmWindow *>(wm->windows.first); win; win = win->next) {
    bScreen *screen = WM_window_get_active_screen(win);
    if (!screen) {
      continue;
    }
    const WorkSpace *workspace = WM_window_get_active_workspace(win);
    const bool zen = workspace != nullptr && STREQ(workspace->id.name + 2, "Zen Mode");
    for (ScrArea *area = static_cast<ScrArea *>(screen->areabase.first); area; area = area->next)
    {
      const bool mixie_canvas = area->spacetype == SPACE_MIXIE;
      const bool drawer_canvas = zen && drawer_live && area->spacetype == SPACE_VIEW3D;
      if (!mixie_canvas && !drawer_canvas) {
        continue;
      }
      if (mixie_canvas) {
        SpaceMixie *smixie = static_cast<SpaceMixie *>(area->spacedata.first);
        if (!smixie || smixie->mode != MIXIE_MODE_MOODBOARD) {
          continue;
        }
      }
      const int want_region = mixie_canvas ? RGN_TYPE_WINDOW : RGN_TYPE_TOOL_PROPS;
      for (ARegion *region = static_cast<ARegion *>(area->regionbase.first); region;
           region = region->next)
      {
        if (region->regiontype != want_region) {
          continue;
        }
        if (ensure_rect_visible_in_region(area, region, tx_min, tx_max, ty_min, ty_max)) {
          ED_area_tag_redraw(area);
        }
      }
    }
  }

  return OPERATOR_FINISHED;
}

/** \} */

}  // namespace blender::ed::mixie


/* Mixar 5.2 port: operator registrations live in namespace blender. */
namespace blender {
/* -------------------------------------------------------------------- */
/** \name Operator Registration (C linkage)
 * \{ */

void MIXIE_OT_moodboard_zoom(wmOperatorType *ot)
{
  ot->name = "Zoom Moodboard";
  ot->idname = "MIXIE_OT_moodboard_zoom";
  ot->description = "Zoom the moodboard canvas";

  ot->invoke = blender::ed::mixie::moodboard_zoom_invoke;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = 0;
}

void MIXIE_OT_moodboard_frame(wmOperatorType *ot)
{
  ot->name = "Frame Moodboard";
  ot->idname = "MIXIE_OT_moodboard_frame";
  ot->description = "Fit the view to the whole board, or to the selection";

  ot->exec = blender::ed::mixie::moodboard_frame_exec;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = 0;

  /* PROP_SKIP_SAVE: this operator is bound twice, once per mode. Without it
   * the remembered value from the last run would leak into whichever binding
   * did not set it. */
  PropertyRNA *prop = RNA_def_boolean(ot->srna,
                                      "selected_only",
                                      false,
                                      "Selected Only",
                                      "Frame just the selected items");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}

void MIXIE_OT_moodboard_ensure_visible(wmOperatorType *ot)
{
  ot->name = "Frame Moodboard Region";
  ot->idname = "MIXIE_OT_moodboard_ensure_visible";
  ot->description = "Zoom the moodboard out if needed so a canvas region is visible";

  ot->exec = blender::ed::mixie::moodboard_ensure_visible_exec;
  /* No poll: the operator locates the moodboard region itself and is invoked
   * from background-download timers where the context has no MIXIE space. */

  ot->flag = 0;

  const float big = 1.0e7f;
  RNA_def_float(ot->srna, "x", 0.0f, -big, big, "X", "Target rect left edge (canvas)", -big, big);
  RNA_def_float(ot->srna, "y", 0.0f, -big, big, "Y", "Target rect bottom edge (canvas)", -big, big);
  RNA_def_float(ot->srna, "width", 0.0f, 0.0f, big, "Width", "Target rect width (canvas)", 0.0f, big);
  RNA_def_float(ot->srna, "height", 0.0f, 0.0f, big, "Height", "Target rect height (canvas)", 0.0f, big);
  RNA_def_float(ot->srna, "margin", 50.0f, 0.0f, big, "Margin", "Extra canvas margin to keep around the rect", 0.0f, big);
}

/** \} */
}  // namespace blender
