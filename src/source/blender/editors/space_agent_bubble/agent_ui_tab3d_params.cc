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
 * order, so priority params land first.
 */

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
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_tab3d_intern.hh"
#include "agent_ui_theme.hh"

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

struct Flow {
  float x;
  float y_top; /* Top edge of the current row. */
  float x0;
  float x_max;
  float y_floor;
  float u;
  bool out_of_room;
};

/** Advance the flow by \a w; wrap to the next row when it does not fit. */
bool flow_place(Flow *f, const float w, rctf *r_rect)
{
  if (f->out_of_room) {
    return false;
  }
  const float h = AGENT_CHIP_H * f->u;
  if (f->x + w > f->x_max && f->x > f->x0) {
    f->x = f->x0;
    f->y_top -= PANE_ROW_PITCH * f->u;
  }
  if (f->y_top - h < f->y_floor) {
    f->out_of_room = true;
    return false;
  }
  r_rect->xmin = f->x;
  r_rect->xmax = f->x + w;
  r_rect->ymax = f->y_top;
  r_rect->ymin = f->y_top - h;
  f->x += w + PANE_CHIP_GAP * f->u;
  return true;
}

void draw_enum_segmented(uiBlock *block,
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
  rctf track;
  if (!flow_place(f, total, &track)) {
    return;
  }
  const float chip[4] = PANE_COL_CHIP;
  const float thumb[4] = PANE_COL_PILL;
  const float text[4] = AGENT_COL_TEXT;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  pane_fill_round(&track, AGENT_CHIP_RADIUS * u, chip);

  const int cur = RNA_property_enum_get(group_ptr, prop);
  float x = track.xmin;
  for (int i = 0; i < totitem && i < 8; i++) {
    rctf seg = {x, x + seg_w[i], track.ymin, track.ymax};
    const bool active = (items[i].value == cur);
    if (active) {
      pane_fill_round(&seg, AGENT_CHIP_RADIUS * u, thumb);
    }
    pane_label_centre(items[i].name,
                     BLI_rctf_cent_x(&seg),
                     BLI_rctf_cent_y(&seg),
                     font,
                     active ? text : dim);
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_set_enum",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           int(seg.xmin), int(seg.ymin),
                           short(seg_w[i]), short(BLI_rctf_size_y(&seg)),
                           items[i].name);
    if (but) {
      char path[256];
      SNPRINTF(path, "%s.%s", group_path, RNA_property_identifier(prop));
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path", path);
      RNA_string_set(op_ptr, "value", items[i].identifier);
    }
    x += seg_w[i];
  }
}

void draw_enum_dropdown(uiBlock *block,
                        PointerRNA *group_ptr,
                        PropertyRNA *prop,
                        const char *group_path,
                        Flow *f)
{
  const float u = f->u;
  const float font = PANE_FONT * u;

  char name[64];
  prettify(RNA_property_identifier(prop), name);
  const int cur = RNA_property_enum_get(group_ptr, prop);
  const char *cur_label = nullptr;
  RNA_property_enum_name_gettexted(nullptr, group_ptr, prop, cur, &cur_label);

  char label[128];
  SNPRINTF(label, "%s: %s", name, cur_label ? cur_label : "—");
  pane_fit_text(label, 300.0f * u, font);

  const float w = PANE_CHIP_PAD_X * u * 2.0f + pane_text_width(label, font);
  rctf rect;
  if (!flow_place(f, w, &rect)) {
    return;
  }
  const float chip[4] = PANE_COL_CHIP;
  const float text[4] = AGENT_COL_TEXT;
  pane_fill_round(&rect, AGENT_CHIP_RADIUS * u, chip);
  pane_label_centre(label, BLI_rctf_cent_x(&rect), BLI_rctf_cent_y(&rect), font, text);

  uiBut *but = uiDefButO(block, ButType::But, "wm.context_menu_enum",
                         blender::wm::OpCallContext::InvokeDefault, "",
                         int(rect.xmin), int(rect.ymin),
                         short(w), short(BLI_rctf_size_y(&rect)), name);
  if (but) {
    char path[256];
    SNPRINTF(path, "%s.%s", group_path, RNA_property_identifier(prop));
    PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "data_path", path);
  }
}

void draw_boolean_chip(uiBlock *block,
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
  const float chip[4] = PANE_COL_CHIP;
  const float thumb[4] = PANE_COL_PILL;
  const float text[4] = AGENT_COL_TEXT;
  const float dim[4] = AGENT_COL_TEXT_DIM;
  pane_fill_round(&rect, AGENT_CHIP_RADIUS * u, chip);
  const float cy = BLI_rctf_cent_y(&rect);
  pane_label_left(name, rect.xmin + pad, cy, font, text);

  /* ON / OFF halves, thumb on the live value. */
  const float toggles_x = rect.xmin + pad + name_w + 12.0f * u;
  rctf on_rect = {toggles_x, toggles_x + on_w, rect.ymin + 4.0f * u, rect.ymax - 4.0f * u};
  rctf off_rect = {on_rect.xmax, on_rect.xmax + off_w, on_rect.ymin, on_rect.ymax};
  if (on) {
    pane_fill_round(&on_rect, AGENT_CHIP_RADIUS * u, thumb);
  }
  else {
    pane_fill_round(&off_rect, AGENT_CHIP_RADIUS * u, thumb);
  }
  pane_label_centre("ON", BLI_rctf_cent_x(&on_rect), cy, font, on ? text : dim);
  pane_label_centre("OFF", BLI_rctf_cent_x(&off_rect), cy, font, on ? dim : text);

  uiBut *but = uiDefButO(block, ButType::But, "wm.context_toggle",
                         blender::wm::OpCallContext::InvokeDefault, "",
                         int(rect.xmin), int(rect.ymin),
                         short(w), short(BLI_rctf_size_y(&rect)), name);
  if (but) {
    char path[256];
    SNPRINTF(path, "%s.%s", group_path, RNA_property_identifier(prop));
    PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "data_path", path);
  }
}

void draw_number_chip(uiBlock *slider_block,
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
  const float text[4] = AGENT_COL_TEXT;
  pane_fill_round(&rect, AGENT_CHIP_RADIUS * u, chip);
  pane_label_left(name, rect.xmin + pad, BLI_rctf_cent_y(&rect), font, text);

  /* A REAL slider: Blender's own NumSlider bound to the group property —
   * exact drag/type behaviour, themed chrome inside the chip. */
  const float sx = rect.xmin + pad + name_w + 12.0f * u;
  uiDefButR(slider_block, ButType::NumSlider, 0, "",
            int(sx), int(rect.ymin + 4.0f * u),
            short(slider_w), short(BLI_rctf_size_y(&rect) - 8.0f * u),
            group_ptr, RNA_property_identifier(prop), -1, 0.0f, 0.0f, nullptr);
}

}  // namespace

float agent_ui_tab3d_params_draw(const bContext *C,
                                PointerRNA *group_ptr,
                                const char *group_path,
                                uiBlock *chips_block,
                                uiBlock *slider_block,
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

  RNA_STRUCT_BEGIN (group_ptr, prop) {
    const char *identifier = RNA_property_identifier(prop);
    if (!STRPREFIX(identifier, "p_")) {
      continue; /* rna_type / name — not schema params. */
    }
    if (f.out_of_room) {
      break;
    }
    switch (RNA_property_type(prop)) {
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
          MEM_freeN(const_cast<EnumPropertyItem *>(items));
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
         * the moodboard N-panel remains the surface for those. */
        break;
    }
  }
  RNA_STRUCT_END;

  /* Strip bottom: the lowest row this flow reached (the caller places the
   * prompt box from here — the kit's prompt-visibility contract). */
  return f.y_top - PANE_ROW_H * u;
}
