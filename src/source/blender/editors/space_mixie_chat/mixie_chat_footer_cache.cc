/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Footer cache system to avoid redundant per-frame operations.
 * Caches theme values and attachment data, invalidating on changes.
 */

#include <cstdint>

#include "BLI_string.h"
#include "BLI_vector.hh"

#include "DNA_scene_types.h"
#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

#include "RNA_access.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Footer Cache Storage
 * \{ */

/**
 * Complete footer cache structure (internal only).
 */
struct FooterCache {
  FooterThemeCache theme;
  blender::Vector<FooterAttachmentCache> attachments;
  int attachment_count;
  int attachment_collection_version; /* Track collection changes */
  bool attachments_valid;
};

/* Global footer cache */
static FooterCache g_footer_cache = {FooterThemeCache{}, {}, 0, -1, false};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Theme Cache Functions
 * \{ */

/**
 * Get theme version for cache invalidation.
 * Simple heuristic: pointer address changes if theme is modified.
 */
static uintptr_t get_theme_version()
{
  bTheme *btheme = static_cast<bTheme *>(U.themes.first);
  return btheme ? reinterpret_cast<uintptr_t>(btheme) : 0;
}

/**
 * Update theme cache from current theme settings.
 */
static void update_theme_cache()
{
  bTheme *btheme = static_cast<bTheme *>(U.themes.first);
  if (!btheme) {
    /* Use defaults if no theme */
    g_footer_cache.theme.bottom_padding = FOOTER_DEFAULT_BOTTOM_PADDING;
    g_footer_cache.theme.side_padding = FOOTER_DEFAULT_SIDE_PADDING;
    g_footer_cache.theme.row_spacing = FOOTER_DEFAULT_ROW_SPACING;
    g_footer_cache.theme.thumbnail_spacing = FOOTER_DEFAULT_THUMBNAIL_SPACING;
    g_footer_cache.theme.thumbnail_size = FOOTER_DEFAULT_THUMBNAIL_SIZE;
    g_footer_cache.theme.top_padding = FOOTER_DEFAULT_TOP_PADDING;
    g_footer_cache.theme.thumbnail_top_margin = FOOTER_DEFAULT_THUMBNAIL_TOP_MARGIN;
    g_footer_cache.theme.main_footer_gap = FOOTER_DEFAULT_MAIN_GAP;
    g_footer_cache.theme.button_row_height = 44.0f;
    g_footer_cache.theme.border_radius = 8.0f;
    g_footer_cache.theme.thumbnail_padding = 4.0f;
    g_footer_cache.theme.border_color[0] = 0.8f;
    g_footer_cache.theme.border_color[1] = 0.8f;
    g_footer_cache.theme.border_color[2] = 0.8f;
    g_footer_cache.theme.border_color[3] = 1.0f;
    g_footer_cache.theme.button_hover_color[0] = 0.4f;  /* Light blue hover */
    g_footer_cache.theme.button_hover_color[1] = 0.55f;
    g_footer_cache.theme.button_hover_color[2] = 0.7f;
    g_footer_cache.theme.button_hover_color[3] = 0.8f;
    g_footer_cache.theme.is_valid = true;
    g_footer_cache.theme.theme_version = 0;
    return;
  }

  const ThemeSpace *ts = &btheme->space_mixie_chat;

  /* Cache all theme values with fallbacks */
  g_footer_cache.theme.bottom_padding = (ts->chat_footer_bottom_padding > 0)
                                            ? float(ts->chat_footer_bottom_padding)
                                            : FOOTER_DEFAULT_BOTTOM_PADDING;

  g_footer_cache.theme.side_padding = (ts->chat_footer_side_padding >= 0.0f)
                                          ? ts->chat_footer_side_padding
                                          : FOOTER_DEFAULT_SIDE_PADDING;

  g_footer_cache.theme.row_spacing = (ts->chat_footer_row_spacing >= 0.0f)
                                         ? ts->chat_footer_row_spacing
                                         : FOOTER_DEFAULT_ROW_SPACING;

  g_footer_cache.theme.thumbnail_spacing = (ts->chat_footer_thumbnail_spacing >= 0.0f)
                                               ? ts->chat_footer_thumbnail_spacing
                                               : FOOTER_DEFAULT_THUMBNAIL_SPACING;

  g_footer_cache.theme.thumbnail_size = (ts->chat_footer_thumbnail_size >= 0.0f)
                                            ? ts->chat_footer_thumbnail_size
                                            : FOOTER_DEFAULT_THUMBNAIL_SIZE;

  g_footer_cache.theme.top_padding = (ts->chat_footer_top_padding >= 0.0f)
                                         ? ts->chat_footer_top_padding
                                         : FOOTER_DEFAULT_TOP_PADDING;

  g_footer_cache.theme.thumbnail_top_margin = (ts->chat_footer_thumbnail_top_margin >= 0.0f)
                                                  ? ts->chat_footer_thumbnail_top_margin
                                                  : FOOTER_DEFAULT_THUMBNAIL_TOP_MARGIN;

  g_footer_cache.theme.main_footer_gap = (ts->chat_main_footer_gap >= 0.0f)
                                             ? ts->chat_main_footer_gap
                                             : FOOTER_DEFAULT_MAIN_GAP;

  g_footer_cache.theme.button_row_height = (ts->chat_footer_button_row_height > 0.0f)
                                               ? ts->chat_footer_button_row_height
                                               : 44.0f;

  g_footer_cache.theme.input_height = (ts->chat_footer_input_height > 0.0f)
                                          ? ts->chat_footer_input_height
                                          : 60.0f;

  /* Cache additional theme properties */
  g_footer_cache.theme.border_radius = (ts->chat_thumbnail_border_radius >= 0.0f)
                                           ? ts->chat_thumbnail_border_radius
                                           : 8.0f;

  g_footer_cache.theme.thumbnail_padding = (ts->chat_thumbnail_padding >= 0.0f)
                                               ? ts->chat_thumbnail_padding
                                               : 4.0f;

  /* Cache border color */
  chat_ui_get_thumbnail_border_color(g_footer_cache.theme.border_color);

  /* Cache button hover color */
  chat_ui_get_button_hover_color(g_footer_cache.theme.button_hover_color);

  /* Cache toggle switch colors */
  chat_ui_get_toggle_on_color(g_footer_cache.theme.toggle_on_color);
  chat_ui_get_toggle_off_color(g_footer_cache.theme.toggle_off_color);
  chat_ui_get_toggle_knob_color(g_footer_cache.theme.toggle_knob_color);
  chat_ui_get_toggle_label_color(g_footer_cache.theme.toggle_label_color);

  g_footer_cache.theme.is_valid = true;
  g_footer_cache.theme.theme_version = get_theme_version();
}

/**
 * Get cached theme values, updating if necessary.
 */
const FooterThemeCache *footer_cache_get_theme()
{
  const uintptr_t current_version = get_theme_version();

  /* Invalidate cache if theme changed */
  if (!g_footer_cache.theme.is_valid || g_footer_cache.theme.theme_version != current_version) {
    update_theme_cache();
  }

  return &g_footer_cache.theme;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Attachment Cache Functions
 * \{ */

/**
 * Get collection version for cache invalidation.
 *
 * Earlier this just returned the collection length. That misses the
 * case where attachments are swapped without changing count — e.g.
 * the moodboard sync replaces attachment "A" with attachment "B"
 * (length stays at 1) and the footer keeps rendering the stale
 * thumbnail of "A". Now we fold each attachment's path into a 32-bit
 * FNV-1a hash so any path change bumps the version.
 */
static int get_attachment_collection_version(Scene *scene)
{
  if (!scene) {
    return 0;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_pending_attachments");
  if (!prop) {
    return 0;
  }

  /* FNV-1a 32-bit init constant. Cheap, well-distributed, no deps. */
  uint32_t hash = 2166136261u;
  const uint32_t fnv_prime = 16777619u;

  /* Mix the count first so an empty vs. single-item-with-empty-path
   * collection don't collide. */
  int count = RNA_property_collection_length(&scene_ptr, prop);
  for (int i = 0; i < 4; i++) {
    hash ^= uint32_t((count >> (i * 8)) & 0xff);
    hash *= fnv_prime;
  }

  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, prop, &iter);
  PropertyRNA *path_prop = nullptr;
  if (iter.valid) {
    path_prop = RNA_struct_find_property(&iter.ptr, "image_path");
  }
  while (iter.valid) {
    if (path_prop) {
      int path_len = RNA_property_string_length(&iter.ptr, path_prop);
      if (path_len > 0 && path_len < 1024) {
        char path[1024];
        RNA_property_string_get(&iter.ptr, path_prop, path);
        for (int i = 0; i < path_len; i++) {
          hash ^= uint32_t(static_cast<unsigned char>(path[i]));
          hash *= fnv_prime;
        }
      }
      /* Per-element separator so "AB" and "A" + "B" hash differently. */
      hash ^= 0x1fu;
      hash *= fnv_prime;
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);

  /* Cache field stores an int — fold to signed without losing bits. */
  return int(hash);
}

/**
 * Update attachment cache from scene data.
 */
static void update_attachment_cache(Scene *scene)
{
  if (!scene) {
    /* CRITICAL: Don't update cache with NULL scene - keep existing data!
     * NULL scene calls happen during initialization and would poison the cache. */
    return;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *pending_prop = RNA_struct_find_property(&scene_ptr,
                                                       "mixie_chat_pending_attachments");

  if (!pending_prop) {
    g_footer_cache.attachments.clear();
    g_footer_cache.attachment_count = 0;
    g_footer_cache.attachments_valid = true;
    return;
  }

  int count = RNA_property_collection_length(&scene_ptr, pending_prop);

  /* Limit to maximum attachments */
  count = (count < FOOTER_MAX_ATTACHMENTS) ? count : FOOTER_MAX_ATTACHMENTS;

  /* Resize cache vector */
  g_footer_cache.attachments.clear();
  g_footer_cache.attachments.reserve(count);

  /* Cache attachment data */
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, pending_prop, &iter);

  PropertyRNA *path_prop = nullptr;
  PropertyRNA *source_prop = nullptr;

  if (iter.valid) {
    path_prop = RNA_struct_find_property(&iter.ptr, "image_path");
    source_prop = RNA_struct_find_property(&iter.ptr, "image_source");
  }

  int index = 0;
  while (iter.valid && index < count) {
    FooterAttachmentCache cached_attachment;

    if (path_prop && source_prop) {
      /* Get path - use RNA_property_string_get which handles allocation */
      int path_len = RNA_property_string_length(&iter.ptr, path_prop);
      if (path_len > 0 && path_len < 1024) {
        RNA_property_string_get(&iter.ptr, path_prop, cached_attachment.path);
        cached_attachment.source = RNA_property_enum_get(&iter.ptr, source_prop);
      }
      else {
        cached_attachment.path[0] = '\0';
        cached_attachment.source = 0;
      }
    }
    else {
      cached_attachment.path[0] = '\0';
      cached_attachment.source = 0;
    }

    g_footer_cache.attachments.append(cached_attachment);
    index++;
    RNA_property_collection_next(&iter);
  }

  RNA_property_collection_end(&iter);

  g_footer_cache.attachment_count = count;
  g_footer_cache.attachment_collection_version = get_attachment_collection_version(scene);
  g_footer_cache.attachments_valid = true;
}

/**
 * Get cached attachment data, updating if necessary.
 */
const blender::Vector<FooterAttachmentCache> *footer_cache_get_attachments(Scene *scene,
                                                                            int *out_count)
{
  int current_version = get_attachment_collection_version(scene);

  /* Invalidate cache if collection changed */
  if (!g_footer_cache.attachments_valid ||
      g_footer_cache.attachment_collection_version != current_version)
  {
    update_attachment_cache(scene);
  }

  if (out_count) {
    *out_count = g_footer_cache.attachment_count;
  }

  return &g_footer_cache.attachments;
}

/**
 * Invalidate all footer caches.
 * Call this when scene or theme changes are detected.
 * NOTE: This marks caches as invalid but does NOT free memory.
 * Use footer_cache_clear() when freeing the space.
 */
void footer_cache_invalidate()
{
  g_footer_cache.theme.is_valid = false;
  g_footer_cache.attachments_valid = false;
}

void footer_cache_clear()
{
  /* Clear attachment vector and free its memory */
  g_footer_cache.attachments.clear_and_shrink();

  /* Reset cache state */
  g_footer_cache.attachment_count = 0;
  g_footer_cache.attachment_collection_version = -1;
  g_footer_cache.attachments_valid = false;

  /* Invalidate theme cache */
  g_footer_cache.theme.is_valid = false;
  g_footer_cache.theme.theme_version = 0;
}

/**
 * Get pending attachment count (uses cache).
 */
int footer_cache_get_attachment_count(Scene *scene)
{
  int count = 0;
  footer_cache_get_attachments(scene, &count);
  return count;
}

/** \} */
