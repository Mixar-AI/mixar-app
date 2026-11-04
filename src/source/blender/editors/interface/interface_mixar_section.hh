/* SPDX-FileCopyrightText: 2025 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar custom UI widgets — styled containers and controls for moodboard panels.
 */

#pragma once

#include "BLI_sys_types.h" /* uchar, for the card flag accessors below. */
namespace blender {
struct ARegion;
}  // namespace blender

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

struct Layout;

/* -------------------------------------------------------------------- */
/* Appearance lives in Button::mixar_style. Native flag2 bits are untouched. */

/**
 * Marks an operator `But` whose double-click or Ctrl+click hands off to the
 * no-emboss Text button laid over it (a My Cameras rename), the way a
 * UI-list row hands its rename to the label above it — see the Mixar hook
 * in `do_but_BUT` (interface_handlers.cc) and
 * #UI_mixar_button_double_click_edits_label.
 *
 * `flag2` (above) and `Button::flag` have no free bit, so this lives in
 * `Button::drawflag`: upstream's anonymous draw-flag enum ends at
 * `BUT_ICON_INVERT = 1 << 27` and the field is an `int`, so bit 30 is the
 * safe claim (28/29 left for upstream growth, 31 is the sign bit).
 * Draw flags survive the per-redraw block rebuild on the active button
 * (`but_update_old_active_from_new` keeps the old button's own bits).
 */
#define UI_BUT_DRAW_MIXAR_DBLCLICK_EDITS_LABEL (1 << 30)

#define UI_BUT_MIXAR_DBLCLICK_EDITS_LABEL_SET(but) \
  ((but)->drawflag |= UI_BUT_DRAW_MIXAR_DBLCLICK_EDITS_LABEL)
#define UI_BUT_MIXAR_DBLCLICK_EDITS_LABEL_TEST(but) \
  (((but)->drawflag & UI_BUT_DRAW_MIXAR_DBLCLICK_EDITS_LABEL) != 0)

/* -------------------------------------------------------------------- */
/* Layout helpers                                                        */

/**
 * Create a styled section box layout.
 * \return Sub-layout to place items in, identical API to layout.box().
 */
Layout *UI_layout_mixar_section(Layout *layout);

/**
 * Mark the most recently created Menu/Block/Popover button in the layout's
 * block with a Dropdown descriptor so it renders with custom styling.
 *
 * Call this immediately after layout->prop() for an enum property.
 */
void UI_layout_mixar_mark_last_dropdown(Layout *layout);

/**
 * Mark the most recently created But (operator) button with
 * an Action descriptor so it renders as an accent action button.
 */
void UI_layout_mixar_mark_last_action(Layout *layout);

/**
 * Mark the most recently created Checkbox button with
 * a Toggle descriptor so it renders as a pill-shaped toggle switch.
 */
void UI_layout_mixar_mark_last_toggle(Layout *layout);

/**
 * Mark the most recently created Text button with
 * an Input descriptor so it renders with visible border and focus glow.
 */
void UI_layout_mixar_mark_last_input(Layout *layout);

/* -------------------------------------------------------------------- */
/* Custom panel category tab drawing for MIXIE space                     */


/**
 * Draw a custom styled panel category tab bar for the MIXIE space.
 * Replaces the default Blender vertical tab strip with a modern design:
 * dark background, accent-blue active pill with glow, subtle inactive tabs.
 */
void UI_panel_category_draw_all_mixar(ARegion *region, const char *category_id_active);
/**
 * Idname of the Mixar-drawn category tab under  mval (region-relative),
 * or null. Rects are recorded by #UI_panel_category_draw_all_mixar at draw
 * time; used by the MIXAR click hook in interface_panel.cc.
 */
const char *UI_mixar_panel_category_find_at(const ARegion *region, const int mval[2]);
/**
 * Region-relative hit rect recorded for the Mixar-drawn tab `idname` in
 * `region`, exactly as #UI_mixar_panel_category_find_at tests it. False when
 * the region never drew the strip. Used by the QA harness inspector
 * (interface_qa_inspect.cc) so `panel_tab` targets read the strip's own
 * geometry instead of re-deriving it.
 */
bool UI_mixar_panel_category_tab_rect_get(const ARegion *region,
                                          const char *idname,
                                          rcti *r_rect);

}  // namespace blender::ui
