/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "agent_bubble_references.hh"
#include "../interface/interface_qa_inspect.hh"
#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_image.hh"
#include "BKE_lib_id.hh"
#include "BKE_report.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "ED_image.hh"
#include "ED_moodboard_attachment.hh"
#include "ED_space_api.hh"
#include "GPU_state.hh"
#include "RNA_access.hh"
#include "RNA_define.hh"
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
  return int(agent_bubble_reference_items(CTX_data_scene(C), CTX_wm_manager(C)).size());
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
  return !state.ink_visible && agent_bubble_reference_count(C) > 0;
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
  /* A draft joins the running turn; Stop is only shown for an empty composer.
   * Both composer regions share the same action and painted state. */
  const rctf &r = layout.btn_generate;
  uiDefButO(block,
            ui::ButtonType::But,
            state.stop_visible ? "mixie_chat.abort_session" : "mixie_chat.send_message",
            wm::OpCallContext::InvokeDefault,
            "",
            int(r.xmin) - region->winrct.xmin,
            int(r.ymin) - region->winrct.ymin,
            short(BLI_rctf_size_x(&r)),
            short(BLI_rctf_size_y(&r)),
            state.stop_visible ? "Stop the running turn" : "Send");
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
  if (state.active_tab == AGENT_TAB_AGENT) {
    agent_bubble_send_button(C, region, block, layout, state);
  }
  /* The same neutral hairline as the Library column separators. */
  pane_column_divider(1, g.view.ymin, g.view.ymax, u);
  int old_scissor[4];
  GPU_scissor_get(old_scissor);
  GPU_scissor_test(true);
  GPU_scissor(int(g.view.xmin),
              int(g.view.ymin),
              int(BLI_rctf_size_x(&g.view)),
              int(BLI_rctf_size_y(&g.view)));
  const auto items = agent_bubble_reference_items(CTX_data_scene(C), wm);
  int index = 0;
  for (const AgentReference &item : items) {
    const rctf image = image_rect(g, index++);
    if (image.ymin - 28 * u > g.view.ymax || image.ymax < g.view.ymin) {
      continue;
    }
    const std::string &path = item.path;
    const std::string &name = item.name;
    const char *source = item.source.c_str();
    const bool generation = state.active_tab != AGENT_TAB_AGENT;
    const float plate[4] = {0.08f, 0.09f, 0.085f, 0.25f};
    GPU_blend(GPU_BLEND_ALPHA);
    pane_fill_round(&image, 10 * u, plate);
    if (generation || STREQ(source, "FILE") || STREQ(source, "BLEND_DATA")) {
      footer_thumbnails_draw_image(CTX_data_main(C),
                                   path.c_str(),
                                   generation || STREQ(source, "BLEND_DATA"),
                                   image.xmin,
                                   image.ymin,
                                   g.image_size);
    }
    rctf visible_image;
    if ((generation || STREQ(source, "BLEND_DATA")) &&
        BLI_rctf_isect(&image, &g.view, &visible_image)) {
      ED_moodboard_attachment_target(C, region, path.c_str(), visible_image);
    }
    MIXAR_THEME_LOAD(dim, TextSecondary);
    const auto caption = ui::mixar_fit_text(
        name.c_str(),
        g.image_size,
        ui::mixar_text_style(ui::MixarTextRole::Caption, agent_ui_text_unit()));
    GPU_blend(GPU_BLEND_ALPHA);
    pane_label_left(
        caption.c_str(), image.xmin, image.ymin - 16 * u, 15 * agent_ui_text_unit(), dim);
    if (item.sketch && BLI_rctf_isect(&image, &g.view, &visible_image)) {
      ui::Button *preview = uiDefButO(block,
                                      ui::ButtonType::But,
                                      "mixar.preview_sketch",
                                      wm::OpCallContext::ExecDefault,
                                      "",
                                      int(visible_image.xmin),
                                      int(visible_image.ymin),
                                      int(BLI_rctf_size_x(&visible_image)),
                                      int(BLI_rctf_size_y(&visible_image)),
                                      "View sketch larger. Add instructions in chat, then Send");
      RNA_string_set(ui::button_operator_ptr_ensure(preview), "image_name", path.c_str());
    }
    rctf close = {
        image.xmax - 30 * u, image.xmax - 2 * u, image.ymax - 30 * u, image.ymax - 2 * u};
    if (close.ymin >= g.view.ymin && close.ymax <= g.view.ymax) {
      const float back[4] = {0.055f, 0.065f, 0.06f, 0.90f};
      pane_fill_round(&close, 14 * u, back);
      ui::Button *button = uiDefIconButO(block,
                                         ui::ButtonType::But,
                                         generation ? "mixar.pane_remove_reference" :
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
      ui::mixar_button_tooltip_owned(
          button, item.sketch ? "Discard this sketch and its queued drawing" : ("Remove " + name).c_str());
    }
  }
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
  if (!G_MAIN || G_MAIN->wm.is_empty()) {
    return;
  }
  wmWindowManager *wm = static_cast<wmWindowManager *>(G_MAIN->wm.first);
  const auto items = agent_bubble_reference_items(win->scene, wm);
  const auto g = agent_bubble_reference_geometry(
      win, region, int(items.size()), agent_bubble_reference_fraction(wm));
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
  for (const AgentReference &item : items) {
    const rctf image = image_rect(g, index);
    rctf visible;
    if (BLI_rctf_isect(&image, &g.view, &visible)) {
      append("reference_preview",
             item.name,
             item.path,
             index,
             visible);
    }
    index++;
  }
}
}  // namespace

void agent_bubble_references_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, qa_targets);
}

static wmOperatorStatus preview_sketch_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  const std::string name = RNA_string_get(op->ptr, "image_name");
  Image *image = reinterpret_cast<Image *>(BKE_libblock_find_name(bmain, ID_IM, name.c_str()));
  if (!image) {
    BKE_report(op->reports, RPT_WARNING, "Sketch preview is unavailable. Draw again to retry");
    return OPERATOR_CANCELLED;
  }
  const rcti rect = {0, 1000, 0, 720};
  if (!WM_window_open(C, "Sketch Preview", &rect, SPACE_IMAGE, false, false, true,
                      WIN_ALIGN_PARENT_CENTER, nullptr, nullptr)) {
    BKE_report(op->reports, RPT_ERROR, "Could not open the sketch preview");
    return OPERATOR_CANCELLED;
  }
  ScrArea *area = CTX_wm_area(C);
  SpaceImage *sima = static_cast<SpaceImage *>(area->spacedata.first);
  ED_space_image_set(bmain, sima, image, false);
  ARegion *region = BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
  CTX_wm_region_set(C, region);
  WM_operator_name_call(C, "IMAGE_OT_view_all", wm::OpCallContext::ExecDefault, nullptr, nullptr);
  ED_area_tag_redraw(area);
  return OPERATOR_FINISHED;
}

void MIXAR_OT_preview_sketch(wmOperatorType *ot)
{
  ot->name = "Preview Sketch";
  ot->idname = "MIXAR_OT_preview_sketch";
  ot->description = "Open the completed drawing in a larger preview. Close it to return to chat";
  ot->exec = preview_sketch_exec;
  ot->poll = ED_operator_screenactive;
  PropertyRNA *prop = RNA_def_string(ot->srna, "image_name", nullptr, 0, "Sketch", "Image to preview");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
}  // namespace blender
