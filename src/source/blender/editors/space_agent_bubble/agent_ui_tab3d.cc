/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * 3D tab for the Agent island — the moodboard Model Gen tab, island-styled.
 *
 * Everything is the SAME surface the moodboard N-panel's Model Gen tab
 * drives: `scene.mixie_moodboard_sidebar.tab_image_to_3d` for mode / model /
 * prompt / reference image, the generation_params WindowManager group for
 * the schema params, and the `_MODEL_GEN_FOOTER` operators for Generate.
 * This file only paints island pixels and lays stock-operator uiButs; no new
 * behaviour, no hardcoded model slugs or param names.
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

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_icons.hh"
#include "agent_ui_tab3d.hh"
#include "agent_ui_tab3d_intern.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name Painter helpers (shared with the params file; the island's other
 * panes keep theirs private, so these are duplicated on purpose).
 * \{ */

void t3d_fill_round(const rctf *rect, const float radius, const float col[4])
{
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(rect, true, radius, col);
}

float t3d_text_width(const char *text, const float size)
{
  const int font = BLF_default();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

void t3d_label_left(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  BLF_disable(font, BLF_CLIPPING);

  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;

  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

void t3d_label_centre(
    const char *text, const float cx, const float cy, const float size, const float col[4])
{
  t3d_label_left(text, cx - t3d_text_width(text, size) * 0.5f, cy, size, col);
}

void t3d_fit_text(char *text, const float max_w, const float size)
{
  if (t3d_text_width(text, size) <= max_w) {
    return;
  }
  size_t len = strlen(text);
  while (len > 1) {
    len--;
    while (len > 1 && ((unsigned char)(text[len]) & 0xC0) == 0x80) {
      len--;
    }
    text[len] = '\0';
    if (t3d_text_width(text, size) <= max_w) {
      break;
    }
  }
}

/** \} */

namespace {

/* -------------------------------------------------------------------- */
/** \name Tab state (read-only RNA)
 * \{ */

struct Tab3DState {
  bool tab_ok; /* scene.mixie_moodboard_sidebar.tab_image_to_3d resolved. */
  PointerRNA tab_ptr;

  char mode_id[64];
  char mode_label[64];
  char model_id[64];
  char model_label[64];

  bool use_selected_image;
  char reference_name[64]; /* Image datablock name, "" when unset. */
  bool generating;

  /* Params group for (mode_id, model_id) — engine-registered on WM. */
  bool group_ok;
  PointerRNA group_ptr;
  char group_path[192]; /* "window_manager.<attr>" */
};

void enum_id_and_label(const bContext *C,
                       PointerRNA *ptr,
                       const char *prop_name,
                       char r_id[64],
                       char r_label[64])
{
  r_id[0] = '\0';
  r_label[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, prop_name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return;
  }
  const int value = RNA_property_enum_get(ptr, prop);
  /* These catalog enums are Python-registered with an ITEMS CALLBACK — with a
   * null context the callback cannot run and every lookup comes back empty,
   * which drew the chips as bare em-dashes. Pass the live context. */
  bContext *C_mut = const_cast<bContext *>(C);
  const char *ident = nullptr;
  if (RNA_property_enum_identifier(C_mut, ptr, prop, value, &ident) && ident) {
    BLI_strncpy(r_id, ident, 64);
  }
  const char *label = nullptr;
  if (RNA_property_enum_name_gettexted(C_mut, ptr, prop, value, &label) && label) {
    BLI_strncpy(r_label, label, 64);
  }
}

/** Python's `re.sub(r"\W", "_", s)` — keep byte-identical with engine.py's
 * `_sanitize`, or the computed WM attr misses the registered group. */
void sanitize_key(const char *in, char *out, const int out_len)
{
  int j = 0;
  for (int i = 0; in[i] && j < out_len - 1; i++) {
    const char c = in[i];
    const bool word = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                      (c >= '0' && c <= '9') || c == '_';
    out[j++] = word ? c : '_';
  }
  out[j] = '\0';
}

bool state_gather(const bContext *C, Tab3DState *st)
{
  *st = {};
  Scene *scene = CTX_data_scene(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!scene) {
    return false;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *sidebar_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_sidebar");
  if (!sidebar_prop || RNA_property_type(sidebar_prop) != PROP_POINTER) {
    return false;
  }
  PointerRNA sidebar = RNA_property_pointer_get(&scene_ptr, sidebar_prop);
  PropertyRNA *tab_prop = RNA_struct_find_property(&sidebar, "tab_image_to_3d");
  if (!tab_prop || RNA_property_type(tab_prop) != PROP_POINTER) {
    return false;
  }
  st->tab_ptr = RNA_property_pointer_get(&sidebar, tab_prop);
  if (st->tab_ptr.data == nullptr) {
    return false;
  }
  st->tab_ok = true;

  enum_id_and_label(C, &st->tab_ptr, "mode", st->mode_id, st->mode_label);
  enum_id_and_label(C, &st->tab_ptr, "model", st->model_id, st->model_label);

  if (PropertyRNA *p = RNA_struct_find_property(&st->tab_ptr, "use_selected_image")) {
    st->use_selected_image = RNA_property_boolean_get(&st->tab_ptr, p);
  }
  if (PropertyRNA *p = RNA_struct_find_property(&st->tab_ptr, "reference_image")) {
    PointerRNA image = RNA_property_pointer_get(&st->tab_ptr, p);
    if (image.data) {
      if (PropertyRNA *name_prop = RNA_struct_find_property(&image, "name")) {
        int len = 0;
        char *value = RNA_property_string_get_alloc(
            &image, name_prop, st->reference_name, sizeof(st->reference_name), &len);
        if (value != st->reference_name) {
          BLI_strncpy(st->reference_name, value, sizeof(st->reference_name));
          MEM_freeN(value);
        }
      }
    }
  }

  /* Busy flag — same per-mode scene flags `_MODEL_GEN_FOOTER` names. Reading
   * whichever exists keeps this resilient to a mode the table doesn't know. */
  const char *flag_name = "mixie_image_to_3d_is_generating";
  if (STREQ(st->mode_id, "hunyuan_rapid")) {
    flag_name = "mixie_hunyuan_rapid_is_generating";
  }
  else if (STREQ(st->mode_id, "tripo_smart_segment")) {
    flag_name = "mixie_smart_segment_is_generating";
  }
  if (PropertyRNA *p = RNA_struct_find_property(&scene_ptr, flag_name)) {
    st->generating = RNA_property_boolean_get(&scene_ptr, p);
  }

  /* Schema param group: wm.mixar_genparams_<service>__<slug> (engine.py's
   * _wm_attr). Placeholder enum ids (LOADING/ERROR/NONE) simply fail to
   * resolve and the strip degrades to prompt + Generate. */
  if (wm && st->mode_id[0] && st->model_id[0]) {
    char svc[64], slug[64];
    sanitize_key(st->mode_id, svc, sizeof(svc));
    sanitize_key(st->model_id, slug, sizeof(slug));
    char attr[160];
    SNPRINTF(attr, "mixar_genparams_%s__%s", svc, slug);
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    if (PropertyRNA *p = RNA_struct_find_property(&wm_ptr, attr)) {
      if (RNA_property_type(p) == PROP_POINTER) {
        st->group_ptr = RNA_property_pointer_get(&wm_ptr, p);
        if (st->group_ptr.data) {
          st->group_ok = true;
          SNPRINTF(st->group_path, "window_manager.%s", attr);
        }
      }
    }
  }
  return true;
}

/** \} */

/** Dropdown chip: painted pill + current label + chevron, opening the stock
 * enum menu for \a data_path on click. Returns the chip's advance width. */
float dropdown_chip(const bContext *C,
                    uiBlock *block,
                    const ARegion *region,
                    const char *label_in,
                    const char *data_path,
                    const char *tip,
                    const float x,
                    const float y_top,
                    const float u)
{
  UNUSED_VARS(C, region);
  const float h = AGENT_CHIP_H * u;
  const float pad = T3D_CHIP_PAD_X * u;
  const float font = AGENT_DU(AGENT_CHIP_FONT);
  const float chev = AGENT_DU(AGENT_CHIP_ICON) * 0.8f;

  char label[64];
  BLI_strncpy(label, label_in[0] ? label_in : "—", sizeof(label));
  t3d_fit_text(label, 320.0f * u, font);

  const float w = pad + t3d_text_width(label, font) + 10.0f * u + chev + pad * 0.75f;
  rctf rect = {x, x + w, y_top - h, y_top};

  const float chip_col[4] = T3D_COL_CHIP;
  const float text_col[4] = AGENT_COL_TEXT;
  t3d_fill_round(&rect, AGENT_CHIP_RADIUS * u, chip_col);
  const float cy = BLI_rctf_cent_y(&rect);
  t3d_label_left(label, x + pad, cy, font, text_col);

  rctf chev_box;
  chev_box.xmax = rect.xmax - pad * 0.75f;
  chev_box.xmin = chev_box.xmax - chev;
  chev_box.ymin = cy - chev * 0.5f;
  chev_box.ymax = cy + chev * 0.5f;
  agent_ui_icon_draw(AGENT_ICON_CHEVRON_DOWN, &chev_box, text_col, chip_col);

  uiBut *but = uiDefButO(block, ButType::But, "wm.context_menu_enum",
                         blender::wm::OpCallContext::InvokeDefault, "",
                         int(rect.xmin), int(rect.ymin), short(w), short(h), tip);
  if (but) {
    PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "data_path", data_path);
  }
  return w + T3D_CHIP_GAP * u;
}

}  // namespace

void agent_ui_tab3d_draw(const bContext *C, ARegion *region, const rctf &panel, const float u)
{
  Tab3DState st;
  if (!state_gather(C, &st)) {
    return;
  }

  GPU_blend(GPU_BLEND_ALPHA);

  /* Panel wash — the design's #2D2D2D -> #131413 ramp over the whole panel
   * (vertical here; the diagonal falloff is imperceptible at this delta). */
  {
    const float top[4] = T3D_COL_PANEL_TOP;
    const float bottom[4] = T3D_COL_PANEL_BOTTOM;
    UI_draw_roundbox_corner_set(UI_CNR_ALL);
    UI_draw_roundbox_4fv_ex(
        &panel, bottom, top, 1.0f, nullptr, 0.0f, AGENT_PANEL_RADIUS * u);
  }

  /* Prompt box: top fixed on the design grid, foot following the panel's
   * (the card stretches with the window and the box absorbs the slack). */
  rctf box;
  box.xmin = panel.xmin + (T3D_BOX_X - AGENT_PANEL_X) * u;
  box.xmax = box.xmin + T3D_BOX_W * u;
  box.ymax = panel.ymax - (T3D_BOX_Y - AGENT_PANEL_Y) * u;
  box.ymin = panel.ymin + T3D_BOX_BOTTOM_INSET * u;
  const float box_col[4] = T3D_COL_BOX;
  if (box.ymax > box.ymin + 40.0f * u) {
    t3d_fill_round(&box, T3D_BOX_RADIUS * u, box_col);
  }

  /* Blocks: chips (unembossed ops) + field/sliders (embossed). The field
   * block is begun FIRST so overlapping chip buttons win their clicks. */
  uiBlock *field_block = UI_block_begin(
      C, region, "agent_island_3d_field", blender::ui::EmbossType::Emboss);
  uiBlock *block = UI_block_begin(
      C, region, "agent_island_3d", blender::ui::EmbossType::None);

  /* --- Params strip: Mode + Model dropdowns, then the schema params. --- */
  float x = panel.xmin + (T3D_ROW_X - AGENT_PANEL_X) * u;
  const float row_top = panel.ymax - (T3D_ROW0_Y - AGENT_PANEL_Y) * u;
  const float x_max = panel.xmax - T3D_ROW_X * u * 0.5f;

  x += dropdown_chip(C, block, region, st.mode_label,
                     "scene.mixie_moodboard_sidebar.tab_image_to_3d.mode",
                     "3D generation mode", x, row_top, u);
  x += dropdown_chip(C, block, region, st.model_label,
                     "scene.mixie_moodboard_sidebar.tab_image_to_3d.model",
                     "AI model", x, row_top, u);

  if (st.group_ok) {
    agent_ui_tab3d_params_draw(C, &st.group_ptr, st.group_path, block, field_block,
                               x, row_top, x_max, box.ymax + 8.0f * u, u);
  }

  /* --- Prompt field: the whole box (bottom chips draw over its foot). --- */
  if (box.ymax > box.ymin + 40.0f * u) {
    PropertyRNA *prompt_prop = RNA_struct_find_property(&st.tab_ptr, "prompt");
    if (prompt_prop) {
      uiBut *input = uiDefButR(field_block, ButType::Text, 0, "",
                               int(box.xmin), int(box.ymin),
                               short(BLI_rctf_size_x(&box)), short(BLI_rctf_size_y(&box)),
                               &st.tab_ptr, "prompt", -1, 0.0f, 0.0f, nullptr);
      if (input) {
        UI_but_placeholder_set(input, "Describe your scene here...");
        UI_but_flag2_enable(input, UI_BUT2_ACTIVATE_ON_INIT_NO_SELECT);
        UI_but_flag_enable(input, UI_BUT_TEXTEDIT_UPDATE);
      }
    }
  }

  /* Field chrome must be on screen BEFORE the bottom row is painted — the
   * embossed field spans the whole box, and painting the chips first left
   * them underneath its fill (invisible chips, working ghosts). */
  UI_block_end(C, field_block);
  UI_block_draw(C, field_block);

  /* --- Bottom row inside the box: Upload Reference + Generate. --- */
  const float chip_h = AGENT_CHIP_H * u;
  const float chip_y0 = box.ymin + T3D_CHIP_BOTTOM_INSET * u;
  const float font = AGENT_DU(AGENT_CHIP_FONT);
  const float text_col[4] = AGENT_COL_TEXT;

  {
    /* Upload chip — the tab's OWN picker (sets reference_image and the
     * generate path reads it when use_selected_image is off). Show the
     * picked image's name once one is set. */
    char label[96] = "Upload Reference";
    if (st.reference_name[0] && !st.use_selected_image) {
      BLI_strncpy(label, st.reference_name, sizeof(label));
    }
    t3d_fit_text(label, 260.0f * u, font);
    const float pad = T3D_CHIP_PAD_X * u;
    const float icon_edge = AGENT_DU(AGENT_CHIP_ICON);
    const float w = pad + icon_edge + AGENT_DU(AGENT_CHIP_ICON_GAP) +
                    t3d_text_width(label, font) + pad;
    rctf rect;
    rect.xmin = box.xmin + (T3D_UPLOAD_X - T3D_BOX_X) * u;
    rect.xmax = rect.xmin + w;
    rect.ymin = chip_y0;
    rect.ymax = chip_y0 + chip_h;
    const float chip_col[4] = T3D_COL_UPLOAD;
    t3d_fill_round(&rect, AGENT_CHIP_RADIUS * u, chip_col);
    const float cy = BLI_rctf_cent_y(&rect);
    rctf icon = {rect.xmin + pad, rect.xmin + pad + icon_edge,
                 cy - icon_edge * 0.5f, cy + icon_edge * 0.5f};
    agent_ui_icon_draw(AGENT_ICON_IMAGE, &icon, text_col, chip_col);
    t3d_label_left(label, icon.xmax + AGENT_DU(AGENT_CHIP_ICON_GAP), cy, font, text_col);

    uiDefButO(block, ButType::But, "mixie.image_to_3d_pick_image",
              blender::wm::OpCallContext::InvokeDefault, "",
              int(rect.xmin), int(rect.ymin),
              short(BLI_rctf_size_x(&rect)), short(chip_h),
              "Pick an input image for 3D generation");
  }

  {
    /* Generate — the same footer routing as the moodboard tab: everything
     * submits mixie.model_gen_generate except smart segmentation. Pinned to
     * ui/model_gen_drawer.py's _MODEL_GEN_FOOTER; a new service there needs
     * a row here only if it routes to a THIRD operator. */
    const char *op = STREQ(st.mode_id, "tripo_smart_segment") ?
                         "mixie.smart_segment_generate" :
                         "mixie.model_gen_generate";
    rctf rect;
    rect.xmax = box.xmax - T3D_BOX_BOTTOM_INSET * u * 2.0f;
    rect.xmin = rect.xmax - T3D_GENERATE_W * u;
    rect.ymin = chip_y0;
    rect.ymax = chip_y0 + chip_h;
    const float gen_col[4] = T3D_COL_GENERATE;
    const float strong[4] = AGENT_COL_TEXT_STRONG;
    const float dim[4] = AGENT_COL_TEXT_DIM;
    t3d_fill_round(&rect, AGENT_CHIP_RADIUS * u, gen_col);
    t3d_label_centre(st.generating ? "Working..." : "Generate",
                     BLI_rctf_cent_x(&rect), BLI_rctf_cent_y(&rect), font,
                     st.generating ? dim : strong);
    if (!st.generating) {
      uiDefButO(block, ButType::But, op, blender::wm::OpCallContext::InvokeDefault, "",
                int(rect.xmin), int(rect.ymin),
                short(BLI_rctf_size_x(&rect)), short(chip_h),
                "Generate a 3D model with the selected mode and model");
    }
  }

  GPU_blend(GPU_BLEND_NONE);

  UI_block_end(C, block);
  UI_block_draw(C, block);
}
