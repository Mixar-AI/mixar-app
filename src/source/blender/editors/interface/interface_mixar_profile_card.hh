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
 * #UI_BUT2_MIXAR_CARD so widget dispatch routes them to
 * #UI_mixar_profile_card_draw_element instead of the stock widget. That
 * keeps layout correctness (which absolute placement inside a popover
 * would lose) while still giving full control of the drawing.
 *
 * Account figures are read from WindowManager RNA written by
 * `modules/common/usage` — see that module for the refresh contract.
 */

#pragma once

#include "BLI_sys_types.h"
namespace blender {
struct bContext;
struct rcti;
struct uiWidgetColors;
}  // namespace blender

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

struct Button;
struct Layout;

/**
 * What a card element draws as. Stored on the button by the builder and
 * read back by the draw function; see #UI_mixar_card_element_get.
 */
enum class MixarCardElement : int {
  None = 0,
  /** "Welcome, Rahul !" — oversized, full-contrast. */
  Heading,
  /** "(rahul@mixar.app)" — small, dim. */
  Muted,
  /** "Your Usage" — small, one tier brighter than #Muted so the section
   * reads as a heading rather than as more metadata. */
  SectionLabel,
  /** "4300 of 5000 left" — small, muted, right-aligned. */
  MetaRight,
  /** "PRO Plan" — small bordered chip. */
  Pill,
  /** Full-width quota bar with the percentage inside the fill. */
  UsageBar,
  /** "Buy Credits" — accent-outlined compact button. */
  AccentButton,
  /** Dashboard / AI Provider Settings / Docs — outlined icon buttons. */
  CardButton,
  /** "Report a Bug" — danger-tinted variant of CardButton. */
  DangerButton,
  /** "Logout" — borderless full-width strip. */
  GhostButton,
  /** Horizontal rule between card sections. */
  Divider,
  /** Danger-tinted body text — inline error copy in card-styled dialogs. */
  DangerText,
  /** Topbar mode slider, left half (Zen). Paints the WHOLE two-up track and
   * the animated thumb, then its own label — the right half paints only its
   * label, so the thumb can never cover the left one (buttons draw in
   * creation order). Payload carries the target: 0 = left active, 1 = right. */
  ModeSliderLeft,
  /** Topbar mode slider, right half (Engine): label only. */
  ModeSliderRight,
  /** Topbar "Cinema Mode" pill: dark fill, hairline border, gradient label.
   * Payload is 1.0 while the mode is active. */
  CinemaPill,
  /** Zen viewport shading pill ("Solid" / "Rendered"): the design's dark
   * chip at full opacity when live, 49% when not. Payload is 1.0 for the
   * live one. */
  ViewportPill,
  /** Topbar account chip: dark slab, label left, full-height avatar disc at
   * the right end carrying the stock person glyph. */
  ProfilePill,
  /** Sentinel — keep last. #UI_mixar_card_element_get range-checks against
   * it, so a kind appended after it would silently read back as None. */
  Count,
};

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

/**
 * Paint the topbar elements (mode slider halves, Cinema Mode pill).
 * Returns false when \a element is not one of them, so the card's own
 * dispatch can carry on.
 */
bool UI_mixar_topbar_draw_element(
    uiBut *but, rcti *rect, MixarCardElement element, bool is_hover, bool is_active);

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
