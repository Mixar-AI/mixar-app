/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Design tokens for the chat UI — the single source of truth for surface,
 * ink, line, radius and state colors.
 *
 * WHY A TOKEN HEADER RATHER THAN THEME DEFAULTS:
 * user preferences are persisted, so a new DNA default never reaches an
 * existing user (see the comment on `chat_ui_get_history_row_hover_color`,
 * which documents a field loading as zero from prefs saved before it
 * existed). The chat surface therefore forces its palette in C++ after the
 * theme read. These tokens are that forced palette, named once instead of
 * being respelled as float literals in a dozen draw files.
 *
 * The scale is deliberately DARK-ONLY. The chat surface commits to one look
 * across every Blender theme so the product reads consistently; there is no
 * light variant to switch to, and adding one would mean auditing every
 * hand-tuned alpha in the draw files.
 *
 * TIERS — the reason there are three inks and two lines:
 * a flat surface with no cards can only express hierarchy through contrast,
 * so each tier has one job and must not be substituted for its neighbour.
 *
 *   ink    — message prose and anything the user reads for content.
 *   ink_2  — supporting meta that is still legible at a glance (tool names,
 *            timings, sender labels).
 *   ink_3  — chrome that should recede until looked for (placeholders,
 *            counts, collapsed-block chevrons).
 *   line   — hairline separators and resting container edges.
 *   line_2 — the same edge raised for focus/hover, so a focused field is
 *            distinguishable without a color shift.
 */

#pragma once

/* -------------------------------------------------------------------- */
/** \name Raw Token Values
 *
 * Linear 0..1 RGB. Keep the source hex in the comment: these are matched
 * against a design reference, and hex is how that reference is specified.
 * \{ */

/* Surfaces, back to front. */
#define CHAT_TOK_PAGE      0.090f, 0.094f, 0.102f  /* #17181a — editor ground */
#define CHAT_TOK_CANVAS    0.110f, 0.114f, 0.122f  /* #1c1d1f — scroll area */
#define CHAT_TOK_SURFACE   0.137f, 0.141f, 0.153f  /* #232427 — raised panel */
#define CHAT_TOK_INSET     0.122f, 0.126f, 0.133f  /* #1f2022 — recessed block */
#define CHAT_TOK_HOVER     0.165f, 0.169f, 0.180f  /* #2a2b2e — row hover */
#define CHAT_TOK_HOVER_2   0.192f, 0.196f, 0.212f  /* #313236 — pressed */
#define CHAT_TOK_FIELD     0.169f, 0.173f, 0.184f  /* #2b2c2f — input / user pill */

/* Ink tiers. */
#define CHAT_TOK_INK       0.949f, 0.953f, 0.957f  /* #f2f3f4 */
#define CHAT_TOK_INK_2     0.647f, 0.659f, 0.678f  /* #a5a8ad */
#define CHAT_TOK_INK_3     0.424f, 0.435f, 0.459f  /* #6c6f75 */

/* Edges. */
#define CHAT_TOK_LINE      0.180f, 0.188f, 0.200f  /* #2e3033 */
#define CHAT_TOK_LINE_2    0.227f, 0.235f, 0.251f  /* #3a3c40 */

/* State colors. Green stays Mixar's live/brand hue; the rest complete the
 * status set so failures and warnings are not one-off literals. */
#define CHAT_TOK_ACCENT    0.239f, 0.604f, 1.000f  /* #3d9aff — interactive */
#define CHAT_TOK_GREEN     0.239f, 0.733f, 0.447f  /* #3dbb72 — live / success */
#define CHAT_TOK_ORANGE    0.965f, 0.561f, 0.235f  /* #f68f3c — warning */
#define CHAT_TOK_RED       0.933f, 0.361f, 0.380f  /* #ee5c61 — failure */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Radii (unscaled pixels — multiply by UI_SCALE_FAC at draw time)
 * \{ */

#define CHAT_RADIUS_CHIP 6.0f     /* Inline chips, small state pills */
#define CHAT_RADIUS_CONTROL 8.0f  /* Buttons, input fields, rows */
#define CHAT_RADIUS_CARD 10.0f    /* Block containers, overlay cards */
#define CHAT_RADIUS_PILL 12.0f    /* The user message pill */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hairline Width
 *
 * The reference expresses containers as a 1px edge over a near-flat fill
 * rather than a heavy filled card, so a hairline is a structural constant
 * here, not a per-call magic number.
 * \{ */

#define CHAT_HAIRLINE_WIDTH 1.0f

/** \} */

/* -------------------------------------------------------------------- */
/** \name Token Accessors
 *
 * Inline so any draw file can pull a token without a link dependency on the
 * theme translation unit, and so the alpha is always explicit at the call
 * site (most of these are composited over other fills).
 * \{ */

inline void chat_tok_set(float out[4], float r, float g, float b, float a)
{
  out[0] = r;
  out[1] = g;
  out[2] = b;
  out[3] = a;
}

#define CHAT_TOK_FN(name, token) \
  inline void name(float out[4], float alpha = 1.0f) \
  { \
    chat_tok_set(out, token, alpha); \
  }

CHAT_TOK_FN(chat_tok_page, CHAT_TOK_PAGE)
CHAT_TOK_FN(chat_tok_canvas, CHAT_TOK_CANVAS)
CHAT_TOK_FN(chat_tok_surface, CHAT_TOK_SURFACE)
CHAT_TOK_FN(chat_tok_inset, CHAT_TOK_INSET)
CHAT_TOK_FN(chat_tok_hover, CHAT_TOK_HOVER)
CHAT_TOK_FN(chat_tok_hover_2, CHAT_TOK_HOVER_2)
CHAT_TOK_FN(chat_tok_field, CHAT_TOK_FIELD)
CHAT_TOK_FN(chat_tok_ink, CHAT_TOK_INK)
CHAT_TOK_FN(chat_tok_ink_2, CHAT_TOK_INK_2)
CHAT_TOK_FN(chat_tok_ink_3, CHAT_TOK_INK_3)
CHAT_TOK_FN(chat_tok_line, CHAT_TOK_LINE)
CHAT_TOK_FN(chat_tok_line_2, CHAT_TOK_LINE_2)
CHAT_TOK_FN(chat_tok_accent, CHAT_TOK_ACCENT)
CHAT_TOK_FN(chat_tok_green, CHAT_TOK_GREEN)
CHAT_TOK_FN(chat_tok_orange, CHAT_TOK_ORANGE)
CHAT_TOK_FN(chat_tok_red, CHAT_TOK_RED)

#undef CHAT_TOK_FN

/** \} */
