/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Internal declarations for footer modules.
 * Shared between footer_cache, footer_layout, and footer_thumbnails.
 */

#pragma once

#include <cstdint>

#include "BLI_rect.h"
#include "BLI_vector.hh"

#include "mixie_chat_footer_constants.hh"

struct ARegion;
struct Main;
struct Scene;
struct bContext;

/* -------------------------------------------------------------------- */
/** \name Footer Cache Structures
 * \{ */

/**
 * Cached attachment data to avoid per-frame allocations and RNA queries.
 */
struct FooterAttachmentCache {
  char path[1024]; /* Image path */
  int source;      /* Image source type (FILE or BLEND_DATA) */
};

/**
 * Footer theme cache to avoid redundant theme lookups.
 * All values cached from ThemeSpace on first access.
 */
struct FooterThemeCache {
  /* Spacing and sizing (in pixels) */
  float bottom_padding;
  float side_padding;
  float row_spacing;
  float thumbnail_spacing;
  float thumbnail_size;
  float top_padding;
  float thumbnail_top_margin;  /* Dedicated margin above thumbnails */
  float main_footer_gap;
  float button_row_height;  /* Single-row height for buttons (unscaled) */
  float input_height;       /* Height of the multi-line text input (unscaled) */
  float border_radius;
  float thumbnail_padding;

  /* Colors */
  float border_color[4];
  float button_hover_color[4];  /* Footer button hover color */
  float toggle_on_color[4];     /* Toggle track ON color */
  float toggle_off_color[4];    /* Toggle track OFF color */
  float toggle_knob_color[4];   /* Toggle knob color */
  float toggle_label_color[4];  /* Toggle label text color */

  /* Cache validity tracking */
  bool is_valid;
  /* Track theme changes. Holds a pointer-derived key, so it must be pointer
   * sized — truncating to int made distinct themes collide on the low 32
   * bits and skip a needed refresh. */
  uintptr_t theme_version;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Layout Structures
 * \{ */

/**
 * Calculated positions for all footer UI elements.
 * Provides consistent positioning across layout and draw functions.
 */
struct FooterElementPositions {
  /* Button row (bottom) */
  int buttons_y;
  int dropdown_x;
  int dropdown_width;
  int attach_btn_x;
  int send_btn_x;
  int btn_size;          /* Size of send button */
  int attach_btn_size;   /* Size of attach button */

  /* Input row (middle) — input_height is multi-line (FOOTER_INPUT_LINE_COUNT rows) */
  int input_y;
  int input_x;
  int input_w;
  int input_height;
  int button_row_height;  /* Single-row height for buttons (scaled) */

  /* '@' mention dropdown (between input row and thumbnails, if open) */
  int mention_y;     /* Bottom of the dropdown panel (scaled) */
  int mention_count; /* Number of suggestion rows (0 = closed) */

  /* Thumbnail row (top, if present) */
  int thumb_y;
  int thumb_size;
  int thumb_spacing;

  /* Padding */
  int side_padding;
  int bottom_padding;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Cache API
 * \{ */

/**
 * Get cached theme values, updating if necessary.
 * PERFORMANCE: Eliminates redundant theme lookups (60+ per second).
 */
const FooterThemeCache *footer_cache_get_theme();

/**
 * Get cached attachment data, updating if necessary.
 * PERFORMANCE: Eliminates per-frame allocations and RNA queries.
 *
 * \param scene: Scene containing pending attachments
 * \param out_count: Filled with attachment count (optional)
 * \return Vector of cached attachment data
 */
const blender::Vector<FooterAttachmentCache> *footer_cache_get_attachments(Scene *scene,
                                                                            int *out_count);

/**
 * Get pending attachment count (uses cache).
 */
int footer_cache_get_attachment_count(Scene *scene);

/**
 * Invalidate all footer caches.
 * Call this when scene or theme changes are detected.
 */
void footer_cache_invalidate();

/**
 * Clear all footer caches and free allocated memory.
 * Call when space is destroyed to prevent memory leaks.
 */
void footer_cache_clear();

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Layout API
 * \{ */

/**
 * Count the number of visible lines in the chat input text.
 * Counts explicit newlines (from Shift+Enter). Clamps between
 * FOOTER_INPUT_LINE_COUNT (3) and FOOTER_INPUT_MAX_LINE_COUNT (10).
 *
 * \param scene: Scene to read mixie_chat_input from
 * \return Line count clamped to [min, max] range
 */
int footer_layout_get_input_line_count(Scene *scene, int region_width);

/**
 * Calculate required footer height based on pending attachments.
 * CRITICAL: Returns UNSCALED units - Blender applies UI_SCALE_FAC when creating window rectangle.
 *
 * This is the single source of truth for footer height calculation.
 * FIXES: Eliminates code duplication between layout and draw functions.
 *
 * \param scene: Scene containing pending attachments
 * \param theme: Cached theme values (pass nullptr to fetch fresh)
 * \param out_has_overflow: Set to true if height exceeds maximum limit (optional)
 * \param input_line_count: Dynamic line count for input field (0 = use default minimum)
 * \param mention_row_count: Visible '@' mention suggestion rows (0 = dropdown closed)
 * \return Required height in unscaled units
 */
int footer_layout_calculate_height(Scene *scene,
                                    const FooterThemeCache *theme,
                                    bool *out_has_overflow,
                                    int input_line_count = 0,
                                    int mention_row_count = 0);

/**
 * Calculate X/Y positions for footer UI elements.
 * Provides consistent positioning across layout and draw functions.
 *
 * \param region_width: Width of the footer region
 * \param pending_count: Number of pending attachments
 * \param theme: Cached theme values
 * \param out_positions: Structure to fill with calculated positions
 * \param input_line_count: Dynamic line count for input field (0 = use default minimum)
 * \param mention_row_count: Visible '@' mention suggestion rows (0 = dropdown closed)
 */
void footer_layout_calculate_positions(int region_width,
                                        int pending_count,
                                        const FooterThemeCache *theme,
                                        FooterElementPositions *out_positions,
                                        int input_line_count = 0,
                                        int mention_row_count = 0);

/** \} */

/* -------------------------------------------------------------------- */
/** \name '@' Mention Autocomplete (mixie_chat_mention.cc)
 *
 * C++ owns the text cursor and the dropdown; Python owns the candidate data
 * (see space_mixie_chat/core/mention_registry.py). The bridge is a set of
 * Python-registered scene properties: mixie_chat_mention_query (written here,
 * update callback runs the search), _items / _active / _show (read here).
 * \{ */

/**
 * Find the active "@token" around the byte cursor in `text`.
 * A token starts with '@' at the start of the text or after whitespace and
 * contains no whitespace between the '@' and the cursor.
 *
 * \param r_tok_start: Byte offset of the '@'.
 * \param r_tok_end: Byte offset one past the token (extends beyond the cursor
 *                   to the next whitespace/end, so accepting replaces the whole word).
 * \param r_query: Receives '@' + the typed part (token start .. cursor).
 * \return true if an active token was found.
 */
bool mixie_chat_mention_detect(const char *text,
                               int cursor_bytes,
                               int *r_tok_start,
                               int *r_tok_end,
                               char *r_query,
                               int query_maxncpy);

/** Write `query` ("" = no active token) to the scene and run the Python
 * search callback synchronously. No-op when unchanged or unregistered. */
void mixie_chat_mention_publish(bContext *C, Scene *scene, const char *query);

bool mixie_chat_mention_is_open(Scene *scene);
/** Total items in the scrollable list (<= FOOTER_MENTION_MAX_ITEMS). */
int mixie_chat_mention_total_count(Scene *scene);
/** VISIBLE rows (<= FOOTER_MENTION_MAX_ROWS). */
int mixie_chat_mention_row_count(Scene *scene);
int mixie_chat_mention_active_get(Scene *scene);
void mixie_chat_mention_active_set(Scene *scene, int index);
/** Move the active row by `dir` (+1/-1), wrapping; scroll follows. */
void mixie_chat_mention_step(Scene *scene, int dir);
/** First visible item index (clamped to the current list). */
int mixie_chat_mention_scroll_get(Scene *scene);
void mixie_chat_mention_scroll_set(Scene *scene, int scroll);
void mixie_chat_mention_scroll_by(Scene *scene, int delta);
/** Hide the dropdown (keeps the query; typing re-evaluates). */
void mixie_chat_mention_dismiss(Scene *scene);
/** Copy the active item's replacement text ("@Name ") into `r_buf`.
 * \return its length, or 0 when unavailable. */
int mixie_chat_mention_insert_text_get(Scene *scene, char *r_buf, int buf_maxncpy);

/** Dropdown geometry in region pixels; row 0 is the top row.
 * \return the row count (0 = closed). */
int mixie_chat_mention_rows_get(Scene *scene,
                                int region_winx,
                                rctf *r_panel,
                                rctf r_rows[FOOTER_MENTION_MAX_ROWS]);
/** \return ITEM index (scroll applied) under the WINDOW-space point `xy`, or -1. */
int mixie_chat_mention_row_hit(Scene *scene, const ARegion *region, const int xy[2]);
/** True when the WINDOW-space point `xy` is inside the dropdown panel. */
bool mixie_chat_mention_panel_hit(Scene *scene, const ARegion *region, const int xy[2]);
void mixie_chat_mention_draw(Scene *scene, ARegion *region);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Thumbnail API
 * \{ */

/**
 * Load image by path and source type.
 * Source types: 0 = FILE (disk), 1 = BLEND_DATA (internal)
 *
 * \param bmain: Main database for image lookup
 * \param path: Image path (filepath or internal name)
 * \param source: Source type (0=FILE, 1=BLEND_DATA)
 * \return Loaded image or nullptr if not found
 */
struct Image *footer_thumbnails_load_image(Main *bmain, const char *path, int source);

/**
 * Draw an image thumbnail at the specified position with aspect-correct scaling.
 * Centers the image within the thumbnail area and maintains aspect ratio.
 *
 * PERFORMANCE: GPU_blend should be set by caller to avoid redundant state changes.
 *
 * \param bmain: Main database for image lookup
 * \param path: Image path
 * \param source: Source type (0=FILE, 1=BLEND_DATA)
 * \param x: Bottom-left X coordinate
 * \param y: Bottom-left Y coordinate
 * \param size: Thumbnail size (width and height)
 */
void footer_thumbnails_draw_image(Main *bmain,
                                   const char *path,
                                   int source,
                                   float x,
                                   float y,
                                   float size);

/**
 * Draw a rounded border around a thumbnail.
 * Uses theme values for border radius and color.
 *
 * \param x: Bottom-left X coordinate
 * \param y: Bottom-left Y coordinate
 * \param size: Thumbnail size (width and height)
 * \param color: RGBA border color
 */
void footer_thumbnails_draw_border(float x, float y, float size, const float color[4]);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Overlay Drawing (mixie_chat_footer_draw.cc)
 * \{ */

struct ARegion;
struct bContext;
struct PointerRNA;

void footer_draw_send_button_glow(ARegion *region,
                                   PointerRNA *scene_ptr,
                                   const FooterElementPositions &pos,
                                   float scale);
void footer_draw_submit_icon(ARegion *region, const FooterElementPositions &pos);
void footer_draw_plan_toggle(ARegion *region,
                              const FooterThemeCache *theme,
                              const FooterElementPositions &pos,
                              bool plan_enabled,
                              int plan_toggle_x,
                              float scale);
void footer_draw_thumbnails(const bContext *C,
                             ARegion *region,
                             Main *bmain,
                             PointerRNA *scene_ptr,
                             const FooterElementPositions &pos,
                             const FooterThemeCache *theme,
                             int pending_count,
                             const blender::Vector<FooterAttachmentCache> *attachments,
                             float scale);

/** \} */
