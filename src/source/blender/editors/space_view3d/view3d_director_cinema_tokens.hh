/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode's design tokens: geometry in DESIGN px at 1x, and the palette.
 *
 * Every painter multiplies a geometry token by #cinema_unit(), which
 * `view3d_director_cinema_layout.cc` resolves once per draw. Split out of
 * `view3d_director_cinema.hh` because the two halves change for different
 * reasons — these move when the DESIGN does, the API when the code does —
 * and together they had outgrown the module size limit.
 */

#pragma once

/* -------------------------------------------------------------------- */
/** \name Design tokens (design px @1x)
 * \{ */

/** Design y of the viewport's top edge in the export's window mock. */
#define CINEMA_VIEWPORT_TOP 85.0f

/* Panels. */
#define CINEMA_PANEL_W 245.0f
/** A card's edge to its content, on EVERY side. The insets used to be picked
 * per card (13 for the dropdown rows, 16 for the speed meter, 11 for a camera
 * row against a 13 caption), so nothing lined up with anything and no row was
 * centred in its own card. One token, and #CINEMA_ROW_W derived from it. */
#define CINEMA_CARD_PAD 14.0f
#define CINEMA_PANEL_RADIUS 19.0f
#define CINEMA_MARGIN 70.0f     /* Window edge -> panel edge, at design width. */
#define CINEMA_MARGIN_MIN 20.0f /* Floor when the viewport is narrower. */
#define CINEMA_GATE_MIN_W 180.0f /* Clear width kept between the two columns. */
/** Smallest fit the designed surface may shrink to before the compact rail
 * takes over. The design is fitted to the region (see #cinema_fit_scale): a
 * laptop viewport that cannot hold it at 1x shows it at, say, 0.8x — the mock
 * itself is a 0.8x render — rather than a different UI. */
#define CINEMA_SCALE_MIN 0.6f

/* Rows inside a panel. */
/* ONE row class for every rounded control — dropdown rows, list rows,
 * segment tracks, the strip's chips and dropdown, the dock's chips and fields
 * — so the design reads as one system: same height, same radius, same
 * gradient. Cards keep CINEMA_PANEL_RADIUS. */
#define CINEMA_ROW_W (CINEMA_PANEL_W - CINEMA_CARD_PAD * 2.0f)
#define CINEMA_ROW_H 32.0f
#define CINEMA_ROW_RADIUS 14.0f
#define CINEMA_ROW_PITCH 68.0f  /* Labelled dropdown to the next one. */
#define CINEMA_LIST_PITCH 32.0f /* Template / camera list rows. */
#define CINEMA_LIST_GAP 3.0f    /* Between them: at pitch they touched. */
/** Rows a list can show before it has to window around the live one. */
#define CINEMA_LIST_MAX_ROWS 4

/* Top strip. */
#define CINEMA_KEYCAP_W 17.0f
#define CINEMA_KEYCAP_H 19.0f
#define CINEMA_KEYCAP_RADIUS 4.0f
#define CINEMA_KEYCAP_FONT 11.0f
/** Side padding when a cap carries a word rather than one glyph. */
#define CINEMA_KEYCAP_PAD 5.0f
/** Hint groups start at the camera gate's left edge and pack at this gap. */
#define CINEMA_HINT_GAP 26.0f
#define CINEMA_PHONE_H 32.0f
/* The strip's controls flow right-to-left from the stage's right edge: phone,
 * tracking eyedropper, grid chip. The phone collapses to an icon chip
 * (CINEMA_PHONE_H square) when the hints would otherwise run into the
 * controls. (Interpolation used to sit here; it moved to the timeline dock,
 * beside the keyframes it describes.) */
#define CINEMA_STRIP_GAP 10.0f
/* The Mixar banner chip above the left column: a CINEMA_PANEL_W pill on the
 * strip band (row class height and radius), inert. */
#define CINEMA_BRAND_PAD 10.0f         /* Pill edge -> logo chip. */
#define CINEMA_BRAND_LOGO 22.0f        /* Round logo chip diameter. */
#define CINEMA_BRAND_MARK 14.0f        /* Mixar mark edge inside the logo chip. */
#define CINEMA_BRAND_GAP 8.0f          /* Logo -> wordmark -> mode name. */
#define CINEMA_BRAND_VERSION_PAD 12.0f /* Pill's right edge -> "V1". */

/* Right panel. Cards stack from CINEMA_COLUMN_TOP at CINEMA_CARD_GAP so the
 * column's foot lands on the same design y as the left column's. */
#define CINEMA_CARD_GAP 11.0f
#define CINEMA_CAMERAS_H 200.0f
#define CINEMA_PREVIEW_H 178.0f
#define CINEMA_SEGMENT_H 32.0f
#define CINEMA_EXPORT_H 48.0f

/* The columns' top edge and the stage's inset from them. The stage (the
 * working area between the columns that the camera gate is fitted to) spans
 * exactly the columns' vertical extent: from here down to
 * #cinema_content_bottom(). */
#define CINEMA_COLUMN_TOP 206.0f
#define CINEMA_STAGE_INSET 18.0f
/** Gap between the camera gate's foot and the chat bar (the resting pill),
 * and between the chat bar's foot and the timeline's top border. */
#define CINEMA_CHAT_GAP 10.0f
/** Inset of the fitted camera border inside the stage. */
#define CINEMA_GATE_PAD 6.0f

/* Lowest content in either column. The height gate is DERIVED from these, so
 * moving a card down moves the gate with it instead of silently laying the
 * Speed slider and the Export button out below the region. */
#define CINEMA_SPEED_CARD_Y 670.0f
#define CINEMA_SPEED_CARD_H 70.0f
#define CINEMA_EXPORT_Y 692.0f

/* Speed bounds. These MIRROR SPEED_MIN / SPEED_MAX in `director/constants.py`,
 * the `shot.speed` RNA property's own limits and therefore the slider's
 * travel; keep the two in step. The slider rests in the middle at 0 (the
 * timing as captured); right contracts the shot, left expands it. */
#define CINEMA_SPEED_MIN -1.0f
#define CINEMA_SPEED_MAX 1.0f

/* Lens and orthographic-scale slider TRAVEL. These MIRROR
 * LENS_SLIDER_MIN_MM / LENS_SLIDER_MAX_MM and ORTHO_SCALE_SLIDER_MIN / _MAX in
 * `director/constants.py`; keep the two in step.
 *
 * They narrow the DRAG, not the property: `Camera.lens` ships a 1-5000mm soft
 * range that puts every focal length anyone uses inside the first few pixels
 * of travel, and `ortho_scale` runs to 1000. Text entry still reaches each
 * property's hard range, so nothing is taken away. */
#define LENS_SLIDER_MIN_MM 10.0f
#define LENS_SLIDER_MAX_MM 300.0f
/* An orthographic camera's scale IS its framing, and a slider's drag rate is
 * its range spread over the row's width: at 0.1-100 one pixel moved the frame
 * by half a metre. 20 covers the framing anyone reaches for and leaves about
 * a tenth of a unit per pixel; text entry still reaches the property's hard
 * range, so nothing is taken away. */
#define ORTHO_SCALE_SLIDER_MIN 0.1f
#define ORTHO_SCALE_SLIDER_MAX 20.0f
/* The aperture slider's TRAVEL. `aperture_fstop` has no upper soft bound
 * anyone would call photographic, so the drag covers the span of real lenses
 * and text entry still reaches the rest. MIRRORS FSTOP_SLIDER_MIN /
 * FSTOP_SLIDER_MAX in `director/constants.py`; keep the two in step. */
#define FSTOP_SLIDER_MIN 0.95f
#define FSTOP_SLIDER_MAX 22.0f

/* Type sizes. */
#define CINEMA_FONT_LABEL 12.0f /* "Aspect Ratio", "My Cameras", hints. */
#define CINEMA_FONT_VALUE 13.0f /* Dropdown values, list rows. */
#define CINEMA_FONT_TITLE 15.0f  /* Dock "Ruler". */
#define CINEMA_FONT_ACTION 14.0f /* Export, and any other full-width action. */

/* Palette. */
#define CINEMA_COL_CARD_TOP {0.133f, 0.137f, 0.137f, 0.96f}    /* #222323 — tracks, not card beds */
#define CINEMA_COL_CARD_BOTTOM {0.043f, 0.043f, 0.043f, 0.96f} /* #0B0B0B — tracks, not card beds */
#define CINEMA_COL_ROW_TOP {0.345f, 0.345f, 0.345f, 1.0f}      /* #585858 */
#define CINEMA_COL_ROW_BOTTOM {0.141f, 0.141f, 0.141f, 1.0f}   /* #242424 */
/* THREE greys, one rule each — they were picked per painter before, so the
 * same kind of text came out three shades depending on which file drew it.
 *   LABEL   names something that is live (a hint's label, the brand's mode).
 *   CAPTION titles a card or a row group ("My Cameras", "Aspect Ratio").
 *   DIM     is a value or row that is NOT the live one.
 * VALUE is white and belongs to the live one. */
#define CINEMA_COL_LABEL {0.502f, 0.502f, 0.502f, 1.0f}        /* #808080 */
/** Dropdown captions and card titles: darker and a little translucent. */
#define CINEMA_COL_CAPTION {0.40f, 0.40f, 0.40f, 0.85f}
#define CINEMA_COL_VALUE {1.0f, 1.0f, 1.0f, 1.0f}
#define CINEMA_COL_DIM {0.388f, 0.388f, 0.388f, 1.0f}    /* #636363 */
#define CINEMA_COL_DIMMER {0.216f, 0.216f, 0.216f, 1.0f} /* #373737 */
#define CINEMA_COL_KEYCAP {0.392f, 0.392f, 0.392f, 1.0f} /* #646464 */
#define CINEMA_COL_PHONE {0.220f, 0.220f, 0.220f, 1.0f}  /* #383838 */
#define CINEMA_COL_CHIP {0.314f, 0.314f, 0.314f, 1.0f}   /* #505050 */
#define CINEMA_COL_EXPORT {0.102f, 0.251f, 0.149f, 1.0f} /* #1A4026 */
#define CINEMA_COL_BRAND_TOP {0.043f, 0.192f, 0.102f, 1.0f}    /* #0B311A */
#define CINEMA_COL_BRAND_BOTTOM {0.059f, 0.059f, 0.059f, 1.0f} /* #0F0F0F */
/** The banner's logo chip: the Agent island's own chip ramp. */
#define CINEMA_COL_LOGO_TOP {0.125f, 0.345f, 0.212f, 1.0f}    /* #205836 */
#define CINEMA_COL_LOGO_BOTTOM {0.227f, 0.518f, 0.341f, 1.0f} /* #3A8457 */
#define CINEMA_COL_SPEED_ON {0.165f, 0.475f, 0.286f, 1.0f}  /* #2A7949 */
#define CINEMA_COL_SPEED_OFF {0.259f, 0.259f, 0.259f, 1.0f} /* #424242 */

/** \} */
