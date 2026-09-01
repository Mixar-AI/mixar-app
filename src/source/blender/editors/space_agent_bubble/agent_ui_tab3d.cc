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
#include "agent_ui_pane_kit.hh"
#include "agent_ui_tab3d.hh"
#include "agent_ui_tab3d_intern.hh"
#include "agent_ui_theme.hh"

/* Painter primitives come from the pane kit (agent_ui_pane_kit.cc). */

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
  char label[64];
  BLI_strncpy(label, label_in[0] ? label_in : "—", sizeof(label));
  pane_fit_text(label, 320.0f * u, PANE_FONT * u);

  const float w = pane_dropdown_chip_w(label, u);
  const rctf rect = {x, x + w, y_top - PANE_ROW_H * u, y_top};
  pane_dropdown_chip_paint(rect, label, u);

  uiBut *but = uiDefButO(block, ButType::But, "wm.context_menu_enum",
                         blender::wm::OpCallContext::InvokeDefault, "",
                         int(rect.xmin), int(rect.ymin), short(w),
                         short(PANE_ROW_H * u), tip);
  if (but) {
    PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "data_path", data_path);
  }
  return w + PANE_CHIP_GAP * u;
}

}  // namespace

void agent_ui_tab3d_draw(const bContext *C, ARegion *region, const rctf &panel, const float u)
{
  Tab3DState st;
  if (!state_gather(C, &st)) {
    return;
  }

  GPU_blend(GPU_BLEND_ALPHA);

  /* Panel wash — the shared #2D2D2D -> #131413 ramp (pane kit). */
  pane_wash_paint(panel, u);

  /* Blocks: chips (unembossed ops) + field/sliders (embossed). The field
   * block is begun FIRST so overlapping chip buttons win their clicks. */
  uiBlock *field_block = UI_block_begin(
      C, region, "agent_island_3d_field", blender::ui::EmbossType::Emboss);
  uiBlock *block = UI_block_begin(
      C, region, "agent_island_3d", blender::ui::EmbossType::None);

  /* --- Params strip: Mode + Model dropdowns, then the schema params. --- */
  float x = panel.xmin + PANE_INSET_X * u;
  const float row_top = panel.ymax - PANE_STRIP_TOP * u;
  const float x_max = panel.xmax - PANE_INSET_X * u;

  x += dropdown_chip(C, block, region, st.mode_label,
                     "scene.mixie_moodboard_sidebar.tab_image_to_3d.mode",
                     "3D generation mode", x, row_top, u);
  x += dropdown_chip(C, block, region, st.model_label,
                     "scene.mixie_moodboard_sidebar.tab_image_to_3d.model",
                     "AI model", x, row_top, u);

  /* Strip height first, box below it — the kit's prompt-visibility contract:
   * a wrapping strip pushes the box down instead of overlapping it. */
  float strip_bottom = row_top - PANE_ROW_H * u;
  if (st.group_ok) {
    const float params_floor = panel.ymin + (PANE_BOX_MIN_H + PANE_BOX_GAP) * u;
    strip_bottom = std::min(strip_bottom,
                            agent_ui_tab3d_params_draw(C, &st.group_ptr, st.group_path,
                                                       block, field_block,
                                                       x, panel.xmin + PANE_INSET_X * u,
                                                       row_top, x_max, params_floor, u));
  }

  rctf box = pane_prompt_box_rect(panel, strip_bottom, u);
  pane_prompt_box_paint(box, u);

  /* --- Prompt field: the whole box (bottom chips draw over its foot). --- */
  if (box.ymax > box.ymin + PANE_BOX_MIN_H * u) {
    PropertyRNA *prompt_prop = RNA_struct_find_property(&st.tab_ptr, "prompt");
    if (prompt_prop) {
      /* The kit's top strip: ghost text and caret at text scale, never a
       * box-height caret, never a collision with the bottom chips. */
      const rctf field = pane_prompt_field_rect(box, u);
      uiBut *input = uiDefButR(field_block, ButType::Text, 0, "",
                               int(field.xmin), int(field.ymin),
                               short(BLI_rctf_size_x(&field)), short(BLI_rctf_size_y(&field)),
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

  /* --- Bottom row inside the box foot: Upload Reference + Generate. --- */
  const float chip_y0 = pane_bottom_row_ymin(box, u);
  {
    /* Upload chip — the tab's OWN picker (sets reference_image and the
     * generate path reads it when use_selected_image is off). Show the
     * picked image's name once one is set. */
    char label[96] = "Upload Reference";
    if (st.reference_name[0] && !st.use_selected_image) {
      BLI_strncpy(label, st.reference_name, sizeof(label));
    }
    pane_fit_text(label, 260.0f * u, PANE_FONT * u);
    rctf rect;
    rect.xmin = box.xmin + PANE_BOTTOM_IN_L * u;
    rect.xmax = rect.xmin + pane_action_chip_w(label, true, u);
    rect.ymin = chip_y0;
    rect.ymax = chip_y0 + PANE_ROW_H * u;
    pane_action_chip_paint(rect, label, true, false, u);

    uiDefButO(block, ButType::But, "mixie.image_to_3d_pick_image",
              blender::wm::OpCallContext::InvokeDefault, "",
              int(rect.xmin), int(rect.ymin),
              short(BLI_rctf_size_x(&rect)), short(BLI_rctf_size_y(&rect)),
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
    const rctf rect = pane_generate_rect(box, u);
    pane_generate_paint(rect, st.generating ? "Working..." : "Generate", !st.generating, u);
    if (!st.generating) {
      uiDefButO(block, ButType::But, op, blender::wm::OpCallContext::InvokeDefault, "",
                int(rect.xmin), int(rect.ymin),
                short(BLI_rctf_size_x(&rect)), short(BLI_rctf_size_y(&rect)),
                "Generate a 3D model with the selected mode and model");
    }
  }

  GPU_blend(GPU_BLEND_NONE);

  UI_block_end(C, block);
  UI_block_draw(C, block);
}
