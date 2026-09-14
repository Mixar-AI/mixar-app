/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Schema-param widgets for the island's 3D tab.
 *
 * The generation catalog owns every param — this file discovers them by
 * ITERATING the engine-registered WindowManager PropertyGroup's RNA (the
 * `p_*` attributes generation_params/core/engine.py builds), so nothing here
 * names a backend param. The design's vocabulary maps by RNA type:
 *
 *   enum, <= 4 items   -> segmented control ("Low Poly | Standard | High Poly")
 *   enum, larger       -> dropdown chip (stock `wm.context_menu_enum`)
 *   boolean            -> ON/OFF chip (stock `wm.context_toggle`)
 *   int / float        -> chip hosting a real embossed NumSlider bound to the
 *                         group property (Blender chrome, exact behaviour)
 *
 * Widgets flow left-to-right and wrap by the design's row pitch, stopping at
 * the prompt box — schema `order` decided the PropertyGroup's declaration
 * order, so priority params land first. Catalog `visible_if` is evaluated
 * from the group's `mixar_visible_if` table; hidden params never consume
 * strip space. Settings remains the full schema surface.
 */

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_mixar.hh"
#include "UI_mixar_layout.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_tab3d_intern.hh"
#include "UI_mixar_tokens.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Turn `p_face_count` into "Face Count" for the chip label. */
void prettify(const char *identifier, char r_out[64])
{
  const char *src = identifier;
  if (STRPREFIX(src, "p_")) {
    src += 2;
  }
  int j = 0;
  bool cap = true;
  for (int i = 0; src[i] && j < 63; i++) {
    char c = src[i];
    if (c == '_') {
      r_out[j++] = ' ';
      cap = true;
      continue;
    }
    if (cap && c >= 'a' && c <= 'z') {
      c = char(c - 'a' + 'A');
    }
    cap = false;
    r_out[j++] = c;
  }
  r_out[j] = '\0';
}

struct Flow : ui::MixarFlow {
  float u;
  const bContext *context;
};

bool flow_place(Flow *f, const float width, rctf *rect)
{
  ui::MixarFlowRect placed;
  if (!f->place(width, placed)) {
    return false;
  }
  *rect = {placed.xmin, placed.xmax, placed.ymin, placed.ymax};
  return true;
}

void draw_enum_dropdown(ui::Block *, PointerRNA *, PropertyRNA *, const char *, Flow *);

void draw_enum_segmented(ui::Block *block,
                         PointerRNA *group_ptr,
                         PropertyRNA *prop,
                         const char *group_path,
                         const EnumPropertyItem *items,
                         const int totitem,
                         Flow *f)
{
  const float u = f->u;
  const float font = PANE_FONT * u;
  const float pad = 30.0f * u;

  float seg_w[8];
  float total = 0.0f;
  for (int i = 0; i < totitem && i < 8; i++) {
    seg_w[i] = pane_text_width(items[i].name, font) + pad;
    total += seg_w[i];
  }
  if (total > f->x_max - f->x0) {
    draw_enum_dropdown(block, group_ptr, prop, group_path, f);
    return;
  }
  rctf track;
  if (!flow_place(f, total, &track)) {
    return;
  }
  const float chip[4] = PANE_COL_CHIP;
  pane_fill_round(&track, PANE_RADIUS * u, chip);

  const int cur = RNA_property_enum_get(group_ptr, prop);
  float x = track.xmin;
  for (int i = 0; i < totitem && i < 8; i++) {
    rctf seg = {x, x + seg_w[i], track.ymin, track.ymax};
    const bool active = (items[i].value == cur);
    ui::Button *but = uiDefButO(block, ui::ButtonType::But, "wm.context_set_enum",
                           blender::wm::OpCallContext::InvokeDefault, items[i].name,
                           int(seg.xmin), int(seg.ymin),
                           short(seg_w[i]), short(BLI_rctf_size_y(&seg)),
                           nullptr);
    ui::mixar_style_button(but, ui::MixarComponent::Segment, ui::MixarVariant::Primary, u);
    ui::mixar_button_lit_set(but, active);
    if (but) {
      pane_but_tooltip_owned(but, items[i].name);
      char path[256];
      SNPRINTF(path, "%s.%s", group_path, RNA_property_identifier(prop));
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", path);
      RNA_string_set(op_ptr, "value", items[i].identifier);
    }
    x += seg_w[i];
  }
}

void draw_enum_dropdown(ui::Block *block,
                        PointerRNA *group_ptr,
                        PropertyRNA *prop,
                        const char *group_path,
                        Flow *f)
{
  const float u = f->u;

  char name[64];
  prettify(RNA_property_identifier(prop), name);
  const int cur = RNA_property_enum_get(group_ptr, prop);
  const char *cur_label = nullptr;
  RNA_property_enum_name_gettexted(const_cast<bContext *>(f->context), group_ptr, prop, cur, &cur_label);

  const std::string label = std::string(name) + ": " + (cur_label ? cur_label : "—");
  const float w = std::min(pane_dropdown_chip_w(label.c_str(), u), 360.0f * u);
  rctf rect;
  if (!flow_place(f, w, &rect)) {
    return;
  }
  ui::Button *but = uiDefButO(block, ui::ButtonType::But, "wm.context_menu_enum",
                         blender::wm::OpCallContext::InvokeDefault, label.c_str(),
                         int(rect.xmin), int(rect.ymin),
                         short(BLI_rctf_size_x(&rect)), short(BLI_rctf_size_y(&rect)), nullptr);
  ui::mixar_style_button(but, ui::MixarComponent::Dropdown, ui::MixarVariant::Primary, u);
  if (but) {
    pane_but_tooltip_owned(but, label.c_str());
    char path[256];
    SNPRINTF(path, "%s.%s", group_path, RNA_property_identifier(prop));
    PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "data_path", path);
  }
}

void draw_boolean_chip(ui::Block *block,
                       PointerRNA *group_ptr,
                       PropertyRNA *prop,
                       const char *group_path,
                       Flow *f)
{
  const float u = f->u;
  const float font = PANE_FONT * u;
  char name[64];
  prettify(RNA_property_identifier(prop), name);
  const bool on = RNA_property_boolean_get(group_ptr, prop);

  const float pad = PANE_CHIP_PAD_X * u;
  const float name_w = pane_text_width(name, font);
  const float on_w = pane_text_width("ON", font) + 20.0f * u;
  const float off_w = pane_text_width("OFF", font) + 20.0f * u;
  const float w = pad + name_w + 12.0f * u + on_w + off_w + pad * 0.5f;

  rctf rect;
  if (!flow_place(f, w, &rect)) {
    return;
  }
  ui::Button *but = uiDefButO(block, ui::ButtonType::But, "wm.context_toggle",
                         blender::wm::OpCallContext::InvokeDefault, name,
                         int(rect.xmin), int(rect.ymin),
                         short(BLI_rctf_size_x(&rect)), short(BLI_rctf_size_y(&rect)), nullptr);
  ui::mixar_style_button(but, ui::MixarComponent::Toggle, ui::MixarVariant::Primary, u);
  ui::mixar_button_lit_set(but, on);
  if (but) {
    pane_but_tooltip_owned(but, name);
    char path[256];
    SNPRINTF(path, "%s.%s", group_path, RNA_property_identifier(prop));
    PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "data_path", path);
  }
}

void draw_number_chip(ui::Block *slider_block,
                      PointerRNA *group_ptr,
                      PropertyRNA *prop,
                      Flow *f)
{
  const float u = f->u;
  const float font = PANE_FONT * u;
  char name[64];
  prettify(RNA_property_identifier(prop), name);

  const float pad = PANE_CHIP_PAD_X * u;
  const float name_w = pane_text_width(name, font);
  const float slider_w = 195.0f * u; /* Design's Face Count slider run. */
  const float w = pad + name_w + 12.0f * u + slider_w + pad * 0.5f;

  rctf rect;
  if (!flow_place(f, w, &rect)) {
    return;
  }
  const float chip[4] = PANE_COL_CHIP;
  const float *text = ui::mixar_tokens::zen.text;
  pane_fill_round(&rect, PANE_RADIUS * u, chip);
  const float fitted_name_w = std::max(0.0f, BLI_rctf_size_x(&rect) - slider_w - pad * 1.5f - 12.0f * u);
  const std::string fitted = ui::mixar_fit_text(name, fitted_name_w + 2.0f, font);
  pane_label_left(fitted.c_str(), rect.xmin + pad, BLI_rctf_cent_y(&rect), font, text);

  /* A REAL slider: Blender's own NumSlider bound to the group property —
   * exact drag/type behaviour, themed chrome inside the chip. */
  const float sx = rect.xmin + pad + std::min(name_w, fitted_name_w) + 12.0f * u;
  ui::Button *number = uiDefButR(slider_block, ui::ButtonType::NumSlider, "",
            int(sx), int(rect.ymin + 4.0f * u),
            short(slider_w), short(BLI_rctf_size_y(&rect) - 8.0f * u),
            group_ptr, RNA_property_identifier(prop), -1, 0.0f, 0.0f, nullptr);
  ui::mixar_style_button(number, ui::MixarComponent::Number, ui::MixarVariant::Primary, u);
}

}  // namespace

float agent_ui_tab3d_params_draw(const bContext *C,
                                PointerRNA *group_ptr,
                                const char *group_path,
                                ui::Block *chips_block,
                                ui::Block *slider_block,
                                const float x0,
                                const float row_start_x,
                                const float y0_top,
                                const float x_max,
                                const float y_floor,
                                const float u)
{
  Flow f = {};
  f.x = x0;
  /* Wrapped rows LEFT-ALIGN at the strip margin. Wrapping to the
   * continuation x (after the Mode/Model dropdowns) indented every second
   * row to mid-strip, which read as centred. */
  f.x0 = row_start_x;
  f.y_top = y0_top;
  f.x_max = x_max;
  f.y_floor = y_floor;
  f.u = u;
  f.context = C;
  f.row_height = PANE_ROW_H * u;
  f.row_pitch = PANE_ROW_PITCH * u;
  f.gap = PANE_CHIP_GAP * u;

  /* Keep the summary above the composer floor. All remaining schema
   * parameters stay reachable through the native Settings popup. */

  RNA_STRUCT_BEGIN (group_ptr, prop) {
    const char *identifier = RNA_property_identifier(prop);
    if (!STRPREFIX(identifier, "p_")) {
      continue; /* rna_type / name / visible_if metadata — not schema params. */
    }
    if (!pane_schema_param_visible(group_ptr, identifier)) {
      continue;
    }
    const PropertyType prop_type = RNA_property_type(prop);
    if (prop_type != PROP_ENUM && prop_type != PROP_BOOLEAN && prop_type != PROP_INT &&
        prop_type != PROP_FLOAT)
    {
      continue; /* No chip vocabulary — see the default case below. */
    }
    if (f.out_of_room) {
      break;
    }
    switch (prop_type) {
      case PROP_ENUM: {
        const EnumPropertyItem *items = nullptr;
        int totitem = 0;
        bool free = false;
        RNA_property_enum_items(
            const_cast<bContext *>(C), group_ptr, prop, &items, &totitem, &free);
        if (items && totitem > 0) {
          if (totitem <= 4) {
            draw_enum_segmented(chips_block, group_ptr, prop, group_path, items, totitem, &f);
          }
          else {
            draw_enum_dropdown(chips_block, group_ptr, prop, group_path, &f);
          }
        }
        if (free && items) {
          MEM_delete(items);
        }
        break;
      }
      case PROP_BOOLEAN:
        draw_boolean_chip(chips_block, group_ptr, prop, group_path, &f);
        break;
      case PROP_INT:
      case PROP_FLOAT:
        draw_number_chip(slider_block, group_ptr, prop, &f);
        break;
      default:
        /* Strings and pointers have no chip vocabulary in the design —
         * the Settings popup remains the surface for those. */
        break;
    }
  }
  RNA_STRUCT_END;

  /* Strip bottom: the lowest row this flow reached, never below the floor the
   * caller reserved for the prompt box (the kit's prompt-visibility
   * contract) — see pane_params_floor. */
  return std::max(f.y_top - PANE_ROW_H * u, y_floor);
}

}  // namespace blender
