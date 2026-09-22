/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Shared, screen-space canvas chrome. Hosts only own placement and clipping. */

#include "mixie_moodboard_chrome.hh"
#include "mixie_moodboard_node_layout.hh"
#include "mixie_moodboard_template_drag.hh"

#include "BKE_screen.hh"
#include "BLF_api.hh"
#include "ED_screen.hh"
#include "UI_interface_layout.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "WM_api.hh"

namespace blender::ed::mixie {

static bool board_has_content(const bContext *C)
{
  PointerRNA ptr = RNA_id_pointer_create(&CTX_data_scene(C)->id);
  /* Same collections as canvas_context.has_moodboard_content. */
  for (const char *name : {"mixie_moodboard_images", "mixie_moodboard_textboxes",
                           "mixie_moodboard_frames", "mixie_moodboard_groups",
                           "mixie_moodboard_action_nodes", "mixie_moodboard_asset_nodes",
                           "mixie_moodboard_links", "mixie_moodboard_annotations"})
  {
    PropertyRNA *prop = RNA_struct_find_property(&ptr, name);
    if (prop && RNA_property_collection_length(&ptr, prop)) {
      return true;
    }
  }
  return false;
}

static void draw_panel(const bContext *C,
                       ARegion *region,
                       const char *panel_id,
                       const int x,
                       const int y,
                       const int width)
{
  PanelType *pt = WM_paneltype_find(panel_id, false);
  if (!pt || width <= 0 || (pt->poll && !pt->poll(C, pt))) {
    return;
  }
  ui::Block *block = ui::block_begin(C, region, panel_id, ui::EmbossType::Emboss);
  /* These blocks are painted last. Their actual bounds, including disabled
   * buttons, must also win over node controls in native hit testing. */
  ui::block_flag_enable(block, ui::BLOCK_CLIP_EVENTS);
  rctf clip;
  const rcti host = moodboard_canvas_host_rect(C);
  BLI_rctf_rcti_copy(&clip, &host);
  const rcti controls = moodboard_canvas_controls_rect(C);
  clip.xmin = std::max(clip.xmin, float(controls.xmin));
  ui::mixar_block_clip_set(block, clip);
  ui::Layout &layout = ui::block_layout(block,
                                        ui::LayoutDirection::Vertical,
                                        ui::LayoutType::Panel,
                                        x, y, width, 0, 0, ui::style_get_dpi());
  /* UILayout.width is not an RNA property. Pass the resolved host budget
   * explicitly; region.width includes the rail and, in the editor, sidebars. */
  layout.context_int_set("moodboard_chrome_width", width);
  layout.context_int_set("moodboard_chrome_font", BLF_default());
  layout.context_int_set("moodboard_chrome_gap", ui::style_get_dpi()->buttonspacex);
  layout.context_int_set("moodboard_chrome_widget_unit", UI_UNIT_X);
  ui::UI_paneltype_draw(const_cast<bContext *>(C), pt, &layout);
  moodboard_template_drag_buttons(C, block);
  ui::block_layout_resolve(block);
  ui::block_bounds_set_normal(block, 0);
  ui::block_end(C, block);
  ui::block_draw(C, block);
}

void mixie_moodboard_chrome_draw(const bContext *C, ARegion *region)
{
  const rcti host = moodboard_canvas_host_rect(C);
  const auto metrics = moodboard_chrome_metrics(UI_SCALE_FAC);
  const int x = host.xmin + int(metrics.padding);
  const int y = host.ymax - int(metrics.padding);
  const int rail = int(metrics.control_height);
  const int templates_x = x + rail + int(metrics.gap);
  const int available = host.xmax - int(metrics.padding) - templates_x;

  ED_region_pixelspace(region);
  if (!board_has_content(C)) {
    const rcti content = moodboard_visible_canvas_rect(C);
    const float width = BLI_rcti_size_x(&content);
    if (width > 40 * UI_SCALE_FAC && BLI_rcti_size_y(&content) > 100 * UI_SCALE_FAC) {
      const auto title = ui::mixar_text_style(ui::MixarTextRole::Heading, UI_SCALE_FAC * 0.75f);
      const auto hint = ui::mixar_text_style(ui::MixarTextRole::Body, UI_SCALE_FAC * 0.75f);
      const bool narrow = width < 240 * UI_SCALE_FAC;
      const std::string label = ui::mixar_fit_text(
          narrow ? "Drop media" : "Start with a reference", width, title);
      BLF_disable(BLF_default(), BLF_CLIPPING);
      ui::mixar_label_center(label.c_str(), BLI_rcti_cent_x(&content),
                            BLI_rcti_cent_y(&content), title, ui::mixar_tokens::mixar_zen().text);
      if (!narrow) {
        const std::string sub = ui::mixar_fit_text(
            "Drop media or choose a node template", width, hint);
        ui::mixar_label_center(sub.c_str(), BLI_rcti_cent_x(&content),
                              BLI_rcti_cent_y(&content) - metrics.control_height,
                              hint, ui::mixar_tokens::mixar_zen().secondary);
      }
      BLF_batch_draw_flush();
    }
  }
  draw_panel(C, region, "MIXIE_PT_canvas_tools", x, y, rail);
  /* One progressive strip: Python draws as many template buttons as fit in
   * `available` and always keeps the + menu. Coarse wide/compact/icon panel
   * switches left blank gaps until the next jump. */
  if (available > 0) {
    draw_panel(C, region, "MIXIE_PT_canvas_templates", templates_x, y, available);
  }
}

}  // namespace blender::ed::mixie
