/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Shared, screen-space canvas chrome. Hosts only own placement and clipping. */

#include "mixie_moodboard_chrome.hh"
#include "mixie_moodboard_first_use.hh"
#include "mixie_moodboard_node_layout.hh"
#include "mixie_moodboard_template_drag.hh"

#include "BKE_screen.hh"
#include "BLF_api.hh"
#include "BLT_translation.hh"
#include "ED_screen.hh"
#include "UI_interface_layout.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "WM_api.hh"

namespace blender::ed::mixie {

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
  draw_panel(C, region, "MIXIE_PT_canvas_tools", x, y, rail);
  /* One progressive strip: Python draws as many template buttons as fit in
   * `available` and always keeps the + menu. Coarse wide/compact/icon panel
   * switches left blank gaps until the next jump. */
  if (available > 0) {
    draw_panel(C, region, "MIXIE_PT_canvas_templates", templates_x, y, available);
  }
  /* Resolve the real shortcut geometry before drawing its first-use cue. */
  moodboard_first_use_draw(C, region);
}

}  // namespace blender::ed::mixie
