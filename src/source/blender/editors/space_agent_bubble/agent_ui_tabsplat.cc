/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Gaussian Splat tab — native controls over catalog state and measured geometry. The pane binds
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
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_tabsplat.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_tabsplat_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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

  /* Shared panel wash (pane kit) — under everything, including the
   * unavailable state, so this tab backdrops like every other pane. */
  pane_wash_paint(panel, u);

  if (!available) {
    /* Fail closed, like the moodboard drawer: message only, no controls —
     * a bundled client must never resurrect a disabled Marble model. */
    const float *dim = ui::mixar_tokens::zen.secondary;
    pane_label_centre("World Labs catalog settings are unavailable",
                       BLI_rctf_cent_x(&panel),
                       BLI_rctf_cent_y(&panel),
                       PANE_FONT * u,
                       dim);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  /* Enum items for the two segmented controls — labels come from the
   * catalog schema, never hardcoded. Schema `visible_if` can hide a track. */
  SplatEnumItem mode_items[SPLAT_ENUM_MAX];
  SplatEnumItem lod_items[SPLAT_ENUM_MAX];
  const bool mode_visible = pane_schema_param_visible(&state.params, "p_mode");
  const bool lod_visible = pane_schema_param_visible(&state.params, "p_lod");
  int mode_count = 0;
  int lod_count = 0;
  if (mode_visible) {
    mode_count = splat_enum_items_get(
        C, &state.params, state.mode_prop, mode_items, SPLAT_ENUM_MAX);
  }
  if (lod_visible) {
    lod_count = splat_enum_items_get(
        C, &state.params, state.lod_prop, lod_items, SPLAT_ENUM_MAX);
  }

  SplatPaneRects rects;
  splat_pane_rects_build(
      panel, u, state.model_label.c_str(), mode_items, mode_count, lod_items, lod_count, &rects);

  splat_pane_paint(C, state, rects, u);

  GPU_blend(GPU_BLEND_NONE);

  /* ---- Controls ---- */
  ui::Block *block = ui::block_begin(
      C, region, "agent_island_splat", blender::ui::EmbossType::None);
  ui::Block *field_block = ui::block_begin(
      C, region, "agent_island_splat_field", blender::ui::EmbossType::Emboss);

  auto rect_args = [](const rctf &r, int *x, int *y, short *w, short *h) {
    *x = int(r.xmin);
    *y = int(r.ymin);
    *w = short(BLI_rctf_size_x(&r));
    *h = short(BLI_rctf_size_y(&r));
  };
  int bx, by;
  short bw, bh;

  pane_settings_button(block, panel.xmax - PANE_INSET_X * u,
                       panel.ymax - PANE_STRIP_TOP * u, u, SPLAT_SERVICE_KEY, state.model_slug);

  /* A compact fallback reads the complete live enum, including choices beyond
   * the segment buffer. Native popup menus own choice navigation and editing. */
  auto dropdown = [&](const rctf &rect, PropertyRNA *prop, const char *caption) {
    if (!splat_rect_is_live(rect)) {
      return;
    }
    const char *value = nullptr;
    RNA_property_enum_name_gettexted(const_cast<bContext *>(C), &state.params, prop,
                                    RNA_property_enum_get(&state.params, prop), &value);
    const std::string label = std::string(caption) + ": " + (value ? value : "—");
    rect_args(rect, &bx, &by, &bw, &bh);
    ui::Button *but = uiDefButO(block, ui::ButtonType::But, "wm.context_menu_enum",
                               wm::OpCallContext::InvokeDefault, label.c_str(),
                               bx, by, bw, bh, nullptr);
    ui::mixar_style_button(but, ui::MixarComponent::Dropdown, ui::MixarVariant::Primary, u);
    if (but) {
      ui::mixar_button_tooltip_owned(but, label.c_str());
      const std::string path = std::string("window_manager.") + state.group_attr + "." +
                               RNA_property_identifier(prop);
      RNA_string_set(ui::button_operator_ptr_ensure(but), "data_path", path.c_str());
    }
  };
  if (rects.mode_dropdown) {
    dropdown(rects.mode_track, state.mode_prop, "Mode");
  }
  if (rects.lod_dropdown) {
    dropdown(rects.lod_track, state.lod_prop, "LOD");
  }

  /* Mode segments (Text / Image) + LOD segments — stock wm.context_set_enum
   * on the generation-params group's own enum attrs. */
  char data_path[256];
  for (int i = 0; i < mode_count && i < rects.mode_count; i++) {
    rect_args(rects.mode_seg[i], &bx, &by, &bw, &bh);
    ui::Button *but = uiDefButO(block,
                                ui::ButtonType::But,
                                "wm.context_set_enum",
                                blender::wm::OpCallContext::InvokeDefault,
                                mode_items[i].label.c_str(),
                                bx,
                                by,
                                bw,
                                bh,
                                nullptr);
    ui::mixar_style_button(but, ui::MixarComponent::Segment, ui::MixarVariant::Primary, u);
    ui::mixar_button_lit_set(but, mode_items[i].active);
    if (but) {
      ui::mixar_button_tooltip_owned(but, mode_items[i].label.c_str());
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      SNPRINTF(data_path, "window_manager.%s.p_mode", state.group_attr);
      RNA_string_set(op_ptr, "data_path", data_path);
      RNA_string_set(op_ptr, "value", mode_items[i].ident.c_str());
    }
  }
  for (int i = 0; i < lod_count && i < rects.lod_count; i++) {
    rect_args(rects.lod_seg[i], &bx, &by, &bw, &bh);
    ui::Button *but = uiDefButO(block,
                                ui::ButtonType::But,
                                "wm.context_set_enum",
                                blender::wm::OpCallContext::InvokeDefault,
                                lod_items[i].label.c_str(),
                                bx,
                                by,
                                bw,
                                bh,
                                nullptr);
    ui::mixar_style_button(but, ui::MixarComponent::Segment, ui::MixarVariant::Primary, u);
    ui::mixar_button_lit_set(but, lod_items[i].active);
    if (but) {
      ui::mixar_button_tooltip_owned(but, lod_items[i].label.c_str());
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      SNPRINTF(data_path, "window_manager.%s.p_lod", state.group_attr);
      RNA_string_set(op_ptr, "data_path", data_path);
      RNA_string_set(op_ptr, "value", lod_items[i].ident.c_str());
    }
  }

  /* Model choices remain supplied by the catalog enum. */
  rect_args(rects.model_chip, &bx, &by, &bw, &bh);
  if (splat_rect_is_live(rects.model_chip)) {
    ui::Button *but = uiDefButO(block,
                                ui::ButtonType::But,
                                "wm.context_menu_enum",
                                blender::wm::OpCallContext::InvokeDefault,
                                state.model_label.empty() ? state.model_slug : state.model_label.c_str(),
                                bx,
                                by,
                                bw,
                                bh,
                                nullptr);
    ui::mixar_style_button(but, ui::MixarComponent::Dropdown, ui::MixarVariant::Primary, u);
    if (but) {
      ui::mixar_button_tooltip_owned(but, state.model_label.c_str());
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "data_path",
                     "scene.mixie_moodboard_sidebar.tab_world_labs.model");
    }
  }

  /* Bottom-row buttons exist only where the row had space for them — an
   * element dropped by splat_pane_rects_build has an empty rect, and wiring
   * one anyway would put an invisible target over Generate. */
  if (state.image_mode) {
    /* Upload — the tab's own picker (writes tab.reference_image and flips
     * use_selected_image off, same as the N-panel). */
    if (splat_rect_is_live(rects.chip_upload)) {
      rect_args(rects.chip_upload, &bx, &by, &bw, &bh);
      ui::Button *but = uiDefIconTextButO(block,
                                          ui::ButtonType::But,
                                          "mixie.world_labs_pick_image",
                                          blender::wm::OpCallContext::InvokeDefault,
                                          ICON_IMAGE_DATA,
                                          "Upload Reference",
                                          bx,
                                          by,
                                          bw,
                                          bh,
                                          "Upload an input image for world generation");
      ui::mixar_style_button(but, ui::MixarComponent::Action, ui::MixarVariant::Secondary, u);
    }

    /* Capture Viewport -> tab.reference_image (use_selected_image off). */
    if (splat_rect_is_live(rects.chip_capture)) {
      rect_args(rects.chip_capture, &bx, &by, &bw, &bh);
      ui::Button *but = uiDefButO(block,
                                  ui::ButtonType::But,
                                  "mixar.pane_capture_viewport",
                                  blender::wm::OpCallContext::InvokeDefault,
                                  "Capture Viewport",
                                  bx,
                                  by,
                                  bw,
                                  bh,
                                  "Screenshot the 3D viewport as the input image");
      ui::mixar_style_button(but, ui::MixarComponent::Action, ui::MixarVariant::Secondary, u);
    }

    /* Moodboard-selection switch. */
    if (splat_rect_is_live(rects.moodboard_switch)) {
      rect_args(rects.moodboard_switch, &bx, &by, &bw, &bh);
      ui::Button *but = uiDefButO(block,
                                  ui::ButtonType::But,
                                  "wm.context_toggle",
                                  blender::wm::OpCallContext::InvokeDefault,
                                  "Use Moodboard",
                                  bx,
                                  by,
                                  bw,
                                  bh,
                                  "Use the image selected on the moodboard");
      ui::mixar_style_button(but, ui::MixarComponent::Toggle, ui::MixarVariant::Primary, u);
      ui::mixar_button_lit_set(but, state.use_selected);
      if (but) {
        PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
        RNA_string_set(op_ptr,
                       "data_path",
                       "scene.mixie_moodboard_sidebar.tab_world_labs.use_selected_image");
      }
    }
  }

  /* Generate and Enter share the owner-based dispatcher. One native button
   * owns both appearance and enabled state. Queue activity is informational. */
  char gen_label[32];
  pane_queue_label(gen_label, sizeof(gen_label), state.active_jobs);
  if (rects.prompt_ok) {
    rect_args(rects.btn_generate, &bx, &by, &bw, &bh);
    ui::Button *but = uiDefButO(block,
                                ui::ButtonType::But,
                                "mixie.moodboard_prompt_generate",
                                blender::wm::OpCallContext::InvokeDefault,
                                gen_label,
                                bx,
                                by,
                                bw,
                                bh,
                                "Generate a 3D world from the prompt or input image");
    ui::mixar_style_button(but, ui::MixarComponent::Action, ui::MixarVariant::Primary, u);
    if (but) {
      PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
      RNA_string_set(op_ptr, "owner_type", RNA_struct_identifier(state.tab.type));
    }
  }

  /* Prompt field — embossed (ui_do_but_TEX ignores plain clicks on an
   * unembossed text button), bound to the tab's own prompt. */
  if (rects.prompt_ok && RNA_struct_find_property(&state.tab, "prompt")) {
    rect_args(rects.prompt_field, &bx, &by, &bw, &bh);
    ui::Button *input_but = uiDefButR(field_block, ui::ButtonType::Text, "", bx, by, bw, bh,
                                 &state.tab, "prompt", -1, 0.0f, 0.0f, nullptr);
    ui::mixar_style_button(input_but, ui::MixarComponent::Input, ui::MixarVariant::Primary, u);
    if (input_but) {
      ui::button_placeholder_set(input_but,
                             state.image_mode ? "Describe your scene here... (optional)" :
                                                "Describe your scene here...");
      ui::button_flag2_enable(input_but, ui::BUT2_ACTIVATE_ON_INIT_NO_SELECT);
      /* TEXTEDIT_UPDATE is not just Enter-to-submit parity — it is one of the
       * multiline text gates (ui_but_is_multiline_text): without it a tall
       * Text button vertically centres its content and draws a rect-height
       * caret (the "giant caret" bug). */
      ui::button_flag_enable(input_but, ui::BUT_TEXTEDIT_UPDATE);
    }
  }

  ui::block_end(C, field_block);
  ui::block_draw(C, field_block);
  ui::block_end(C, block);
  ui::block_draw(C, block);
}

/** \} */

}  // namespace blender
