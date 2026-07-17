/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * '@' mention autocomplete for the chat input.
 *
 * Split of responsibilities (C++ owns the cursor, Python owns the data):
 *   - interface_handlers.cc detects the active "@token" around the text
 *     cursor on every edit and publishes it into the Python-registered
 *     `scene.mixie_chat_mention_query` property (mixie_chat_mention_publish
 *     fires RNA_property_update, which runs the Python search callback
 *     synchronously — same bridge as the \x1F Enter-submit marker).
 *   - Python (space_mixie_chat/core/mention_registry.py) matches the query
 *     against root objects / materials / assets and fills the
 *     `scene.mixie_chat_mention_items` collection + `_active` + `_show`.
 *   - This file reads that state back for the footer dropdown: geometry,
 *     hit-testing, drawing and the accept/step/dismiss helpers used by the
 *     text-edit event hooks.
 *
 * All RNA reads are guarded with RNA_struct_find_property so the feature
 * degrades gracefully when the Python side hasn't registered (same pattern
 * as mixie_chat_is_busy in mixie_chat_footer.cc).
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"

#include "ED_screen.hh"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name RNA Property Helpers
 * \{ */

static PropertyRNA *mention_prop_find(PointerRNA *scene_ptr, const char *name)
{
  return RNA_struct_find_property(scene_ptr, name);
}

static int mention_items_len(PointerRNA *scene_ptr)
{
  PropertyRNA *prop = mention_prop_find(scene_ptr, "mixie_chat_mention_items");
  if (!prop) {
    return 0;
  }
  return RNA_property_collection_length(scene_ptr, prop);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Token Detection
 * \{ */

bool mixie_chat_mention_detect(const char *text,
                               int cursor_bytes,
                               int *r_tok_start,
                               int *r_tok_end,
                               char *r_query,
                               int query_maxncpy)
{
  if (text == nullptr || query_maxncpy < 2) {
    return false;
  }
  const int len = int(strlen(text));
  const int cursor = std::clamp(cursor_bytes, 0, len);

  /* Scan backward from the cursor for the '@' that starts the token.
   * Whitespace between '@' and the cursor breaks the token (typing a space
   * naturally closes the dropdown). '@' and whitespace are ASCII, so a
   * bytewise scan is UTF-8 safe. */
  int at = -1;
  for (int i = cursor - 1; i >= 0; i--) {
    const char c = text[i];
    if (c == '@') {
      at = i;
      break;
    }
    if (ELEM(c, ' ', '\t', '\n', '\r')) {
      return false;
    }
    if ((cursor - i) > MENTION_QUERY_MAX) {
      return false;
    }
  }
  if (at < 0) {
    return false;
  }

  /* The '@' must start the message or follow whitespace so email-like text
   * ("user@example.com") never triggers the dropdown. */
  if (at > 0 && !ELEM(text[at - 1], ' ', '\t', '\n', '\r')) {
    return false;
  }

  /* Token extends to the next whitespace (or end): accepting a suggestion
   * consumes the whole word being completed, not just the typed prefix. */
  int end = cursor;
  while (end < len && !ELEM(text[end], ' ', '\t', '\n', '\r')) {
    end++;
  }

  if (r_tok_start) {
    *r_tok_start = at;
  }
  if (r_tok_end) {
    *r_tok_end = end;
  }

  /* Query = '@' + the part the user actually typed (up to the cursor). */
  const int qlen = std::min(cursor - at, query_maxncpy - 1);
  memcpy(r_query, text + at, size_t(qlen));
  r_query[qlen] = '\0';
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name State Bridge (scene RNA properties registered from Python)
 * \{ */

void mixie_chat_mention_publish(bContext *C, Scene *scene, const char *query)
{
  if (!scene || !query) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = mention_prop_find(&scene_ptr, "mixie_chat_mention_query");
  if (!prop) {
    return; /* Python side not registered — feature off. */
  }
  /* Skip no-op writes so the Python search callback only runs when the
   * query actually changed. */
  char current[MENTION_QUERY_MAX + 8] = "";
  RNA_property_string_get(&scene_ptr, prop, current);
  if (STREQ(current, query)) {
    return;
  }
  RNA_property_string_set(&scene_ptr, prop, query);
  /* Runs the Python update callback synchronously (fills the items
   * collection and the show/active flags before we return). */
  RNA_property_update(C, &scene_ptr, prop);
}

bool mixie_chat_mention_is_open(Scene *scene)
{
  if (!scene) {
    return false;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *show_prop = mention_prop_find(&scene_ptr, "mixie_chat_mention_show");
  if (!show_prop || !RNA_property_boolean_get(&scene_ptr, show_prop)) {
    return false;
  }
  return mention_items_len(&scene_ptr) > 0;
}

int mixie_chat_mention_row_count(Scene *scene)
{
  if (!mixie_chat_mention_is_open(scene)) {
    return 0;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  return std::min(mention_items_len(&scene_ptr), FOOTER_MENTION_MAX_ROWS);
}

int mixie_chat_mention_active_get(Scene *scene)
{
  if (!scene) {
    return 0;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = mention_prop_find(&scene_ptr, "mixie_chat_mention_active");
  if (!prop) {
    return 0;
  }
  return RNA_property_int_get(&scene_ptr, prop);
}

void mixie_chat_mention_active_set(Scene *scene, int index)
{
  if (!scene) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = mention_prop_find(&scene_ptr, "mixie_chat_mention_active");
  if (!prop) {
    return;
  }
  const int count = std::min(mention_items_len(&scene_ptr), FOOTER_MENTION_MAX_ROWS);
  index = (count > 0) ? std::clamp(index, 0, count - 1) : 0;
  RNA_property_int_set(&scene_ptr, prop, index);
}

void mixie_chat_mention_step(Scene *scene, int dir)
{
  const int count = mixie_chat_mention_row_count(scene);
  if (count <= 0) {
    return;
  }
  const int active = mixie_chat_mention_active_get(scene);
  mixie_chat_mention_active_set(scene, (active + dir + count) % count);
}

void mixie_chat_mention_dismiss(Scene *scene)
{
  if (!scene) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = mention_prop_find(&scene_ptr, "mixie_chat_mention_show");
  if (prop) {
    RNA_property_boolean_set(&scene_ptr, prop, false);
  }
}

int mixie_chat_mention_insert_text_get(Scene *scene, char *r_buf, int buf_maxncpy)
{
  if (!scene || !r_buf || buf_maxncpy < 2) {
    return 0;
  }
  r_buf[0] = '\0';

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *items_prop = mention_prop_find(&scene_ptr, "mixie_chat_mention_items");
  if (!items_prop) {
    return 0;
  }
  const int count = std::min(RNA_property_collection_length(&scene_ptr, items_prop),
                             FOOTER_MENTION_MAX_ROWS);
  if (count <= 0) {
    return 0;
  }
  const int active = std::clamp(mixie_chat_mention_active_get(scene), 0, count - 1);

  PointerRNA item_ptr;
  if (!RNA_property_collection_lookup_int(&scene_ptr, items_prop, active, &item_ptr)) {
    return 0;
  }
  PropertyRNA *insert_prop = RNA_struct_find_property(&item_ptr, "insert_text");
  if (!insert_prop) {
    return 0;
  }
  if (RNA_property_string_length(&item_ptr, insert_prop) >= buf_maxncpy) {
    return 0; /* Would truncate mid-UTF8 — refuse rather than corrupt. */
  }
  RNA_property_string_get(&item_ptr, insert_prop, r_buf);
  return int(strlen(r_buf));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Dropdown Geometry & Hit Testing
 * \{ */

/**
 * Compute the dropdown panel + row rects (region pixel coords) for a footer
 * of `region_winx` width. Row 0 is the TOP row (natural reading order).
 * Geometry is recomputed from scratch — deterministic from (scene, width) —
 * so the event hooks and the draw never disagree.
 *
 * \return the number of rows (0 = dropdown closed).
 */
int mixie_chat_mention_rows_get(Scene *scene,
                                int region_winx,
                                rctf *r_panel,
                                rctf r_rows[FOOTER_MENTION_MAX_ROWS])
{
  const int count = mixie_chat_mention_row_count(scene);
  if (count <= 0) {
    return 0;
  }

  const FooterThemeCache *theme = footer_cache_get_theme();
  const int pending_count = footer_cache_get_attachment_count(scene);
  const int input_lines = footer_layout_get_input_line_count(scene, region_winx);

  FooterElementPositions pos;
  footer_layout_calculate_positions(region_winx, pending_count, theme, &pos, input_lines, count);

  const float scale = UI_SCALE_FAC;
  const float pad = FOOTER_MENTION_PANEL_PAD_BASE * scale;
  const float row_h = FOOTER_MENTION_ROW_H_BASE * scale;

  if (r_panel) {
    r_panel->xmin = float(pos.input_x);
    r_panel->xmax = float(pos.input_x + pos.input_w);
    r_panel->ymin = float(pos.mention_y);
    r_panel->ymax = float(pos.mention_y) + pad * 2.0f + row_h * float(count);
  }
  if (r_rows) {
    for (int i = 0; i < count; i++) {
      rctf *row = &r_rows[i];
      row->xmin = float(pos.input_x) + pad;
      row->xmax = float(pos.input_x + pos.input_w) - pad;
      /* Row 0 on top. */
      row->ymin = float(pos.mention_y) + pad + row_h * float(count - 1 - i);
      row->ymax = row->ymin + row_h;
    }
  }
  return count;
}

int mixie_chat_mention_row_hit(Scene *scene, const ARegion *region, const int xy[2])
{
  if (!region) {
    return -1;
  }
  rctf rows[FOOTER_MENTION_MAX_ROWS];
  const int count = mixie_chat_mention_rows_get(scene, region->winx, nullptr, rows);
  const float rx = float(xy[0] - region->winrct.xmin);
  const float ry = float(xy[1] - region->winrct.ymin);
  for (int i = 0; i < count; i++) {
    if (BLI_rctf_isect_pt(&rows[i], rx, ry)) {
      return i;
    }
  }
  return -1;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Dropdown Drawing
 * \{ */

static int mention_kind_icon(int kind)
{
  switch (kind) {
    case 1:
      return ICON_MATERIAL;
    case 2:
      return ICON_ASSET_MANAGER;
    case 0:
    default:
      return ICON_OBJECT_DATA;
  }
}

static const char *mention_kind_label(int kind)
{
  switch (kind) {
    case 1:
      return "Material";
    case 2:
      return "Asset";
    case 0:
    default:
      return "Object";
  }
}

void mixie_chat_mention_draw(Scene *scene, ARegion *region)
{
  rctf panel;
  rctf rows[FOOTER_MENTION_MAX_ROWS];
  const int count = mixie_chat_mention_rows_get(scene, region->winx, &panel, rows);
  if (count <= 0) {
    return;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *items_prop = mention_prop_find(&scene_ptr, "mixie_chat_mention_items");
  if (!items_prop) {
    return;
  }
  const int active = std::clamp(mixie_chat_mention_active_get(scene), 0, count - 1);

  const FooterThemeCache *theme = footer_cache_get_theme();
  const float scale = UI_SCALE_FAC;

  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);

  /* Panel: same rounded/bordered style as attachment thumbnails. */
  float bg_color[4];
  chat_ui_get_button_bg_color(bg_color);
  const float radius = theme->border_radius * scale;
  chat_ui_draw_rounded_rect_bordered(&panel, radius, bg_color, theme->border_color, U.pixelsize);

  /* Active row highlight (keyboard selection + mouse hover share it). */
  if (active >= 0 && active < count) {
    chat_ui_draw_rounded_rect(&rows[active], radius * 0.6f, theme->button_hover_color);
  }

  float text_color[4];
  float kind_color[4];
  chat_ui_get_button_text_color(text_color);
  chat_ui_get_placeholder_text_color(kind_color);

  const int font_size = int(11.0f * scale);
  const float icon_size = 16.0f * scale;
  const float inner_pad = 6.0f * scale;

  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, items_prop, &iter);
  for (int i = 0; iter.valid && i < count; RNA_property_collection_next(&iter), i++) {
    char name[320] = "";
    int kind = 0;
    PropertyRNA *name_prop = RNA_struct_find_property(&iter.ptr, "name");
    PropertyRNA *kind_prop = RNA_struct_find_property(&iter.ptr, "kind");
    if (name_prop && RNA_property_string_length(&iter.ptr, name_prop) < int(sizeof(name))) {
      RNA_property_string_get(&iter.ptr, name_prop, name);
    }
    if (kind_prop) {
      kind = RNA_property_int_get(&iter.ptr, kind_prop);
    }

    const rctf *row = &rows[i];
    const float row_cy = (row->ymin + row->ymax) * 0.5f;

    /* Type icon at the left edge (same aspect convention as
     * footer_draw_submit_icon: 16 / target pixel size). */
    UI_icon_draw_ex(row->xmin + inner_pad,
                    row_cy - icon_size * 0.5f,
                    mention_kind_icon(kind),
                    16.0f / icon_size,
                    0.8f,
                    0.0f,
                    nullptr,
                    false,
                    UI_NO_ICON_OVERLAY_TEXT);

    /* Name, vertically centered on the row (y is the text baseline). */
    const float baseline = row_cy - float(font_size) * 0.36f;
    chat_ui_draw_label(
        name, row->xmin + inner_pad * 2.0f + icon_size, baseline, font_size, 0, text_color, false);

    /* Dim kind tag, right aligned. */
    chat_ui_draw_label(mention_kind_label(kind),
                       row->xmax - inner_pad,
                       baseline,
                       int(float(font_size) * 0.9f),
                       0,
                       kind_color,
                       true);
  }
  RNA_property_collection_end(&iter);

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */
