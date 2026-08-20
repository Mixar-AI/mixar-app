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
/* Custom flag2 bits — checked in interface_widgets.cc widget dispatch.  */

/** Marks a Roundbox button as a Mixar section (styled box container). */
#define UI_BUT2_MIXAR_SECTION (1 << 2)
/** Marks a Menu button as a Mixar dropdown (styled enum selector). */
#define UI_BUT2_MIXAR_DROPDOWN (1 << 3)
/** Marks a But (operator) button as a Mixar action button (accent CTA). */
#define UI_BUT2_MIXAR_ACTION (1 << 4)
/** Marks a Checkbox button as a Mixar toggle switch (pill-shaped). */
#define UI_BUT2_MIXAR_TOGGLE (1 << 5)
/** Marks a Text button as a Mixar styled input (visible border + focus glow). */
#define UI_BUT2_MIXAR_INPUT (1 << 6)
/**
 * Marks any button as an element of the Mixar account card; the element
 * kind lives in `Button::hardmin` (see #MixarCardElement).
 *
 * NOTE: `Button::flag2` is a signed `char`, and this is bit 7 — its sign
 * bit, and the last one free (upstream owns 0-1, Mixar 2-6). Always set
 * and test it through #UI_BUT2_MIXAR_CARD_SET / #UI_BUT2_MIXAR_CARD_TEST
 * so the value round-trips through `uchar` instead of relying on
 * implementation-defined narrowing. If a further bit is ever needed,
 * widen the field rather than adding another sign-bit special case.
 */
#define UI_BUT2_MIXAR_CARD (1 << 7)

#define UI_BUT2_MIXAR_CARD_SET(but) \
  ((but)->flag2 = char(uchar((but)->flag2) | uchar(UI_BUT2_MIXAR_CARD)))
#define UI_BUT2_MIXAR_CARD_TEST(but) ((uchar((but)->flag2) & uchar(UI_BUT2_MIXAR_CARD)) != 0)

/* -------------------------------------------------------------------- */
/* Layout helpers                                                        */

/**
 * Create a styled section box layout.
 * \return Sub-layout to place items in, identical API to layout.box().
 */
Layout *UI_layout_mixar_section(Layout *layout);

/**
 * Mark the most recently created Menu/Block/Popover button in the layout's
 * block with #UI_BUT2_MIXAR_DROPDOWN so it renders with custom styling.
 *
 * Call this immediately after layout->prop() for an enum property.
 */
void UI_layout_mixar_mark_last_dropdown(Layout *layout);

/**
 * Mark the most recently created But (operator) button with
 * #UI_BUT2_MIXAR_ACTION so it renders as an accent action button.
 */
void UI_layout_mixar_mark_last_action(Layout *layout);

/**
 * Mark the most recently created Checkbox button with
 * #UI_BUT2_MIXAR_TOGGLE so it renders as a pill-shaped toggle switch.
 */
void UI_layout_mixar_mark_last_toggle(Layout *layout);

/**
 * Mark the most recently created Text button with
 * #UI_BUT2_MIXAR_INPUT so it renders with visible border and focus glow.
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

}  // namespace blender::ui
