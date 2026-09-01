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

#include "agent_ui_tabmedia_intern.hh"
#include "agent_ui_theme.hh"



/* -------------------------------------------------------------------- */
/** \name Paint helpers (duplicated from agent_ui_queue.cc's statics —
 * deliberately local, same reasoning).
 * \{ */

void media_fill_round(const rctf *rect, const float radius, const float col[4])
{
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(rect, true, radius, col);
}

static int media_font()
{
  return BLF_default();
}

float media_text_width(const char *text, const float size)
{
  const int font = media_font();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void media_label_left(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = media_font();
  BLF_size(font, size);
  BLF_disable(font, BLF_CLIPPING);

  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;

  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

void media_label_centre(
    const char *text, const float cx, const float cy, const float size, const float col[4])
{
  media_label_left(text, cx - media_text_width(text, size) * 0.5f, cy, size, col);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name RNA plumbing
 * \{ */

/** engine.py's `_sanitize`: every non-word char becomes '_'. */
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
  const float pad = AGENT_DU(AGENT_CHIP_PAD_X) + 4.0f * u;
  switch (chip.kind) {
    case MediaChipKind::Enum:
      /* label  value ▾ */
      return pad * 2.0f + media_text_width(chip.label, font_sub) + 10.0f * u +
             media_text_width(chip.value, font) + 22.0f * u;
    case MediaChipKind::Bool:
      /* label [ON OFF] */
      return pad * 2.0f + media_text_width(chip.label, font_sub) + 10.0f * u +
             media_text_width("ON", font_sub) + media_text_width("OFF", font_sub) + 44.0f * u;
    case MediaChipKind::Int:
      /* label - value + */
      return pad * 2.0f + media_text_width(chip.label, font_sub) + 10.0f * u +
             media_text_width(chip.value, font) + 64.0f * u;
  }
  return 0.0f;
}

/** \} */


