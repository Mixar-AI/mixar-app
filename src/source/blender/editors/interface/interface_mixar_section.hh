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

struct uiLayout;

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

/* -------------------------------------------------------------------- */
/* Layout helpers                                                        */

/**
 * Create a styled section box layout.
 * \return Sub-layout to place items in, identical API to layout.box().
 */
uiLayout *UI_layout_mixar_section(uiLayout *layout);

/**
 * Mark the most recently created Menu/Block/Popover button in the layout's
 * block with #UI_BUT2_MIXAR_DROPDOWN so it renders with custom styling.
 *
 * Call this immediately after layout->prop() for an enum property.
 */
void UI_layout_mixar_mark_last_dropdown(uiLayout *layout);

/**
 * Mark the most recently created But (operator) button with
 * #UI_BUT2_MIXAR_ACTION so it renders as an accent action button.
 */
void UI_layout_mixar_mark_last_action(uiLayout *layout);

/**
 * Mark the most recently created Checkbox button with
 * #UI_BUT2_MIXAR_TOGGLE so it renders as a pill-shaped toggle switch.
 */
void UI_layout_mixar_mark_last_toggle(uiLayout *layout);

/**
 * Mark the most recently created Text button with
 * #UI_BUT2_MIXAR_INPUT so it renders with visible border and focus glow.
 */
void UI_layout_mixar_mark_last_input(uiLayout *layout);

/* -------------------------------------------------------------------- */
/* Custom panel category tab drawing for MIXIE space                     */

struct ARegion;

/**
 * Draw a custom styled panel category tab bar for the MIXIE space.
 * Replaces the default Blender vertical tab strip with a modern design:
 * dark background, accent-blue active pill with glow, subtle inactive tabs.
 */
void UI_panel_category_draw_all_mixar(ARegion *region, const char *category_id_active);
