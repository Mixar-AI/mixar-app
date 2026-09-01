/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Gaussian Splat tab — state resolution and control layout. The pane binds
 * the SAME properties and operators as the moodboard World Labs tab
 * (`ui/world_labs_drawer.py` / `ui/operators/world_labs_ops.py`): the tab
 * PropertyGroup at `scene.mixie_moodboard_sidebar.tab_world_labs`, the
 * catalog-built generation-params WindowManager group for
 * (`world_labs`, current model), and `mixie.world_labs_generate` /
 * `mixie.world_labs_pick_image`. All geometry was measured from the
 * "gaussian splats" artboard (island origin 267,340) and is expressed
 * relative to the card panel's top-left in artboard units x `u`.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

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
#include "UI_interface_layout.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_tabsplat.hh"
#include "agent_ui_tabsplat_intern.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name State resolution
 * \{ */

namespace {

/** Mirror of generation_params' `_sanitize` (`re.sub(r"\W", "_", name)`). */
void sanitize_ident(const char *in, char *out, const int out_len)
{
  int n = 0;
  for (int i = 0; in[i] != '\0' && n < out_len - 1; i++) {
    const char c = in[i];
    const bool word = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                      (c >= '0' && c <= '9') || (c == '_');
    out[n++] = word ? c : '_';
  }
  out[n] = '\0';
}

bool ident_is_placeholder(const char *ident)
{
  return ident[0] == '\0' || STREQ(ident, "LOADING") || STREQ(ident, "NONE") ||
         STREQ(ident, "ERROR");
}

}  // namespace

bool splat_state_resolve(const bContext *C, SplatTabState *r_state)
{
  *r_state = {};

  Scene *scene = CTX_data_scene(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!scene || !wm) {
    return false;
  }

  /* scene.mixie_moodboard_sidebar.tab_world_labs */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *sidebar_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_sidebar");
  if (!sidebar_prop || RNA_property_type(sidebar_prop) != PROP_POINTER) {
    return false;
  }
  PointerRNA sidebar = RNA_property_pointer_get(&scene_ptr, sidebar_prop);
  PropertyRNA *tab_prop = RNA_struct_find_property(&sidebar, "tab_world_labs");
  if (!tab_prop || RNA_property_type(tab_prop) != PROP_POINTER) {
    return false;
  }
  r_state->tab = RNA_property_pointer_get(&sidebar, tab_prop);
  if (r_state->tab.data == nullptr) {
    return false;
  }

  /* Current model slug — the enum IDENTIFIER is the catalog slug. Dynamic
   * items need the real context. */
  PropertyRNA *model_prop = RNA_struct_find_property(&r_state->tab, "model");
  if (!model_prop || RNA_property_type(model_prop) != PROP_ENUM) {
    return false;
  }
  {
    const int value = RNA_property_enum_get(&r_state->tab, model_prop);
    const char *ident = nullptr;
    if (!RNA_property_enum_identifier(
            const_cast<bContext *>(C), &r_state->tab, model_prop, value, &ident) ||
        !ident || ident_is_placeholder(ident))
    {
      return false;
    }
    BLI_strncpy(r_state->model_slug, ident, sizeof(r_state->model_slug));
    const char *name = nullptr;
    if (RNA_property_enum_name_gettexted(
            const_cast<bContext *>(C), &r_state->tab, model_prop, value, &name) &&
        name)
    {
      BLI_strncpy(r_state->model_label, name, sizeof(r_state->model_label));
    }
  }

  /* WindowManager generation-params group: mixar_genparams_world_labs__<slug>. */
  char slug_sane[128];
  sanitize_ident(r_state->model_slug, slug_sane, sizeof(slug_sane));
  char group_attr[192];
  SNPRINTF(group_attr, "mixar_genparams_world_labs__%s", slug_sane);
  BLI_strncpy(r_state->group_attr, group_attr, sizeof(r_state->group_attr));

  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *group_prop = RNA_struct_find_property(&wm_ptr, group_attr);
  if (!group_prop || RNA_property_type(group_prop) != PROP_POINTER) {
    return false;
  }
  r_state->params = RNA_property_pointer_get(&wm_ptr, group_prop);
  if (r_state->params.data == nullptr) {
    return false;
  }

  /* `mode` and `lod` enums — the drawer fails closed without both. */
  r_state->mode_prop = RNA_struct_find_property(&r_state->params, "p_mode");
  r_state->lod_prop = RNA_struct_find_property(&r_state->params, "p_lod");
  if (!r_state->mode_prop || RNA_property_type(r_state->mode_prop) != PROP_ENUM ||
      !r_state->lod_prop || RNA_property_type(r_state->lod_prop) != PROP_ENUM)
  {
    return false;
  }

  const int mode_value = RNA_property_enum_get(&r_state->params, r_state->mode_prop);
  const char *mode_ident = nullptr;
  if (RNA_property_enum_identifier(const_cast<bContext *>(C),
                                   &r_state->params,
                                   r_state->mode_prop,
                                   mode_value,
                                   &mode_ident) &&
      mode_ident)
  {
    BLI_strncpy(r_state->mode_ident, mode_ident, sizeof(r_state->mode_ident));
  }
  /* The drawer upper-cases before comparing; mirror that tolerance. */
  r_state->image_mode = (r_state->mode_ident[0] == 'i' || r_state->mode_ident[0] == 'I');

  r_state->use_selected = false;
  if (PropertyRNA *use_sel = RNA_struct_find_property(&r_state->tab, "use_selected_image")) {
    r_state->use_selected = RNA_property_boolean_get(&r_state->tab, use_sel);
  }
  return true;
}

int splat_enum_items_get(const bContext *C,
                         PointerRNA *ptr,
                         PropertyRNA *prop,
                         SplatEnumItem *r_items,
                         const int max_items)
{
  const EnumPropertyItem *items = nullptr;
  int totitem = 0;
  bool free = false;
  RNA_property_enum_items(
      const_cast<bContext *>(C), ptr, prop, &items, &totitem, &free);
  int count = 0;
  const int current = RNA_property_enum_get(ptr, prop);
  for (int i = 0; i < totitem && count < max_items; i++) {
    if (items[i].identifier == nullptr || items[i].identifier[0] == '\0') {
      continue; /* separators */
    }
    BLI_strncpy(r_items[count].ident, items[i].identifier, sizeof(r_items[count].ident));
    BLI_strncpy(r_items[count].label,
                items[i].name ? items[i].name : items[i].identifier,
                sizeof(r_items[count].label));
    r_items[count].active = (items[i].value == current);
    count++;
  }
  if (free) {
    MEM_freeN(const_cast<EnumPropertyItem *>(items));
  }
  return count;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Draw
 * \{ */

void agent_ui_tabsplat_draw(const bContext *C,
                            ARegion *region,
                            const rctf &panel,
                            const float u)
{
  SplatTabState state;
  const bool available = splat_state_resolve(C, &state);

  GPU_blend(GPU_BLEND_ALPHA);

  if (!available) {
    /* Fail closed, like the moodboard drawer: message only, no controls —
     * a bundled client must never resurrect a disabled Marble model. */
    const float dim[4] = AGENT_COL_TEXT_DIM;
    splat_label_centre("World Labs catalog settings are unavailable",
                       BLI_rctf_cent_x(&panel),
                       BLI_rctf_cent_y(&panel),
                       AGENT_DU(SPLAT_FONT),
                       dim);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  /* Enum items for the two segmented controls — labels come from the
   * catalog schema, never hardcoded. */
  SplatEnumItem mode_items[SPLAT_ENUM_MAX];
  SplatEnumItem lod_items[SPLAT_ENUM_MAX];
  const int mode_count = splat_enum_items_get(
      C, &state.params, state.mode_prop, mode_items, SPLAT_ENUM_MAX);
  const int lod_count = splat_enum_items_get(
      C, &state.params, state.lod_prop, lod_items, SPLAT_ENUM_MAX);

  SplatPaneRects rects;
  splat_pane_rects_build(panel, u, lod_items, lod_count, &rects);

  splat_pane_paint(C, state, rects, mode_items, mode_count, lod_items, lod_count, u);

  GPU_blend(GPU_BLEND_NONE);

  /* ---- Controls ---- */
  uiBlock *block = UI_block_begin(
      C, region, "agent_island_splat", blender::ui::EmbossType::None);
  uiBlock *field_block = UI_block_begin(
      C, region, "agent_island_splat_field", blender::ui::EmbossType::Emboss);

  auto rect_args = [](const rctf &r, int *x, int *y, short *w, short *h) {
    *x = int(r.xmin);
    *y = int(r.ymin);
    *w = short(BLI_rctf_size_x(&r));
    *h = short(BLI_rctf_size_y(&r));
  };
  int bx, by;
  short bw, bh;

  /* Mode segments (Text / Image) + LOD segments — stock wm.context_set_enum
   * on the generation-params group's own enum attrs. */
  char data_path[256];
  for (int i = 0; i < mode_count && i < 2; i++) {
    rect_args(i == 0 ? rects.mode_text : rects.mode_image, &bx, &by, &bw, &bh);
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_set_enum",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           bx, by, bw, bh, mode_items[i].label);
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      SNPRINTF(data_path, "window_manager.%s.p_mode", state.group_attr);
      RNA_string_set(op_ptr, "data_path", data_path);
      RNA_string_set(op_ptr, "value", mode_items[i].ident);
    }
  }
  for (int i = 0; i < lod_count && i < rects.lod_count; i++) {
    rect_args(rects.lod_seg[i], &bx, &by, &bw, &bh);
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_set_enum",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           bx, by, bw, bh, lod_items[i].label);
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      SNPRINTF(data_path, "window_manager.%s.p_lod", state.group_attr);
      RNA_string_set(op_ptr, "data_path", data_path);
      RNA_string_set(op_ptr, "value", lod_items[i].ident);
    }
  }

  /* Model dropdown: an invisible RNA menu button over the painted chip — the
   * enum's own items build the menu, so the choice list always tracks the
   * catalog. */
  rect_args(rects.model_chip, &bx, &by, &bw, &bh);
  uiDefButR(block, ButType::Menu, 0, "", bx, by, bw, bh,
            &state.tab, "model", -1, 0.0f, 0.0f, nullptr);

  if (state.image_mode) {
    /* Upload — the tab's own picker (writes tab.reference_image and flips
     * use_selected_image off, same as the N-panel). */
    rect_args(rects.chip_upload, &bx, &by, &bw, &bh);
    uiDefButO(block, ButType::But, "mixie.world_labs_pick_image",
              blender::wm::OpCallContext::InvokeDefault, "", bx, by, bw, bh,
              "Upload an input image for world generation");

    /* Moodboard-selection switch. */
    rect_args(rects.moodboard_switch, &bx, &by, &bw, &bh);
    uiBut *but = uiDefButO(block, ButType::But, "wm.context_toggle",
                           blender::wm::OpCallContext::InvokeDefault, "",
                           bx, by, bw, bh,
                           "Use the image selected on the moodboard");
    if (but) {
      PointerRNA *op_ptr = UI_but_operator_ptr_ensure(but);
      RNA_string_set(op_ptr,
                     "data_path",
                     "scene.mixie_moodboard_sidebar.tab_world_labs.use_selected_image");
    }
  }

  /* Generate — the moodboard tab's own operator, prop-less so it reads the
   * sidebar tab exactly like the N-panel footer. */
  rect_args(rects.btn_generate, &bx, &by, &bw, &bh);
  uiDefButO(block, ButType::But, "mixie.world_labs_generate",
            blender::wm::OpCallContext::InvokeDefault, "", bx, by, bw, bh,
            "Generate a 3D world from the prompt or input image");

  /* Prompt field — embossed (ui_do_but_TEX ignores plain clicks on an
   * unembossed text button), bound to the tab's own prompt. */
  if (RNA_struct_find_property(&state.tab, "prompt")) {
    rect_args(rects.prompt_field, &bx, &by, &bw, &bh);
    uiBut *input_but = uiDefButR(field_block, ButType::Text, 0, "", bx, by, bw, bh,
                                 &state.tab, "prompt", -1, 0.0f, 0.0f, nullptr);
    if (input_but) {
      UI_but_placeholder_set(input_but,
                             state.image_mode ? "Describe your scene here... (optional)" :
                                                "Describe your scene here...");
      UI_but_flag2_enable(input_but, UI_BUT2_ACTIVATE_ON_INIT_NO_SELECT);
    }
  }

  UI_block_end(C, field_block);
  UI_block_draw(C, field_block);
  UI_block_end(C, block);
  UI_block_draw(C, block);
}

/** \} */
