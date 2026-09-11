/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Thin-stroke glyphs for the Mixar account card.
 *
 * Blender's stock `ICON_*` set is drawn for toolbars and outliners: the
 * glyphs are dense, high-contrast and sized for a 16px slot. Dropped
 * into the card they out-shout their own labels and read as a different
 * design language from everything around them. These are drawn from the
 * same rounded-box and anti-aliased line primitives the card already
 * uses, so they scale with `UI_SCALE_FAC` and take the card's muted
 * foreground colour like any other card element.
 *
 * Deliberately tiny: this is a card-local glyph set, not a general icon
 * system. Anything needing real iconography should use `ICON_*`.
 */

#pragma once

#include "BLI_sys_types.h"
#include "UI_mixar_types.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

/* Card glyph identity is stored in the button's runtime style descriptor. */


/**
 * Draw \a icon centred on (\a cx, \a cy) inside a \a size x \a size box.
 *
 * Expects alpha blending to already be enabled and leaves it enabled;
 * the caller is mid-composition and re-enabling per glyph would thrash
 * GPU state for no benefit.
 */
void UI_mixar_card_icon_draw(
    MixarCardIcon icon, float cx, float cy, float size, const uchar col[4]);
}  // namespace blender::ui
