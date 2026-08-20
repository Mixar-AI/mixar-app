/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard zoom operator
 */

#include "mixie_moodboard_ops_common.hh"

#include "DNA_windowmanager_types.h"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Moodboard Zoom Operator
 * \{ */

static wmOperatorStatus moodboard_zoom_invoke(bContext *C, wmOperator * /*op*/, const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return OPERATOR_PASS_THROUGH;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");

  if (!prop) {
    return OPERATOR_PASS_THROUGH;
  }

  bool any_selected = false;
  int image_count = RNA_property_collection_length(&scene_ptr, prop);

  for (int i = 0; i < image_count; i++) {
    PointerRNA item_ptr;
    RNA_property_collection_lookup_int(&scene_ptr, prop, i, &item_ptr);
    PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
    if (sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop)) {
      any_selected = true;
      break;
    }
  }

  const float sensitivity = 0.01f;
  int delta_x = WM_event_absolute_delta_x(event);
  float zoom_delta = float(delta_x) * sensitivity;

  if (!any_selected) {
    ARegion *region = CTX_wm_region(C);
    View2D *v2d = &region->v2d;

    float zoom_factor = 1.0f - zoom_delta;
    zoom_factor = std::max(0.1f, std::min(10.0f, zoom_factor));

    float cur_width = BLI_rctf_size_x(&v2d->cur);
    float cur_height = BLI_rctf_size_y(&v2d->cur);

    float new_width = cur_width * zoom_factor;
    float new_height = cur_height * zoom_factor;

    float center_x = (v2d->cur.xmin + v2d->cur.xmax) / 2.0f;
    float center_y = (v2d->cur.ymin + v2d->cur.ymax) / 2.0f;

    v2d->cur.xmin = center_x - new_width / 2.0f;
    v2d->cur.xmax = center_x + new_width / 2.0f;
    v2d->cur.ymin = center_y - new_height / 2.0f;
    v2d->cur.ymax = center_y + new_height / 2.0f;

    ui::view2d_curRect_validate(v2d);
    ui::view2d_curRect_changed(C, v2d);
    ED_area_tag_redraw(CTX_wm_area(C));

    return OPERATOR_FINISHED;
  }

  bool any_updated = false;

  for (int i = 0; i < image_count; i++) {
    PointerRNA item_ptr;
    RNA_property_collection_lookup_int(&scene_ptr, prop, i, &item_ptr);

    PropertyRNA *sel_prop = RNA_struct_find_property(&item_ptr, "selected");
    if (sel_prop && RNA_property_boolean_get(&item_ptr, sel_prop)) {
      PropertyRNA *scale_prop = RNA_struct_find_property(&item_ptr, "scale");
      if (scale_prop) {
        float current_scale = RNA_property_float_get(&item_ptr, scale_prop);
        float new_scale = current_scale * (1.0f + zoom_delta);

        new_scale = std::max(MOODBOARD_IMAGE_MIN_SCALE, std::min(MOODBOARD_IMAGE_MAX_SCALE, new_scale));

        if (new_scale != current_scale) {
          RNA_property_float_set(&item_ptr, scale_prop, new_scale);
          any_updated = true;
        }
      }
    }
  }

  if (any_updated) {
    ED_area_tag_redraw(CTX_wm_area(C));
  }

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

/* Grow one region's visible rect so the target is on screen.  Returns true if
 * the view was changed. */
static bool ensure_rect_visible_in_region(ARegion *region,
                                          const float tx_min,
                                          const float tx_max,
                                          const float ty_min,
                                          const float ty_max)
{
  View2D *v2d = &region->v2d;

  /* Already fully inside the visible rect: nothing to do. */
  if (tx_min >= v2d->cur.xmin && tx_max <= v2d->cur.xmax && ty_min >= v2d->cur.ymin &&
      ty_max <= v2d->cur.ymax)
  {
    return false;
  }

  /* Grow the visible rect to also contain the target, then let View2D
   * re-validate zoom/aspect limits (which can only enlarge the area, so the
   * target stays visible). */
  v2d->cur.xmin = std::min(v2d->cur.xmin, tx_min);
  v2d->cur.xmax = std::max(v2d->cur.xmax, tx_max);
  v2d->cur.ymin = std::min(v2d->cur.ymin, ty_min);
  v2d->cur.ymax = std::max(v2d->cur.ymax, ty_max);

  ui::view2d_curRect_validate(v2d);
  ED_region_tag_redraw(region);
  return true;
}

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

  for (wmWindow *win = static_cast<wmWindow *>(wm->windows.first); win; win = win->next) {
    bScreen *screen = WM_window_get_active_screen(win);
    if (!screen) {
      continue;
    }
    for (ScrArea *area = static_cast<ScrArea *>(screen->areabase.first); area; area = area->next)
    {
      if (area->spacetype != SPACE_MIXIE) {
        continue;
      }
      SpaceMixie *smixie = static_cast<SpaceMixie *>(area->spacedata.first);
      if (!smixie || smixie->mode != MIXIE_MODE_MOODBOARD) {
        continue;
      }
      for (ARegion *region = static_cast<ARegion *>(area->regionbase.first); region;
           region = region->next)
      {
        if (region->regiontype != RGN_TYPE_WINDOW) {
          continue;
        }
        if (ensure_rect_visible_in_region(region, tx_min, tx_max, ty_min, ty_max)) {
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
  ot->name = "Zoom Selected Images";
  ot->idname = "MIXIE_OT_moodboard_zoom";
  ot->description = "Zoom selected images using pinch gesture";

  ot->invoke = blender::ed::mixie::moodboard_zoom_invoke;
  ot->poll = blender::ed::mixie::moodboard_poll;

  ot->flag = 0;
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
