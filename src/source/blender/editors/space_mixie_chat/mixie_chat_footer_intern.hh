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

#include "BLI_vector.hh"

struct Main;
struct Scene;

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
 * \return Required height in unscaled units
 */
int footer_layout_calculate_height(Scene *scene,
                                    const FooterThemeCache *theme,
                                    bool *out_has_overflow,
                                    int input_line_count = 0);

/**
 * Calculate X/Y positions for footer UI elements.
 * Provides consistent positioning across layout and draw functions.
 *
 * \param region_width: Width of the footer region
 * \param pending_count: Number of pending attachments
 * \param theme: Cached theme values
 * \param out_positions: Structure to fill with calculated positions
 * \param input_line_count: Dynamic line count for input field (0 = use default minimum)
 */
void footer_layout_calculate_positions(int region_width,
                                        int pending_count,
                                        const FooterThemeCache *theme,
                                        FooterElementPositions *out_positions,
                                        int input_line_count = 0);

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
