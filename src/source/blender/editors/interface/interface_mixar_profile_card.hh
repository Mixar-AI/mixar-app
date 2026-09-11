/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar account card — the contents of the top-bar profile dropdown.
 *
 * The dropdown is a normal Python popover (`MIXAR_PT_profile`, in
 * `space_mixie_chat/ui/topbar.py`) whose `draw()` calls the RNA item
 * `layout.mixar_profile_card()`. Python therefore still owns
 * registration, poll and every operator the card invokes; this layer
 * owns only pixels.
 *
 * Elements are built through the ordinary #Layout API so Blender
 * computes sizes and the popover auto-fits, then tagged with
 * dedicated button style metadata so widget dispatch routes them to
 * #UI_mixar_profile_card_draw_element instead of the stock widget. That
 * keeps layout correctness (which absolute placement inside a popover
 * would lose) while still giving full control of the drawing.
 *
 * Account figures are read from WindowManager RNA written by
 * `modules/common/usage` — see that module for the refresh contract.
 */

#pragma once

#include <cstdint>

#include "BLI_sys_types.h"
#include "UI_mixar_types.hh"
namespace blender {
struct bContext;
struct rcti;
struct uiWidgetColors;
}  // namespace blender

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

struct Button;
struct Layout;
enum class ButtonType : int8_t;

/**
 * What a card element draws as. Stored on the button by the builder and
 * read back by the draw function; see #UI_mixar_card_element_get.
 */


/**
 * Build the account card into \a layout.
 *
 * Safe to call when logged out or before the first billing fetch — the
 * card degrades to the parts it can populate rather than drawing
 * placeholder numbers.
 */
void UI_layout_mixar_profile_card(Layout *layout, bContext *C);

/** Element kind a button was tagged with, or None if it is not a card element. */
MixarCardElement UI_mixar_card_element_get(const Button *but);

/**
 * Tag the most recently created button in \a layout's block as card
 * element \a element (any kind; \a payload is the #MixarCardIcon for
 * button kinds, the fill fraction for the quota bar, 0 otherwise).
 *
 * Exposed so card-styled surfaces built from Python — the AI Provider
 * Settings dialog — can reuse the profile card's element painters
 * instead of re-hardcoding the design. See `rna_ui_api.cc`
 * (`mixar_card_label`).
 */
void UI_layout_mixar_card_tag_last(Layout *layout, MixarCardElement element, float payload);

/**
 * Style the most recently created operator/push button (#ButtonType::But)
 * in \a layout's block as one of the card's action-button kinds, and
 * set or clear #BUT_ACTIVE_DEFAULT on it.
 *
 * The active-default flag is what lets a dialog own its confirm row:
 * #wm_block_dialog_create only appends the automatic OK/Cancel pair
 * when the block has no active-default button. Non-button \a element
 * kinds are ignored (the tag would draw a label as chrome-less text
 * inside a clickable rect).
 */
void UI_layout_mixar_card_style_last_button(Layout *layout,
                                            MixarCardElement element,
                                            bool active_default);

/** Whether \a element is one of the clickable action kinds. */
bool UI_mixar_card_element_is_button(MixarCardElement element);

/** How a Cinema Mode popup row paints (the CinemaRow payload). */


/**
 * Tag \a but (created straight on a Block, not through a Layout) as a
 * Cinema Mode popup row of \a kind.
 *
 * Value-carrying controls retain their type-derived recipe. All presentation
 * lives in MixarButtonStyle; numeric ranges and enum values are untouched.
 */
void UI_mixar_cinema_row_tag(Button *but, MixarCinemaRowKind kind);

/**
 * Mark the operator button \a but so that a double-click or Ctrl+click on
 * it starts editing the no-emboss Text button under the cursor instead
 * (the My Cameras rename): the row keeps its single click, the rename
 * field gets the label-edit gestures a UI-list row would give it.
 * Sets #UI_BUT_DRAW_MIXAR_DBLCLICK_EDITS_LABEL; handled in `do_but_BUT`.
 */
void UI_mixar_button_double_click_edits_label(Button *but);

/**
 * \a but's type, for callers outside the interface module (the Director
 * popups pick a row kind by type without pulling in `interface_intern.hh`).
 */
ButtonType UI_mixar_button_type(const Button *but);

/**
 * Whether \a but's `hardmin`/`hardmax` hold its value range or string
 * length (Num / NumSlider / Scroll / Text / Toggle / IconToggle / Menu),
 * for compatibility callers. Styling never writes value fields on ANY type.
 */
bool UI_mixar_cinema_row_carries_value(const Button *but);

/**
 * The kind a tagged CinemaRow paints as: derived from the button type for
 * value-carrying buttons (NumSlider -> Slider, Text -> Field, toggles ->
 * Option), otherwise the dedicated Cinema metadata.
 */
MixarCinemaRowKind UI_mixar_cinema_row_kind_get(const Button *but);

/** Paint one #MixarCardElement::CinemaRow (`interface_mixar_cinema_row.cc`). */
void UI_mixar_cinema_row_draw(Button *but, const rcti *rect, bool is_hover, bool is_active);

/**
 * Paint the topbar elements (mode slider halves, Cinema Mode pill).
 * Returns false when \a element is not one of them, so the card's own
 * dispatch can carry on.
 */
bool UI_mixar_topbar_draw_element(
    Button *but, rcti *rect, MixarCardElement element, bool is_hover, bool is_active);

/**
 * Draw one action button — background, glyph and label.
 *
 * Lives in `interface_mixar_card_button.cc`; split from the other
 * element painters because composing the icon/label group is most of
 * the card's drawing code.
 */
void UI_mixar_card_button_draw(
    Button *but, rcti *rect, MixarCardElement element, bool is_hover, bool is_active);

/**
 * Draw one tagged card element.
 *
 * Called from `interface_widgets.cc` widget dispatch. Takes the unpacked
 * hover/active flags rather than `WidgetStateInfo`, which is private to
 * that translation unit.
 */
void UI_mixar_profile_card_draw_element(
    Button *but, uiWidgetColors *wcol, rcti *rect, bool is_hover, bool is_active);
}  // namespace blender::ui
