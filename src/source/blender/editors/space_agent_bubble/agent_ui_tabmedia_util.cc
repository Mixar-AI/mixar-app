/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Media pane internals — native controls, RNA plumbing, and the catalog param
 * chip model. See agent_ui_tabmedia.cc for the pane itself.
 */

#include <algorithm>
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

#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "WM_types.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabmedia_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Media bindings and shared native controls
 * \{ */

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
 * moodboard's draw_service_params shows. `visible_if` is evaluated from the
 * group's `mixar_visible_if` table so hidden params never occupy a chip
 * slot or the overflow count. */
int media_gather_param_chips(const bContext *C, PointerRNA *group, MediaParamChip *chips, const int max_chips, int *r_total)
{
  int count = 0;
  *r_total = 0;
  RNA_STRUCT_BEGIN (group, prop) {
    const char *ident = RNA_property_identifier(prop);
    if (!STRPREFIX(ident, "p_")) {
      continue;
    }
    if (!pane_schema_param_visible(group, ident)) {
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
    chip.label = RNA_property_ui_name(prop);

    const PropertyType type = RNA_property_type(prop);
    if (type == PROP_ENUM) {
      chip.kind = MediaChipKind::Enum;
      const int value = RNA_property_enum_get(group, prop);
      const char *label = nullptr;
      if (RNA_property_enum_name_gettexted(const_cast<bContext *>(C), group, prop, value, &label) && label) {
        chip.value = label;
      }
    }
    else if (type == PROP_BOOLEAN) {
      chip.kind = MediaChipKind::Bool;
      chip.bool_value = RNA_property_boolean_get(group, prop);
    }
    else if (type == PROP_INT) {
      chip.kind = MediaChipKind::Int;
      chip.value = std::to_string(RNA_property_int_get(group, prop));
    }
    else {
      /* Floats/strings don't fit a chip strip; the Settings popup remains
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
      return pad * 2.0f + pane_text_width(chip.label.c_str(), font_sub) + 10.0f * u +
             pane_text_width(chip.value.c_str(), font) +
             (2 * ui::mixar_tokens::padding + ui::mixar_tokens::icon) * u;
    case MediaChipKind::Bool:
      /* label [ON OFF] */
      return pad * 2.0f + pane_text_width(chip.label.c_str(), font) + 12.0f * u +
             pane_text_width("ON", font) + pane_text_width("OFF", font) + 44.0f * u;
    case MediaChipKind::Int:
      /* Caption + native numeric field, with room for drag arrows and typing.
       */
      return pad * 2.0f + pane_text_width(chip.label.c_str(), font_sub) + 10.0f * u +
             pane_text_width(chip.value.c_str(), font) + 64.0f * u;
  }
  return 0.0f;
}

void media_param_chip_control(ui::Block *block,
                              const MediaParamChip &chip,
                              PointerRNA *owner,
                              const char *data_path,
                              const float u)
{
  using namespace ui::mixar_tokens;
  const ui::MixarTextStyle body_style = ui::mixar_text_style(ui::MixarTextRole::Body, u);
  const ui::MixarTextStyle caption_style = ui::mixar_text_style(ui::MixarTextRole::Caption, u);
  rctf control = chip.rect;
  ui::Button *button = nullptr;
  if (chip.kind == MediaChipKind::Bool) {
    button = uiDefButO(block,
                       ui::ButtonType::But,
                       "wm.context_toggle",
                       wm::OpCallContext::InvokeDefault,
                       chip.label.c_str(),
                       int(control.xmin),
                       int(control.ymin),
                       short(BLI_rctf_size_x(&control)),
                       short(BLI_rctf_size_y(&control)),
                       nullptr);
    ui::mixar_style_button(button, ui::MixarComponent::Toggle, ui::MixarVariant::Primary, u);
    ui::mixar_button_lit_set(button, chip.bool_value);
  }
  else {
    /* Caption and value are a composite: the caption is decorative, while
     * the value has one native rectangle for paint, editing and QA. */
    ui::mixar_fill_round(chip.rect, radius * u, zen.control);
    const float value_min = (chip.kind == MediaChipKind::Int ? 64.0f : 100.0f) * u;
    const float value_width = std::max(value_min, std::min(
        ui::mixar_text_width(chip.value.c_str(), body_style) + (2 * padding + icon) * u,
        BLI_rctf_size_x(&control) * 0.6f));
    const float caption_width = std::min(
        ui::mixar_text_width(chip.label.c_str(), caption_style),
        std::max(0.0f, BLI_rctf_size_x(&control) - (padding + 10) * u - value_width));
    const std::string caption = ui::mixar_fit_text(chip.label.c_str(), caption_width, caption_style);
    ui::mixar_label_left(caption.c_str(), control.xmin + padding * u,
                        BLI_rctf_cent_y(&control), caption_style, zen.secondary);
    control.xmin += padding * u + caption_width + 10 * u;
    if (chip.kind == MediaChipKind::Enum) {
      button = uiDefButO(block,
                         ui::ButtonType::But,
                         "wm.context_menu_enum",
                         wm::OpCallContext::InvokeDefault,
                         chip.value.c_str(),
                         int(control.xmin),
                         int(control.ymin),
                         short(BLI_rctf_size_x(&control)),
                         short(BLI_rctf_size_y(&control)),
                         nullptr);
      ui::mixar_style_button(button, ui::MixarComponent::Dropdown, ui::MixarVariant::Primary, u);
    }
    else {
      button = uiDefButR(block,
                         ui::ButtonType::Num,
                         "",
                         int(control.xmin),
                         int(control.ymin + 4 * u),
                         short(BLI_rctf_size_x(&control) - 4 * u),
                         short(BLI_rctf_size_y(&control) - 8 * u),
                         owner,
                         chip.prop_id,
                         -1,
                         0.0f,
                         0.0f,
                         nullptr);
      ui::mixar_style_button(button, ui::MixarComponent::Number, ui::MixarVariant::Primary, u);
    }
  }
  if (button) {
    const std::string tip = chip.label + (chip.value.empty() ? "" : ": " + chip.value);
    ui::mixar_button_tooltip_owned(button, tip.c_str());
    if (chip.kind != MediaChipKind::Int) {
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(button);
      RNA_string_set(op_ptr, "data_path", data_path);
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
