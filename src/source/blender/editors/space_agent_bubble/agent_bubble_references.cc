/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "agent_bubble_references.hh"
#include "../interface/interface_qa_inspect.hh"
#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "ED_space_api.hh"
#include "GPU_state.hh"
#include "RNA_access.hh"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_mixar_text.hh"
#include "WM_api.hh"
#include "WM_types.hh"
#include "agent_ui_draw.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_text.hh"
#include "agent_ui_theme.hh"
#include <algorithm>

namespace blender {
void footer_thumbnails_draw_image(Main *, const char *, int, float, float, float);

int agent_bubble_reference_count(const bContext *C)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return 0;
  }
  PointerRNA ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&ptr, "mixie_chat_pending_attachments");
  return prop ? RNA_property_collection_length(&ptr, prop) : 0;
}

bool agent_bubble_references_visible(const bContext *C)
{
  if (!CTX_wm_area(C) || CTX_wm_area(C)->spacetype != SPACE_AGENT_BUBBLE ||
      ED_agent_bubble_is_resting_pill(C))
  {
    return false;
  }
  AgentIslandState state;
  agent_ui_state_gather(C, &state);
  return state.active_tab == AGENT_TAB_AGENT && !state.ink_visible &&
         agent_bubble_reference_count(C) > 0;
}

float agent_bubble_reference_fraction(wmWindowManager *wm)
{
  PointerRNA ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&ptr, AGENT_REFERENCE_SCROLL);
  return prop ? std::clamp(RNA_property_float_get(&ptr, prop), 0.0f, 1.0f) : 0.0f;
}

AgentReferenceGeometry agent_bubble_reference_geometry(const wmWindow *win,
                                                       const ARegion *region,
                                                       const int count,
                                                       const float fraction)
{
  const float u = float(WM_window_native_pixel_x(win)) / AGENT_ISLAND_W;
  const float width = BLI_rcti_size_x(&region->winrct) + 1;
  const float height = BLI_rcti_size_y(&region->winrct) + 1;
  AgentReferenceGeometry g{};
  g.view = {
      20 * u, width - 28 * u, (AGENT_CARD_PAD_BOTTOM + AGENT_CHIP_H + 16) * u, height - 10 * u};
  g.image_size = std::max(32 * u,
                          0.88f * std::min(BLI_rctf_size_x(&g.view),
                                            BLI_rctf_size_y(&g.view) - 30 * u));
  g.row_pitch = g.image_size + 40 * u;
  g.max_scroll = std::max(0.0f, count * g.row_pitch - 12 * u - BLI_rctf_size_y(&g.view));
  g.offset = std::clamp(fraction, 0.0f, 1.0f) * g.max_scroll;
  g.scrollbar = {width - 16 * u, width - 9 * u, g.view.ymin, g.view.ymax};
  return g;
}

void agent_bubble_references_sync(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  const bool show = agent_bubble_references_visible(C);
  const float u = float(WM_window_native_pixel_x(CTX_wm_window(C))) / AGENT_ISLAND_W;
  for (ARegion &region : area->regionbase) {
    if (region.regiontype != RGN_TYPE_UI) {
      continue;
    }
    const int width = int(AGENT_REFERENCE_COLUMN_W * u / UI_SCALE_FAC + .5f);
    const bool hidden = region.flag & RGN_FLAG_HIDDEN;
    if (hidden == show || (show && region.sizex != width)) {
      SET_FLAG_FROM_TEST(region.flag, !show, RGN_FLAG_HIDDEN);
      region.flag &= ~RGN_FLAG_TOO_SMALL;
      region.sizex = width;
      ED_area_tag_region_size_update(area, &region);
    }
  }
}

void agent_bubble_send_button(const bContext * /*C*/,
                              ARegion *region,
                              ui::Block *block,
                              const AgentIslandLayout &layout,
                              const AgentIslandState &state)
{
  const rctf &r = layout.btn_generate;
  uiDefButO(block,
            ui::ButtonType::But,
            state.status_busy ? "mixie_chat.abort_session" : "mixie_chat.send_message",
            wm::OpCallContext::InvokeDefault,
            "",
            int(r.xmin) - region->winrct.xmin,
            int(r.ymin) - region->winrct.ymin,
            short(BLI_rctf_size_x(&r)),
            short(BLI_rctf_size_y(&r)),
            state.status_busy ? "Stop the running turn" : "Send");
}

namespace {
rctf image_rect(const AgentReferenceGeometry &g, int index)
{
  const float top = g.view.ymax + g.offset - index * g.row_pitch;
  const float x = BLI_rctf_cent_x(&g.view) - g.image_size / 2;
  return {x, x + g.image_size, top - g.image_size, top};
}
}  // namespace

void agent_bubble_references_draw(const bContext *C,
                                  ARegion *region,
                                  const AgentIslandLayout &layout,
                                  const AgentIslandState &state)
{
  const float u = layout.scale;
  wmWindowManager *wm = CTX_wm_manager(C);
  const auto g = agent_bubble_reference_geometry(CTX_wm_window(C),
                                                 region,
                                                 agent_bubble_reference_count(C),
                                                 agent_bubble_reference_fraction(wm));
  ui::Block *block = ui::block_begin(C, region, "agent_references", ui::EmbossType::None);
  agent_bubble_send_button(C, region, block, layout, state);
  /* The same neutral hairline as the My Generations column separators. */
  pane_column_divider(1, g.view.ymin, g.view.ymax, u);
  int old_scissor[4];
  GPU_scissor_get(old_scissor);
  GPU_scissor_test(true);
  GPU_scissor(int(g.view.xmin),
              int(g.view.ymin),
              int(BLI_rctf_size_x(&g.view)),
              int(BLI_rctf_size_y(&g.view)));
  PointerRNA scene = RNA_id_pointer_create(&CTX_data_scene(C)->id);
  int index = 0;
  RNA_BEGIN (&scene, item, "mixie_chat_pending_attachments") {
    const rctf image = image_rect(g, index++);
    if (image.ymin - 28 * u > g.view.ymax || image.ymax < g.view.ymin) {
      continue;
    }
    const std::string path = RNA_string_get(&item, "image_path");
    const std::string name = RNA_string_get(&item, "display_name");
    PropertyRNA *source_prop = RNA_struct_find_property(&item, "image_source");
    const char *source = nullptr;
    RNA_property_enum_identifier(const_cast<bContext *>(C),
                                 &item,
                                 source_prop,
                                 RNA_property_enum_get(&item, source_prop),
                                 &source);
    const float plate[4] = {0.08f, 0.09f, 0.085f, 0.25f};
    GPU_blend(GPU_BLEND_ALPHA);
    pane_fill_round(&image, 10 * u, plate);
    if (source && (STREQ(source, "FILE") || STREQ(source, "BLEND_DATA"))) {
      footer_thumbnails_draw_image(CTX_data_main(C),
                                   path.c_str(),
                                   STREQ(source, "BLEND_DATA"),
                                   image.xmin,
                                   image.ymin,
                                   g.image_size);
    }
    const float dim[4] = AGENT_COL_TEXT_DIM;
    const auto caption = ui::mixar_fit_text(
        name.c_str(),
        g.image_size,
        ui::mixar_text_style(ui::MixarTextRole::Caption, agent_ui_text_unit()));
    GPU_blend(GPU_BLEND_ALPHA);
    pane_label_left(
        caption.c_str(), image.xmin, image.ymin - 16 * u, 15 * agent_ui_text_unit(), dim);
    rctf close = {
        image.xmax - 30 * u, image.xmax - 2 * u, image.ymax - 30 * u, image.ymax - 2 * u};
    if (close.ymin >= g.view.ymin && close.ymax <= g.view.ymax) {
      const float back[4] = {0.055f, 0.065f, 0.06f, 0.90f};
      pane_fill_round(&close, 14 * u, back);
      ui::Button *button = uiDefIconButO(block,
                                         ui::ButtonType::But,
                                         "mixie_chat.remove_attachment",
                                         wm::OpCallContext::ExecDefault,
                                         ICON_X,
                                         int(close.xmin),
                                         int(close.ymin),
                                         int(BLI_rctf_size_x(&close)),
                                         int(BLI_rctf_size_y(&close)),
                                         "Remove reference");
      PointerRNA *props = ui::button_operator_ptr_ensure(button);
      RNA_string_set(props, "attachment_path", path.c_str());
      RNA_string_set(props, "attachment_source", source ? source : "");
      ui::mixar_button_tooltip_owned(button, ("Remove " + name).c_str());
    }
  }
  RNA_END;
  GPU_scissor(UNPACK4(old_scissor));
  GPU_scissor_test(false);
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  if (g.max_scroll > 0 && RNA_struct_find_property(&wm_ptr, AGENT_REFERENCE_SCROLL)) {
    const rctf &r = g.scrollbar;
    ui::block_emboss_set(block, ui::EmbossType::Emboss);
    ui::Button *scroll = uiDefButR(block,
                                   ui::ButtonType::Scroll,
                                   "",
                                   int(r.xmin),
                                   int(r.ymin),
                                   int(BLI_rctf_size_x(&r)),
                                   int(BLI_rctf_size_y(&r)),
                                   &wm_ptr,
                                   AGENT_REFERENCE_SCROLL,
                                   0,
                                   0,
                                   1,
                                   "Scroll references");
    ui::button_scrollbar_visual_height_set(scroll, BLI_rctf_size_y(&g.view) / g.max_scroll);
  }
  ui::block_end(C, block);
  ui::block_draw(C, block);
}

namespace {
void qa_targets(const wmWindow *win,
                const ScrArea *area,
                const ARegion *region,
                std::vector<MixarQATarget> &targets)
{
  if (area->spacetype != SPACE_AGENT_BUBBLE || region->regiontype != RGN_TYPE_UI ||
      (region->flag & (RGN_FLAG_HIDDEN | RGN_FLAG_TOO_SMALL)))
  {
    return;
  }
  PointerRNA scene = RNA_id_pointer_create(&win->scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene, "mixie_chat_pending_attachments");
  if (!prop) {
    return;
  }
  if (!G_MAIN || G_MAIN->wm.is_empty()) {
    return;
  }
  const auto g = agent_bubble_reference_geometry(
      win,
      region,
      RNA_property_collection_length(&scene, prop),
      agent_bubble_reference_fraction(static_cast<wmWindowManager *>(G_MAIN->wm.first)));
  auto append = [&](const char *surface,
                    const std::string &text,
                    const std::string &path,
                    int index,
                    rctf rect) {
    BLI_rctf_translate(&rect, region->winrct.xmin, region->winrct.ymin);
    MixarQATarget target;
    target.surface = surface;
    target.text = text;
    target.value = path;
    target.index = index;
    BLI_rcti_rctf_copy(&target.rect_win, &rect);
    targets.push_back(std::move(target));
  };
  append("reference_column", "Attached references", "", -1, g.view);
  int index = 0;
  RNA_BEGIN (&scene, item, "mixie_chat_pending_attachments") {
    const rctf image = image_rect(g, index);
    rctf visible;
    if (BLI_rctf_isect(&image, &g.view, &visible)) {
      append("reference_preview",
             RNA_string_get(&item, "display_name"),
             RNA_string_get(&item, "image_path"),
             index,
             visible);
    }
    index++;
  }
  RNA_END;
}
}  // namespace

void agent_bubble_references_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, qa_targets);
}
}  // namespace blender
