/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Private kit shared by the Cinema Mode popup-row painters
 * (`interface_mixar_cinema_row*.cc`): the mirrored design tokens and the
 * small row primitives every kind is built from. The public entry points
 * are in `interface_mixar_profile_card.hh`.
 *
 * The tokens are DEFINED in `interface_mixar_cinema_row.cc` as aliases of
 * `UI_mixar_chrome.hh` (a pin test keeps those bytes in step with
 * `view3d_director_cinema.hh`); this header only declares them so the
 * segment and value painters can share them.
 */

#pragma once

#include "BLI_rect.h"
#include "BLI_sys_types.h"

#include "UI_interface_c.hh"

#include "interface_mixar_profile_card.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui::mixar_cinema_row {

/* Design px @1x — mirrored from view3d_director_cinema.hh. */
extern const float ROW_RADIUS; /* CINEMA_ROW_RADIUS */
extern const float TEXT_PAD;
/** Floor the row padding shrinks to before a label is ellipsised. */
extern const float TEXT_PAD_MIN;
/** Narrowest a segment cell shrinks to while a neighbour reveals its label. */
extern const float SEGMENT_MIN_W;

extern const uchar ROW_TOP[4];       /* CINEMA_COL_ROW_TOP */
extern const uchar ROW_BOTTOM[4];    /* CINEMA_COL_ROW_BOTTOM */
extern const uchar HOVER[4];         /* popup hover fill; a hovered slider's track */
extern const uchar TRACK[4];         /* a slider's resting track */
extern const uchar TEXT_ON[4];       /* CINEMA_COL_VALUE */
extern const uchar TEXT_OFF[4];      /* readable on the popup back */
extern const uchar TEXT_DISABLED[4]; /* CINEMA_COL_DIM */
extern const uchar CAPTION[4];       /* CINEMA_COL_CAPTION */
extern const uchar SLIDER_ON[4];     /* CINEMA_COL_SPEED_ON */

/** The button rect as the painted row: 1 px inset so butted rows never touch. */
rctf row_rect(const rcti *rect);

/** The row class radius: #ROW_RADIUS, capped to a pill for shorter rows. */
float row_radius(const rctf &row);

/**
 * The button's FULL label. Blender clips `drawstr` for its own stock layout
 * (icon space plus padding it never draws here), which turned "Beauty" into
 * "Be" in a three-up row; the painters lay text out themselves from `str`.
 */
const char *row_label(const Button *but);

/** The row-class font for values and options (13 px against 12 px captions). */
uiFontStyle row_font();

/** The caption font. */
uiFontStyle caption_font();

/** The graded chip: the surface's "live" row. */
void draw_chip(const rctf &row, float radius, float alpha = 1.0f);

/** The flat hover / pressed fill. */
void draw_hover(const rctf &row, float radius, float alpha);

/** Pixels one side of #TEXT_PAD can give back down to #TEXT_PAD_MIN. */
float pad_slack();

/**
 * Draw \a label inside \a rect (already inset by #TEXT_PAD). A label that
 * does not fit first takes back up to \a slack_left / \a slack_right px of
 * padding (pass #pad_slack for a side that is still pure padding, 0 for a
 * side that ends at an icon or a value) and is drawn whole if that fits;
 * only then is it shortened with a middle ellipsis, so a tight cell never
 * cuts a glyph in half.
 */
void draw_label(const uiFontStyle &fs,
                const rcti *rect,
                const char *label,
                const uchar col[4],
                FontStyleAlign align,
                float slack_left,
                float slack_right);

/**
 * Lay the stock 16 px icon at the left of \a text and advance `text.xmin`
 * past it — unless icon plus label cannot fit, when the label wins and the
 * icon is dropped. Returns whether the icon was drawn.
 */
bool draw_leading_icon(
    const Button *but, const rcti *rect, rcti &text, float label_w, float alpha);

/* Kind painters. */

/** Option / Active / Action (`interface_mixar_cinema_row.cc`). */
void draw_option(Button *but, const rcti *rect, MixarCinemaRowKind kind, bool hover, bool active);

/** One cell of a hover-expanding segmented group (`_segment.cc`). */
void draw_segment(Button *but, const rcti *rect);

/** Dim caption text, optional leading icon, no chrome (`_value.cc`). */
void draw_caption(Button *but, const rcti *rect);

/** The row-class slider track with the green fill to the value (`_value.cc`). */
void draw_slider(Button *but, const rcti *rect, bool hover);

/** A Text field over surface-painted text: nothing while idle (`_value.cc`). */
void draw_field(Button *but, const rcti *rect);

}  // namespace blender::ui::mixar_cinema_row
