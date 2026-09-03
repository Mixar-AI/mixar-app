/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Media pane internals — paint helpers, RNA plumbing, and the catalog param
 * chip model. See agent_ui_tabmedia.cc for the pane itself.
 */

#include <cstdio>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabmedia_intern.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {



/* -------------------------------------------------------------------- */
/** \name Paint helpers (duplicated from agent_ui_queue.cc's statics —
 * deliberately local, same reasoning).
 * \{ */

/* Painter primitives come from the pane kit (agent_ui_pane_kit.cc). */

void media_sanitize_key(const char *in, char *out, const int out_len)
{
  int n = 0;
  for (int i = 0; in[i] != '\0' && n < out_len - 1; i++) {
    const char c = in[i];
    const bool word = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                      (c >= '0' && c <= '9') || c == '_';
    out[n++] = word ? c : '_';
  }
  out[n] = '\0';
}

/** Resolve `scene.mixie_moodboard_sidebar.<tab_prop>`; false when missing. */
bool media_sidebar_tab_ptr(Scene *scene, const char *tab_prop, PointerRNA *r_ptr)
{
  if (!scene) {
    return false;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *sidebar_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_sidebar");
  if (!sidebar_prop || RNA_property_type(sidebar_prop) != PROP_POINTER) {
    return false;
  }
  PointerRNA sidebar = RNA_property_pointer_get(&scene_ptr, sidebar_prop);
  if (!sidebar.data) {
    return false;
  }
  PropertyRNA *tab = RNA_struct_find_property(&sidebar, tab_prop);
  if (!tab || RNA_property_type(tab) != PROP_POINTER) {
    return false;
  }
  *r_ptr = RNA_property_pointer_get(&sidebar, tab);
  return r_ptr->data != nullptr;
}

/** Current enum identifier + display label of `prop_name` on *ptr*. */
bool media_read_enum(const bContext *C,
               PointerRNA *ptr,
               const char *prop_name,
               char r_ident[64],
               char r_label[64])
{
  /* Catalog enums are Python-registered with items CALLBACKS — a null
   * context leaves the callback unrun and every lookup empty/stale. */
  bContext *C_mut = const_cast<bContext *>(C);
  r_ident[0] = r_label[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, prop_name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return false;
  }
  const int value = RNA_property_enum_get(ptr, prop);
  const char *ident = nullptr;
  if (RNA_property_enum_identifier(C_mut, ptr, prop, value, &ident) && ident) {
    BLI_strncpy(r_ident, ident, 64);
  }
  const char *label = nullptr;
  if (RNA_property_enum_name_gettexted(C_mut, ptr, prop, value, &label) && label) {
    BLI_strncpy(r_label, label, 64);
  }
  return r_ident[0] != '\0';
}

bool media_ident_is_placeholder(const char *ident)
{
  return ident[0] == '\0' || STREQ(ident, "LOADING") || STREQ(ident, "ERROR") ||
         STREQ(ident, "NONE");
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Param chip model
 * \{ */

/* MediaChipKind / MediaParamChip live in agent_ui_tabmedia_intern.hh. */

/** All `p_*` params of the catalog group into chips. Order follows RNA
 * definition order, which follows the schema dict — the same order the
 * moodboard's draw_service_params shows. `visible_if` conditions live only
 * in the Python schema and are not evaluated here (documented limitation:
 * a conditionally-hidden param stays visible in this pane). */
int media_gather_param_chips(const bContext *C, PointerRNA *group, MediaParamChip *chips, const int max_chips, int *r_total)
{
  int count = 0;
  *r_total = 0;
  RNA_STRUCT_BEGIN (group, prop) {
    const char *ident = RNA_property_identifier(prop);
    if (!STRPREFIX(ident, "p_")) {
      continue;
    }
    (*r_total)++;
    if (count >= max_chips) {
      continue;
    }
    MediaParamChip &chip = chips[count];
    chip = {};
    chip.on_wm_group = true;
    BLI_strncpy(chip.prop_id, ident, sizeof(chip.prop_id));
    BLI_strncpy(chip.label, RNA_property_ui_name(prop), sizeof(chip.label));

    const PropertyType type = RNA_property_type(prop);
    if (type == PROP_ENUM) {
      chip.kind = MediaChipKind::Enum;
      const int value = RNA_property_enum_get(group, prop);
      const char *label = nullptr;
      if (RNA_property_enum_name_gettexted(const_cast<bContext *>(C), group, prop, value, &label) && label) {
        BLI_strncpy(chip.value, label, sizeof(chip.value));
      }
    }
    else if (type == PROP_BOOLEAN) {
      chip.kind = MediaChipKind::Bool;
      chip.bool_value = RNA_property_boolean_get(group, prop);
    }
    else if (type == PROP_INT) {
      chip.kind = MediaChipKind::Int;
      SNPRINTF(chip.value, "%d", RNA_property_int_get(group, prop));
    }
    else {
      /* Floats/strings don't fit a chip strip; the moodboard N-panel remains
       * the full-fidelity surface for those (documented in the spec). */
      (*r_total)--;
      continue;
    }
    count++;
  }
  RNA_STRUCT_END;
  return count;
}

float media_chip_width(const MediaParamChip &chip, const float u, const float font, const float font_sub)
{
  const float pad = PANE_CHIP_PAD_X * u;
  switch (chip.kind) {
    case MediaChipKind::Enum:
      /* label  value ▾ */
      return pad * 2.0f + pane_text_width(chip.label, font_sub) + 10.0f * u +
             pane_text_width(chip.value, font) + 22.0f * u;
    case MediaChipKind::Bool:
      /* label [ON OFF] */
      return pad * 2.0f + pane_text_width(chip.label, font_sub) + 10.0f * u +
             pane_text_width("ON", font_sub) + pane_text_width("OFF", font_sub) + 44.0f * u;
    case MediaChipKind::Int:
      /* label - value + */
      return pad * 2.0f + pane_text_width(chip.label, font_sub) + 10.0f * u +
             pane_text_width(chip.value, font) + 64.0f * u;
  }
  return 0.0f;
}

void media_param_chips_paint(const MediaParamChip *chips,
                             const int count,
                             const float u,
                             const float font,
                             const float font_sub)
{
  const float col_param[4] = PANE_COL_CHIP;
  const float col_value[4] = PANE_COL_PILL_DIM;
  const float col_value_on[4] = PANE_COL_PILL;
  const float col_text[4] = AGENT_COL_TEXT;
  const float col_strong[4] = AGENT_COL_TEXT_STRONG;
  const float col_dim[4] = AGENT_COL_TEXT_DIM;

  for (int i = 0; i < count; i++) {
    const MediaParamChip &chip = chips[i];
    const float cy = BLI_rctf_cent_y(&chip.rect);
    pane_fill_round(&chip.rect, PANE_RADIUS * u, col_param);
    const float pad = PANE_CHIP_PAD_X * u;
    float tx = chip.rect.xmin + pad;
    pane_label_left(chip.label, tx, cy, font_sub, col_dim);
    tx += pane_text_width(chip.label, font_sub) + 10.0f * u;

    if (chip.kind == MediaChipKind::Enum) {
      pane_label_left(chip.value, tx, cy, font, col_text);
      /* Down chevron. */
      pane_label_left("\xE2\x96\xBE", chip.rect.xmax - pad - 10.0f * u, cy, font_sub, col_text);
    }
    else if (chip.kind == MediaChipKind::Bool) {
      rctf pill;
      pill.xmin = tx;
      pill.xmax = chip.rect.xmax - pad + 4.0f * u;
      pill.ymin = cy - (PANE_PILL_H * 0.5f) * u;
      pill.ymax = cy + (PANE_PILL_H * 0.5f) * u;
      pane_fill_round(&pill, PANE_RADIUS * u, chip.bool_value ? col_value_on : col_value);
      const float on_w = pane_text_width("ON", font_sub);
      const float off_w = pane_text_width("OFF", font_sub);
      const float span = BLI_rctf_size_x(&pill);
      pane_label_left("ON",
                      pill.xmin + span * 0.25f - on_w * 0.5f,
                      cy,
                      font_sub,
                      chip.bool_value ? col_strong : col_dim);
      pane_label_left("OFF",
                      pill.xmin + span * 0.75f - off_w * 0.5f,
                      cy,
                      font_sub,
                      chip.bool_value ? col_dim : col_strong);
    }
    else { /* Int */
      pane_label_left("\xE2\x88\x92", tx + 4.0f * u, cy, font, col_dim);
      pane_label_centre(
          chip.value, (tx + chip.rect.xmax - pad) * 0.5f, cy, font, col_text);
      pane_label_left("+", chip.rect.xmax - pad - 8.0f * u, cy, font, col_dim);
    }
  }
}

int media_collect_reference_images(const bContext *C,
                                   PointerRNA *tab_ptr,
                                   const bool video,
                                   Image **r_images,
                                   const int max_images)
{
  int count = 0;
  bool from_board = true;
  if (!video && tab_ptr != nullptr) {
    PropertyRNA *use_board = RNA_struct_find_property(tab_ptr, "use_reference_images");
    if (use_board && RNA_property_type(use_board) == PROP_BOOLEAN) {
      from_board = RNA_property_boolean_get(tab_ptr, use_board);
    }
  }
  if (from_board || tab_ptr == nullptr) {
    return pane_board_selected_images(C, r_images, max_images);
  }

  PropertyRNA *refs = RNA_struct_find_property(tab_ptr, "reference_images");
  if (!refs || RNA_property_type(refs) != PROP_COLLECTION) {
    return 0;
  }
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(tab_ptr, refs, &iter);
  for (; iter.valid && count < max_images; RNA_property_collection_next(&iter)) {
    PointerRNA item = iter.ptr;
    PropertyRNA *img_prop = RNA_struct_find_property(&item, "image");
    if (!img_prop || RNA_property_type(img_prop) != PROP_POINTER) {
      continue;
    }
    PointerRNA img = RNA_property_pointer_get(&item, img_prop);
    if (img.data) {
      r_images[count++] = static_cast<Image *>(img.data);
    }
  }
  RNA_property_collection_end(&iter);
  return count;
}

/** \} */

}  // namespace blender
