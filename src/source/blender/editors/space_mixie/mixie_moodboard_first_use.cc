/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** A non-interactive first-use sketch, never a graph node or an undo step. */
#include "mixie_moodboard_first_use.hh"
#include "mixie_moodboard_node_layout.hh"
#include "../interface/interface_intern.hh"

#include "BKE_screen.hh"
#include "BLI_string.h"
#include "GPU_immediate_util.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "WM_api.hh"

namespace blender::ed::mixie {

struct MoodboardFirstUseLayout {
  rctf node = {}, media = {}, caption = {};
  float2 arrow_start = {}, arrow_end = {};
  std::string title;
  int icon = 0;
  bool ghost = false;
  bool arrow = false;
};

static bool is_first_use(Scene *scene)
{
  PointerRNA ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *started = RNA_struct_find_property(&ptr, "mixie_moodboard_started");
  if (started && RNA_property_boolean_get(&ptr, started)) {
    return false;
  }
  /* Content also hides the guide immediately, before the history timer runs.
   * A cancelled modal preview returns to the guide without recording a use. */
  for (const char *name : {"mixie_moodboard_images", "mixie_moodboard_textboxes",
                           "mixie_moodboard_frames", "mixie_moodboard_groups",
                           "mixie_moodboard_action_nodes", "mixie_moodboard_asset_nodes",
                           "mixie_moodboard_links", "mixie_moodboard_annotations"}) {
    PropertyRNA *prop = RNA_struct_find_property(&ptr, name);
    if (prop && RNA_property_collection_length(&ptr, prop)) {
      return false;
    }
  }
  return true;
}

static bool first_shortcut(ARegion *region, rcti &anchor, std::string &title, int &icon)
{
  if (!region->runtime) {
    return false;
  }
  bool found = false;
  for (const ui::Block &block : region->runtime->uiblocks) {
    if (block.name != "MIXIE_PT_canvas_templates") {
      continue;
    }
    for (const std::unique_ptr<ui::Button> &button : block.buttons_ptrs) {
      if (!button->optype || (button->flag & ui::UI_HIDDEN) ||
          !STREQ(button->optype->idname, "MIXIE_OT_moodboard_add_template")) {
        continue;
      }
      rcti rect;
      ui::button_to_pixelrect(&rect, region, &block, button.get());
      if (!ui::mixar_block_clip_pixelrect(region, &block, &rect) ||
          BLI_rcti_size_x(&rect) <= 0) {
        continue;
      }
      if (!found || rect.xmin < anchor.xmin) {
        anchor = rect;
        title = button->str;
        icon = button->icon;
        found = true;
      }
    }
  }
  return found;
}

static bool moodboard_first_use_layout(Scene *scene, const ScrArea *area, ARegion *region,
                               MoodboardFirstUseLayout &layout)
{
  layout = {};
  if (!scene || !is_first_use(scene)) {
    return false;
  }
  const float s = UI_SCALE_FAC;
  const rcti content = moodboard_visible_canvas_rect(area, region);
  const float width = BLI_rcti_size_x(&content), height = BLI_rcti_size_y(&content);
  if (width < 70 * s || height < 60 * s) {
    return false;
  }
  const float cx = BLI_rcti_cent_x(&content), cy = BLI_rcti_cent_y(&content);
  layout.caption = {float(content.xmin), float(content.xmax), cy - 10 * s, cy + 10 * s};
  rcti anchor;
  if (width < 225 * s || height < 275 * s ||
      !first_shortcut(region, anchor, layout.title, layout.icon)) {
    /* Narrow drawers retain readable copy and the real + menu. */
    return true;
  }
  layout.ghost = true;
  const float top = content.ymax - std::min(110 * s, (height - 195 * s) * 0.5f);
  layout.node = {cx - 100 * s, cx + 100 * s, top - 145 * s, top};
  layout.media = {layout.node.xmin + 14 * s, layout.node.xmax - 14 * s,
                  layout.node.ymin + 14 * s, layout.node.ymax - 43 * s};
  layout.caption = {layout.node.xmin, layout.node.xmax,
                    layout.node.ymin - 33 * s, layout.node.ymin - 11 * s};
  layout.arrow_start = float2(BLI_rcti_cent_x(&anchor), anchor.ymin - 8 * s);
  layout.arrow_end = float2(layout.node.xmin + 8 * s, layout.node.ymax + 8 * s);
  layout.arrow = layout.arrow_start.y > layout.arrow_end.y + 24 * s;
  return true;
}

static void icon(const int id, const float x, const float cy, const float color[4])
{
  const uchar mono[4] = {uchar(color[0] * 255), uchar(color[1] * 255),
                         uchar(color[2] * 255), 255};
  ui::icon_draw_ex(x, cy - 8 * UI_SCALE_FAC, id, 1.0f, color[3], 0, mono, false, nullptr,
                   false, UI_SCALE_FAC);
}

static void dotted_arrow(const MoodboardFirstUseLayout &layout, const float color[4])
{
  const float s = UI_SCALE_FAC;
  const float2 a = layout.arrow_start, d = layout.arrow_end;
  const float2 b(a.x, a.y - 55 * s), c(d.x - 40 * s, d.y + 30 * s);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  float2 previous = a;
  float distance = 0;
  for (int i = 0; i <= 100; i++) {
    const float t = float(i) / 100, u = 1 - t;
    const float2 point = a * (u*u*u) + b * (3*u*u*t) + c * (3*u*t*t) + d * (t*t*t);
    const float2 delta = point - previous;
    distance += std::sqrt(delta.x * delta.x + delta.y * delta.y);
    if (i == 0 || distance >= 5 * s) {
      imm_draw_circle_fill_2d(pos, point.x, point.y, 0.8f * s, 10);
      distance = 0;
    }
    previous = point;
  }
  /* Solid tip keeps the direction legible at every scale. */
  GPU_line_width(1.2f * s);
  immBegin(GPU_PRIM_LINE_STRIP, 3);
  immVertex2f(pos, d.x - 10 * s, d.y + 1 * s);
  immVertex2f(pos, d.x, d.y);
  immVertex2f(pos, d.x - 1 * s, d.y + 10 * s);
  immEnd();
  GPU_line_width(1.0f);
  immUnbindProgram();
}

void moodboard_first_use_draw(const bContext *C, ARegion *region)
{
  MoodboardFirstUseLayout layout;
  if (!moodboard_first_use_layout(CTX_data_scene(C), CTX_wm_area(C), region, layout)) {
    return;
  }
  const float s = UI_SCALE_FAC;
  const auto &theme = ui::mixar_tokens::mixar_zen();
  const auto text = ui::mixar_text_style(ui::MixarTextRole::Body, s * 0.75f);
  const auto caption = ui::mixar_text_style(ui::MixarTextRole::Caption, s * 0.8f);
  float faint[4], stroke[4], ink[4];
  copy_v4_v4(faint, theme.panel); faint[3] = 0.10f;
  copy_v4_v4(stroke, theme.secondary); stroke[3] = 0.4f;
  copy_v4_v4(ink, theme.secondary); ink[3] = 0.95f;
  const GPUBlend previous_blend = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
  BLF_disable(BLF_default(), BLF_CLIPPING);
  if (layout.ghost) {
    if (layout.arrow) {
      dotted_arrow(layout, ink);
    }
    ui::mixar_label_left("Drag to add a node", layout.node.xmin + 14 * s,
                         layout.node.ymax + 24 * s, caption, ink);
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv(&layout.node, true, 12 * s, faint);
    ui::draw_roundbox_4fv(&layout.node, false, 12 * s, stroke);
    ui::draw_roundbox_4fv(&layout.media, false, 7 * s, stroke);
    const float title_y = layout.node.ymax - 23 * s;
    icon(layout.icon, layout.node.xmin + 14 * s, title_y, ink);
    const std::string title = ui::mixar_fit_text(layout.title.c_str(),
                                                BLI_rctf_size_x(&layout.node) - 54 * s, text);
    ui::mixar_label_left(title.c_str(), layout.node.xmin + 38 * s, title_y, text, ink);
    icon(ICON_IMAGE_DATA, BLI_rctf_cent_x(&layout.media) - 8 * s,
         BLI_rctf_cent_y(&layout.media), ink);
  }
  const std::string label = ui::mixar_fit_text("Drop your media",
                                              BLI_rctf_size_x(&layout.caption), text);
  ui::mixar_label_center(label.c_str(), BLI_rctf_cent_x(&layout.caption),
                         BLI_rctf_cent_y(&layout.caption), text, ink);
  BLF_batch_draw_flush();
  GPU_blend(previous_blend);
}

}  // namespace blender::ed::mixie
