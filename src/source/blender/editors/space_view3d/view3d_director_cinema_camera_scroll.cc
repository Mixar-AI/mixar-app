/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: scrolling the "My Cameras" card.
 *
 * Split from the card itself (`view3d_director_cinema_cameras.cc`) because
 * they are different jobs and the painter was at the module size limit: that
 * file paints the rows and publishes where they landed, and this one is the
 * gesture that moves them. Everything it needs crosses through the public
 * `cinema_camera_list_*` API, so neither side reaches into the other.
 *
 * **A UI handler owns the gesture, not a keymap item.** The card is painted
 * into the 3D viewport's own WINDOW region, so a wheel over it is a wheel
 * over the viewport, and a keymap item has to beat `view3d.zoom` to be
 * reached at all — through the mode keymaps, "3D View Generic", the active
 * tool's keymap and whatever the UI layer does with the event first. Two
 * rounds of widening the operator's poll did not make the list scroll, which
 * is the answer: the poll was never being asked. UI handlers run BEFORE every
 * keymap (the toast click handler in `view3d_toast_click.cc` is installed on
 * this same region for exactly that reason), so the gesture is decided here
 * and `view3d.zoom` never sees it. `MIXAR_OT_director_scroll_cameras` stays
 * registered as the scriptable and QA-drivable entry point onto the same
 * `cinema_camera_list_scroll`, but nothing binds it to a key any more: one
 * gesture, one owner.
 *
 * Getting the gesture HERE was only half of it. The card re-snaps its window
 * onto the live camera's row whenever the camera it is following changes, and
 * a scroll that cleared "which camera" instead of adopting it made that
 * re-snap fire on the very next draw — the one the scroll itself tags. The
 * rows moved for no frames at all, which reads exactly like a wheel that does
 * nothing; see `cinema_camera_list_scroll` in
 * `view3d_director_cinema_cameras.cc`.
 */

#include <algorithm>

#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
/* `ARegion::runtime` is an opaque pointer in DNA; installing a UI handler
 * touches `runtime->handlers`, which needs the definition. */
#include "BKE_screen.hh"
#include "BKE_wm_runtime.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "ED_screen.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Wheel scrolling
 *
 * The surface paints and never hit-tests, so the card has no handler of its
 * own. Scrolling is an ordinary operator whose POLL is the scoping — the same
 * shape as `MIXAR_OT_director_place_camera` on the aerial map: bound to the
 * wheel at the head of the addon "3D View" keymap, it answers only while the
 * cursor is over the rows the painter published this frame and the list
 * actually overflows, so everywhere else the wheel keeps zooming the viewport.
 * \{ */

namespace {

/** Trackpad pixels not yet worth a row. Gesture state, so it lives with the
 * gesture rather than with the card's published geometry. */
float g_pan_remainder = 0.0f;

bool camera_list_scroll_poll(bContext *C)
{
  if (!view3d_director_is_directing(CTX_data_scene(C))) {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  if (!(area && region && area->spacetype == SPACE_VIEW3D &&
        region->regiontype == RGN_TYPE_WINDOW))
  {
    return false;
  }
  /* Polls carry no event, so the cursor comes from the window's event state
   * (the way `ui_view_drop_poll` finds its view). */
  const wmWindow *win = CTX_wm_window(C);
  if (!(win && win->runtime && win->runtime->eventstate)) {
    return false;
  }
  const int x = win->runtime->eventstate->xy[0] - region->winrct.xmin;
  const int y = win->runtime->eventstate->xy[1] - region->winrct.ymin;
  /* Anywhere on a painted CARD, not just the rows that can scroll.
   *
   * The card is opaque and the viewport is behind it; a wheel there used to
   * fall through to `view3d.zoom` whenever the list had nothing to scroll —
   * which is most of the time, since a handful of cameras all fit. What the
   * director saw was a list that ignored the wheel while the shot moved
   * underneath. The stage is deliberately NOT included: the wheel is the
   * viewport's there. */
  return cinema_camera_list_contains(region, x, y) || cinema_columns_contain(C, region, x, y);
}

/**
 * Rows to step for this event.
 *
 * A wheel binding ALONE left the card unscrollable on a laptop: a trackpad
 * two-finger scroll arrives as `MOUSEPAN`, not `WHEELUP/DOWNMOUSE`, so the
 * keymap simply never matched and the gesture fell through to the viewport —
 * which, with "Lock Camera to View" on for the session, dollies the shot
 * camera. That is the "the camera is getting affected" the list's scroll was
 * first reported as. The Parallel Agents panel hit the same wall and its
 * `agent_panel_scroll_invoke` records the same finding.
 *
 * The list steps in ROWS, so the gesture's pixels accumulate in the
 * published row pitch until they are worth one.
 * `WM_event_absolute_delta_y` already accounts for the "natural scrolling"
 * preference, so its sign is used as-is and never re-inverted here — a
 * second inversion is how this comes out backwards.
 */
int pan_rows(const wmEvent *event)
{
  const float pitch = std::max(cinema_camera_list_row_pitch(), 1.0f);
  g_pan_remainder += float(WM_event_absolute_delta_y(event));
  const int rows = int(g_pan_remainder / pitch);
  g_pan_remainder -= float(rows) * pitch;
  return rows;
}

int scroll_rows_for_event(wmOperator *op, const wmEvent *event)
{
  if (event->type != MOUSEPAN) {
    g_pan_remainder = 0.0f;
    return RNA_int_get(op->ptr, "delta");
  }
  return pan_rows(event);
}

wmOperatorStatus camera_list_scroll_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  /* Only the ROWS scroll. Over any other card the gesture is absorbed and
   * does nothing, which is what an opaque panel should do with it. */
  if (region != nullptr && cinema_camera_list_contains(region, event->mval[0], event->mval[1])) {
    const int rows = scroll_rows_for_event(op, event);
    if (rows != 0 && cinema_camera_list_scroll(rows)) {
      ED_region_tag_redraw(region);
    }
  }
  return OPERATOR_FINISHED;
}

wmOperatorStatus camera_list_scroll_exec(bContext *C, wmOperator *op)
{
  if (!cinema_camera_list_scroll(RNA_int_get(op->ptr, "delta"))) {
    /* Already at the end: absorb it anyway. Letting it through would zoom
     * the viewport from under a list the user is still scrolling. */
    return OPERATOR_FINISHED;
  }
  ARegion *region = CTX_wm_region(C);
  if (region != nullptr) {
    ED_region_tag_redraw(region);
  }
  return OPERATOR_FINISHED;
}

/**
 * Rows this event asks for, or 0.
 *
 * Both gestures land here. A trackpad two-finger scroll arrives as
 * `MOUSEPAN`, not `WHEELUP/DOWNMOUSE`, so a wheel-only path leaves the card
 * dead on a laptop; the Parallel Agents panel records the same finding.
 */
int rows_for_gesture(const wmEvent *event)
{
  if (event->type == WHEELUPMOUSE) {
    g_pan_remainder = 0.0f;
    return -1;
  }
  if (event->type == WHEELDOWNMOUSE) {
    g_pan_remainder = 0.0f;
    return 1;
  }
  return pan_rows(event);
}

int director_cinema_ui_handler(bContext *C, const wmEvent *event, void * /*userdata*/)
{
  if (!ELEM(event->type, WHEELUPMOUSE, WHEELDOWNMOUSE, MOUSEPAN)) {
    return WM_UI_HANDLER_CONTINUE;
  }
  if (!view3d_director_is_directing(CTX_data_scene(C))) {
    return WM_UI_HANDLER_CONTINUE;
  }
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  if (!area || area->spacetype != SPACE_VIEW3D || !region ||
      region->regiontype != RGN_TYPE_WINDOW)
  {
    return WM_UI_HANDLER_CONTINUE;
  }
  const int x = event->mval[0];
  const int y = event->mval[1];
  if (cinema_camera_list_contains(region, x, y)) {
    const int rows = rows_for_gesture(event);
    if (rows != 0 && cinema_camera_list_scroll(rows)) {
      ED_region_tag_redraw(region);
    }
    return WM_UI_HANDLER_BREAK;
  }
  if (cinema_columns_contain(C, region, x, y)) {
    /* The columns are OPAQUE and the viewport is behind them: a wheel there
     * must never zoom or — with "Lock Camera to View" on for the session —
     * dolly the shot camera out from under a card the director is reading. */
    return WM_UI_HANDLER_BREAK;
  }
  return WM_UI_HANDLER_CONTINUE;
}

void director_cinema_ui_handler_remove(bContext * /*C*/, void * /*userdata*/)
{
  /* Nothing to free: the card's scroll position belongs to the card. */
}

}  // namespace

void view3d_director_cinema_region_init(ARegion *region)
{
  WM_event_remove_ui_handler(&region->runtime->handlers,
                             director_cinema_ui_handler,
                             director_cinema_ui_handler_remove,
                             nullptr,
                             false);
  WM_event_add_ui_handler(nullptr,
                          &region->runtime->handlers,
                          director_cinema_ui_handler,
                          director_cinema_ui_handler_remove,
                          nullptr,
                          eWM_EventHandlerFlag(0));
}

void MIXAR_OT_director_scroll_cameras(wmOperatorType *ot)
{
  ot->name = "Scroll Cameras";
  ot->idname = "MIXAR_OT_director_scroll_cameras";
  ot->description = "Scroll the My Cameras list";

  ot->invoke = camera_list_scroll_invoke;
  ot->exec = camera_list_scroll_exec;
  ot->poll = camera_list_scroll_poll;

  /* Not OPTYPE_UNDO: a scroll position is view state, not scene data. */
  ot->flag = OPTYPE_INTERNAL;

  RNA_def_int(ot->srna, "delta", 1, -16, 16, "Delta", "Rows to scroll", -16, 16);
}

/** \} */

}  // namespace blender
