/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Constants for footer layout and UI elements.
 * Extracts magic numbers to named constants for maintainability.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Layout Constants
 * \{ */

/* Base UI unit height (unscaled pixels) */
#define FOOTER_UI_UNIT_BASE 20

/* Minimum number of visible text lines in the multi-line input field */
#define FOOTER_INPUT_LINE_COUNT 3

/* Maximum number of visible text lines before scrolling kicks in */
#define FOOTER_INPUT_MAX_LINE_COUNT 6

/* Maximum footer height to prevent overflow (unscaled pixels) */
#define FOOTER_MAX_HEIGHT 1000

/* Maximum attachments per message. Matches MAX_ATTACHMENTS_PER_MESSAGE
 * in the Python side (space_mixie_chat/constants.py); the backend
 * can't process more in a single turn. */
#define FOOTER_MAX_ATTACHMENTS 5

/* Maximum attachment collection size for sanity checking */
#define FOOTER_MAX_ATTACHMENT_COUNT 100

/** \} */

/* -------------------------------------------------------------------- */
/** \name '@' Mention Dropdown Constants
 * \{ */

/* Height of one suggestion row (unscaled pixels) */
#define FOOTER_MENTION_ROW_H_BASE 22

/* Inner padding of the dropdown panel (unscaled pixels) */
#define FOOTER_MENTION_PANEL_PAD_BASE 4

/* Gap between the input field and the dropdown panel (unscaled pixels) */
#define FOOTER_MENTION_GAP_BASE 4

/* Maximum visible suggestion rows. Matches MENTION_MAX_ITEMS in the Python
 * side (space_mixie_chat/constants.py) — Python never fills more items. */
#define FOOTER_MENTION_MAX_ROWS 6

/* Maximum published query length in bytes (includes the leading '@').
 * Matches the maxlen of scene.mixie_chat_mention_query. */
#define MENTION_QUERY_MAX 96

/** \} */

/* -------------------------------------------------------------------- */
/** \name Button Sizing Constants (scaled pixels)
 * \{ */

/* Mode dropdown width - sized for icon + text like "Image from scene" */
#define FOOTER_DROPDOWN_WIDTH_BASE 160

/* Dropdown internal padding (horizontal) */
#define FOOTER_DROPDOWN_PADDING_BASE 8

/* Style guide button width */
#define FOOTER_STYLE_BUTTON_WIDTH_BASE 90

/* Button spacing between elements */
#define FOOTER_BUTTON_SPACING_BASE 4

/* Remove button size for thumbnails */
#define FOOTER_REMOVE_BUTTON_SIZE_BASE 20

/* Input field horizontal padding (extra padding for text field) */
#define FOOTER_INPUT_H_PADDING_BASE 12

/** \} */

/* -------------------------------------------------------------------- */
/** \name Default Theme Fallbacks (unscaled pixels)
 * \{ */

/* Default bottom padding if theme not set */
#define FOOTER_DEFAULT_BOTTOM_PADDING 6

/* Default side padding if theme not set */
#define FOOTER_DEFAULT_SIDE_PADDING 8.0f

/* Default row spacing if theme not set */
#define FOOTER_DEFAULT_ROW_SPACING 2.0f

/* Default thumbnail spacing if theme not set */
#define FOOTER_DEFAULT_THUMBNAIL_SPACING 6.0f

/* Default thumbnail size if theme not set */
#define FOOTER_DEFAULT_THUMBNAIL_SIZE 48.0f

/* Default top padding if theme not set */
#define FOOTER_DEFAULT_TOP_PADDING 6.0f

/* Default thumbnail top margin if theme not set */
#define FOOTER_DEFAULT_THUMBNAIL_TOP_MARGIN 8.0f

/* Default main-footer gap if theme not set */
#define FOOTER_DEFAULT_MAIN_GAP 4.0f

/** \} */

}  // namespace blender
