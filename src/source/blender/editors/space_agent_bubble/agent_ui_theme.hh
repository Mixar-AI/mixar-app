/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Design tokens for the Agent island — the floating command surface that
 * replaces the old Agent Bubble chat UI.
 *
 * EVERY number below is measured from the source artboard
 * (`entire chat ui full.svg`, agent frame at board origin 853,1138 — the
 * frame that carries the model chip; the standalone `just agent.svg`
 * export is the same geometry minus that chip and with slightly different
 * card-gradient stops, and is NOT the reference).
 *
 * \section units Artboard units
 *
 * Coordinates are quoted in ARTBOARD units, with the artboard's own origin
 * moved to the island's top-left — artboard (267, 340) is our (0, 0). The
 * island is 1310 x 569 artboard units.
 *
 * The artboard is a 1.5x export. That divisor is not a guess: the artboard
 * draws its icons at 24 units square, and 24 / 1.5 = 16 — Blender's icon
 * size at scale 1. Every other token lands on a native value under the same
 * divisor (chip text 12, card radius 21.3, tab pill 34.7 tall), which no
 * other divisor does: at /2 the icons come out 12 and the chip text 9,
 * at /1 the title text is a 25 px outlier. Change AGENT_DESIGN_DIVISOR only
 * with a fresh measurement to justify it.
 *
 * Use AGENT_DU() to turn an artboard unit into a scaled device pixel; it
 * folds in UI_SCALE_FAC so the island tracks the user's interface scale.
 */

#pragma once

#include "BLI_utildefines.h"

#include "UI_interface.hh"

/* -------------------------------------------------------------------- */
/** \name Artboard -> device pixels
 * \{ */

/** Artboard export factor. See the file docstring before touching this. */
#define AGENT_DESIGN_DIVISOR 1.5f

/** One artboard unit in scaled device pixels. */
#define AGENT_DU(v) (float(v) / AGENT_DESIGN_DIVISOR * UI_SCALE_FAC)

/** \} */

/* -------------------------------------------------------------------- */
/** \name Island Envelope
 *
 * The island is the whole floating surface: status pill, tab strip and
 * card. The bubble's chrome-less window is sized to exactly this, so
 * island-local (0,0) is the window's top-left.
 * \{ */

#define AGENT_ISLAND_W 1310

/* The island STARTS at the tab strip. The artboard draws a status pill 48
 * units above it, but that band would composite as an opaque black bar over
 * the viewport — the bubble window has no per-pixel alpha. The pill is its own
 * always-on-top window instead (parented to the bubble and anchored above it),
 * so the only dark bar on screen is the tab strip's own. */
#define AGENT_ISLAND_TOP 48
#define AGENT_ISLAND_H (569 - AGENT_ISLAND_TOP)

/** \} */

/* -------------------------------------------------------------------- */
/** \name Status Pill  ("• Processing…")
 *
 * Artboard rect 277,340 135x38 rx19 -> island-local 10,0.
 * \{ */

#define AGENT_PILL_X 10
#define AGENT_PILL_Y 0
#define AGENT_PILL_W 135
#define AGENT_PILL_H 38
#define AGENT_PILL_RADIUS 19

/** Status dot: artboard circle (293, 359) r5 -> island-local (26, 19). */
#define AGENT_PILL_DOT_CX 26
#define AGENT_PILL_DOT_CY 19
#define AGENT_PILL_DOT_R 5

/** Label ink starts at artboard x=306 -> island-local 39, centred in the pill. */
#define AGENT_PILL_LABEL_X 39
#define AGENT_PILL_FONT 15

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tab Strip
 *
 * Container: artboard 269,388 1306x65 rx32 -> island-local 2,48.
 * All tab pills share y=394 (local 54) and h=52, rx=26.
 * \{ */

#define AGENT_STRIP_X 2
#define AGENT_STRIP_Y 48
#define AGENT_STRIP_W 1306
#define AGENT_STRIP_H 65
#define AGENT_STRIP_RADIUS 32

#define AGENT_TAB_Y 54
#define AGENT_TAB_H 52
#define AGENT_TAB_RADIUS 26

/** The active pill is drawn 1 unit taller and 1 higher than the outlined ones
 *  (artboard 277,394 122x53 rx26.5) — keep the asymmetry, it is what stops the
 *  filled pill reading as inset against its neighbours. */
#define AGENT_TAB_ACTIVE_DY (-1)
#define AGENT_TAB_ACTIVE_DH 1

/** Icon box, 24 units square, top at artboard y=409 -> local 69. */
#define AGENT_TAB_ICON 24
#define AGENT_TAB_ICON_Y 69

/** Left-edge x of each tab pill, island-local (artboard x minus 267). */
#define AGENT_TAB_X_AGENT 10
#define AGENT_TAB_W_AGENT 122
#define AGENT_TAB_X_3D 137
#define AGENT_TAB_W_3D 88
#define AGENT_TAB_X_MEDIA 231
#define AGENT_TAB_W_MEDIA 123
#define AGENT_TAB_X_SPLAT 360
#define AGENT_TAB_W_SPLAT 262

/** Right cluster. */
#define AGENT_TAB_X_GENERATIONS 965
#define AGENT_TAB_W_GENERATIONS 218
#define AGENT_TAB_X_QUEUE 1189
#define AGENT_TAB_W_QUEUE 111

/** Queue count chip inside the Queue pill: artboard 1461,401 37x38 rx18.5. */
#define AGENT_QUEUE_COUNT_X 1194
#define AGENT_QUEUE_COUNT_Y 61
#define AGENT_QUEUE_COUNT_W 37
#define AGENT_QUEUE_COUNT_H 38
#define AGENT_QUEUE_COUNT_RADIUS 18

/** "NEW" badge on the Gaussian Splat tab: artboard 821,406 57x28 rx14. */
#define AGENT_NEW_BADGE_X 554
#define AGENT_NEW_BADGE_Y 66
#define AGENT_NEW_BADGE_W 57
#define AGENT_NEW_BADGE_H 28
#define AGENT_NEW_BADGE_RADIUS 14
#define AGENT_NEW_BADGE_FONT 13

/** Gap between a tab's icon and its label, and the pill's inner side padding. */
#define AGENT_TAB_ICON_GAP 8
#define AGENT_TAB_PAD_X 13
#define AGENT_TAB_FONT 18

/** \} */

/* -------------------------------------------------------------------- */
/** \name Card
 *
 * Border 267,461 1310x448 rx32 -> local 0,121. The 2-unit inset fill is the
 * card proper; the border is therefore a 2-unit stroke, not a glow. There is
 * no blur filter on it in the artboard — the halo in a JPEG preview is
 * compression, do not reproduce it.
 * \{ */

#define AGENT_CARD_X 0
#define AGENT_CARD_Y 121
#define AGENT_CARD_W 1310
#define AGENT_CARD_H 448
#define AGENT_CARD_RADIUS 32
#define AGENT_CARD_BORDER 2

/** Header band: the card's gradient showing above the inner panel. */
#define AGENT_CARD_HEADER_H 74

/** Round buttons in the header: artboard circles r19.5 at cy=499.5,
 *  cx 303.5 / 349.5 -> island-local cy 38.5 within the card, cx 36.5 / 82.5. */
#define AGENT_HDR_BTN_R 19
#define AGENT_HDR_BTN_CY 38
#define AGENT_HDR_BTN1_CX 36
#define AGENT_HDR_BTN2_CX 82
#define AGENT_HDR_GLYPH_R 13

#define AGENT_HDR_TITLE_FONT 25
#define AGENT_HDR_FAQ_FONT 17
/** "FAQs" ink ends at artboard x=1554 -> 23 units of right inset. */
#define AGENT_HDR_FAQ_INSET 23

/** \} */

/* -------------------------------------------------------------------- */
/** \name Inner Panel
 *
 * artboard 273,537 1298x366 rx28 -> island-local 6,197.
 * \{ */

#define AGENT_PANEL_X 6
#define AGENT_PANEL_Y 197
#define AGENT_PANEL_W 1298
#define AGENT_PANEL_H 366
#define AGENT_PANEL_RADIUS 28

/* The card hosts the conversation, so the panel splits: the transcript takes
 * the upper part and the input line sits just above the chip row. The artboard
 * has no transcript — it draws the whole panel as the input — so this split is
 * the one deliberate departure from it, and the reason the ghost text sits at
 * the panel's bottom rather than its top. */
/* The card STRETCHES with the window: its top stays on the artboard's grid and
 * its foot follows the window's bottom edge, with the transcript absorbing all
 * the slack. Anchoring the card to a fixed 569-unit height instead leaves the
 * composer stranded at the window's bottom while the card's foot floats far
 * above it, which is exactly what a taller window produced.
 *
 * These are the fixed distances measured UP from the card's bottom edge. */
#define AGENT_CARD_PAD_BOTTOM 23 /* card foot -> chip row bottom */
#define AGENT_INPUT_H 56
#define AGENT_INPUT_GAP 10       /* input line -> chip row */
#define AGENT_TRANSCRIPT_GAP 10  /* transcript -> input line */

/* Where the island is cut into regions, in artboard units. The top slab holds
 * the pill, tab strip and card header; the middle is the transcript (a real
 * WINDOW region, so it scrolls with View2D); the bottom holds the input line
 * and the chip row. */
#define AGENT_SLAB_TOP_H 197
#define AGENT_SLAB_BOTTOM_Y 426

/** Prompt text: ink box starts at artboard (312, 577) -> local (45, 237). */
#define AGENT_PROMPT_X 45
#define AGENT_PROMPT_Y 237
#define AGENT_PROMPT_FONT 24

/** \} */

/* -------------------------------------------------------------------- */
/** \name Chip Row
 *
 * All chips share y=842 (island-local 502), h=44, rx=14.
 * \{ */

#define AGENT_CHIP_Y 502
#define AGENT_CHIP_H 44
#define AGENT_CHIP_RADIUS 14
#define AGENT_CHIP_FONT 18
/* Measured off the artboard's model chip: icon ink 501..518 inside a chip
 * starting at 489, label ink from 526. */
#define AGENT_CHIP_PAD_X 12
#define AGENT_CHIP_ICON 18
#define AGENT_CHIP_ICON_GAP 8

/** Segmented Agent/Generate mode control: track 291,842 273x44, and the
 *  active thumb inset 2 units on every side (293,844 125x40). */
#define AGENT_SEG_X 24
#define AGENT_SEG_W 273
#define AGENT_SEG_THUMB_INSET 2
#define AGENT_SEG_THUMB_W 125

/** Upload Reference chip: artboard 599,842 150x44 — widened to 200 so the
 *  label reads in full. The artboard truncates it to "Upload Refe…", but that
 *  clipped mid-word in the build and the model chip's slot beside it is free
 *  now, so the chip takes the room rather than the ellipsis. */
#define AGENT_CHIP_UPLOAD_X 332
#define AGENT_CHIP_UPLOAD_W 200

/* The artboard's model chip (756,842 188x44, "* Claude Opus 5 v") is
 * deliberately NOT reproduced — the model picker was cut from the design.
 * Its slot is left empty rather than reflowed: the chips that remain keep
 * the artboard's x positions. */

/** Generate button: artboard 1441,842 114x44. */
#define AGENT_BTN_GENERATE_X 1174
#define AGENT_BTN_GENERATE_W 114

/** \} */

/* -------------------------------------------------------------------- */
/** \name Palette
 *
 * Straight from the artboard's fills. Alpha is ALWAYS stated — a
 * three-value initialiser zero-fills it and the shape draws invisible.
 * \{ */

/* Surfaces */
#define AGENT_COL_SURFACE {0.071f, 0.071f, 0.071f, 1.0f}      /* #121212 strip, panel, pill */
#define AGENT_COL_CHIP {0.114f, 0.114f, 0.114f, 1.0f}         /* #1D1D1D chip track */
#define AGENT_COL_CHIP_ACTIVE {0.196f, 0.196f, 0.196f, 1.0f}  /* #323232 segment thumb */
#define AGENT_COL_QUEUE {0.259f, 0.259f, 0.259f, 1.0f}        /* #424242 queue pill */
#define AGENT_COL_QUEUE_COUNT {0.424f, 0.424f, 0.424f, 1.0f}  /* #6C6C6C count chip */

/* Greens */
#define AGENT_COL_BORDER {0.000f, 1.000f, 0.549f, 1.0f}       /* #00FF8C card border */
#define AGENT_COL_TAB_ACTIVE {0.094f, 0.243f, 0.145f, 1.0f}   /* #183E25 active tab */
#define AGENT_COL_ACCENT {0.169f, 0.486f, 0.294f, 1.0f}       /* #2B7C4B dot, badge, hdr btn */
#define AGENT_COL_GENERATE {0.102f, 0.251f, 0.149f, 1.0f}     /* #1A4026 generate button */

/* Card gradient — top-right #325B33 to #002317, along the artboard vector
 * (1554,463) -> (1281.66,1068.71) in island-local units. The ramp runs past
 * the card's bottom edge, so only its first ~73% is ever visible; sampling
 * it over the card rect alone would make the card far too dark. */
#define AGENT_COL_CARD_TOP {0.196f, 0.357f, 0.200f, 1.0f}
#define AGENT_COL_CARD_BOTTOM {0.000f, 0.137f, 0.090f, 1.0f}
#define AGENT_CARD_GRAD_X0 1287
#define AGENT_CARD_GRAD_Y0 2
#define AGENT_CARD_GRAD_X1 1014
#define AGENT_CARD_GRAD_Y1 607

/* Strokes and text.
 *
 * Two text weights, and the artboard is deliberate about which goes where:
 * the tab strip's ACTIVE label, the Queue pill, the card title and FAQs are
 * pure white, while every chip label is #E2E2E2. Flattening the two makes the
 * strip lose its focus and the chip row gain a shout it should not have. */
#define AGENT_COL_TEXT_STRONG {1.0f, 1.0f, 1.0f, 1.0f}
#define AGENT_COL_OUTLINE {0.255f, 0.255f, 0.255f, 1.0f}      /* #414141 tab outline */
#define AGENT_COL_TEXT {0.886f, 0.886f, 0.886f, 1.0f}         /* #E2E2E2 primary label */
#define AGENT_COL_TEXT_DIM {0.459f, 0.459f, 0.459f, 1.0f}     /* #757575 inactive label */
#define AGENT_COL_GLYPH {0.894f, 0.894f, 0.894f, 1.0f}        /* #E4E4E4 header glyph disc */

/** \} */
