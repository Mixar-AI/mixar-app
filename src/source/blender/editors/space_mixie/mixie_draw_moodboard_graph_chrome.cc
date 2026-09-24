/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Card chrome painters for the moodboard graph.
 *
 * Split out of #mixie_draw_moodboard_graph.cc (500-line rule). Chrome is what
 * a card wears rather than what it contains: affordances the user grabs, drawn
 * in canvas units for resize handles, and screen pixels for readable titles.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BLI_time.h"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "BLF_api.hh"

#include "GPU_immediate_util.hh"

/* The card painters moved here from the graph pass draw roundboxes. */
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"

namespace blender::ed::mixie {

float moodboard_card_corner_radius(View2D *v2d, PointerRNA *node)
{
  const auto metrics = ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC);
  float pixels = metrics.padding;
  if (RNA_struct_find_property(node, "action_type")) {
    if (RNA_pointer_get(node, "preview_image").data ||
        RNA_pointer_get(node, "preview_object").data ||
        RNA_pointer_get(node, "mask_preview").data)
    {
      /* Result content has square corners and a canvas-space inset. */
      return MOODBOARD_GRAPH_PREVIEW_INSET;
    }
    /* Concentric with the settings chip: outer radius = inset + inner radius.
     * Both stay in screen pixels when the board zooms. Asset previews remain
     * square and therefore use the padding alone as their outer radius. */
    pixels += ui::mixar_tokens::radius * UI_SCALE_FAC * 0.65f;
  }
  return pixels / std::max(ui::view2d_scale_get_x(v2d), 0.001f);
}

void moodboard_draw_card_background(const rctf &rect, const bool selected, const float radius)
{
  moodboard_draw_surface(rect, radius);
  /* The running glow below is the "generating" accent; the SELECTED rim is the
   * only other brightening, and both stay here because only the call site
   * knows a node's state. The resting bed and rim live in the token row. */
  if (selected) {
    const float *border = ui::mixar_tokens::mixar_zen().focus;
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv(&rect, false, radius, border);
  }
}

void moodboard_draw_running_glow(const rctf &rect, const float radius)
{
  /* Subtle "generating" pulse while a node is QUEUED/RUNNING: an accent border
   * that breathes in alpha plus a faint outset halo. Kept deliberately dim —
   * never a harsh bright ring. The Python pulse timer
   * (node_job_bridge.ensure_pulse_timer) supplies the continuous redraws; the
   * wall clock supplies the phase (~2.9s breathe). */
  const float pulse = 0.5f + 0.5f * float(std::sin(BLI_time_now_seconds() * 2.2));
  const float *accent = ui::mixar_tokens::mixar_zen().focus;
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  rctf halo = rect;
  halo.xmin -= 3.0f;
  halo.ymin -= 3.0f;
  halo.xmax += 3.0f;
  halo.ymax += 3.0f;
  const float halo_color[4] = {accent[0], accent[1], accent[2], 0.05f + 0.10f * pulse};
  ui::draw_roundbox_4fv(&halo, false, radius + 3.0f, halo_color);
  const float border[4] = {accent[0], accent[1], accent[2], 0.24f + 0.30f * pulse};
  ui::draw_roundbox_4fv(&rect, false, radius, border);
}

void moodboard_draw_node_resize_handles(View2D *v2d, const rctf &rect)
{
  /* The SAME four corner squares a selected reference picture wears, from the
   * one shared painter -- so the gesture looks identical wherever it is
   * offered and the squares cannot drift from the hit-test.
   *
   * Drawn only for a SELECTED card, by the caller: handles are a property of
   * the selection, exactly as they are for a picture. The wedge this replaces
   * was painted on every card, selected or not, and pointed at a resize rule
   * that behaved differently from a picture's. */
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  GPU_blend(GPU_BLEND_ALPHA);
  mixie_draw_moodboard_resize_handles(v2d,
                                      pos,
                                      rect.xmin,
                                      rect.ymin,
                                      BLI_rctf_size_x(&rect),
                                      BLI_rctf_size_y(&rect));
  GPU_blend(GPU_BLEND_NONE);
  immUnbindProgram();
}

/* Screen-space text: zoom changes the card, never its title's font size. */
static void draw_header_text(const char *text,
                             const float x,
                             const float y,
                             const float max_width,
                             const float alpha,
                             const bool right_aligned)
{
  if (!text || text[0] == '\0' || max_width <= 1.0f) {
    return;
  }
  const int font_id = BLF_default();
  const auto style = ui::mixar_text_style(ui::MixarTextRole::Caption, UI_SCALE_FAC);
  const std::string fitted = ui::mixar_fit_text(text, max_width, style);
  text = fitted.c_str();
  const float size = style.size;
  BLF_size(font_id, size);
  BLF_enable(font_id, BLF_CLIPPING);
  const float width = BLF_width(font_id, text, strlen(text));
  const float draw_x = right_aligned ? x - std::min(width, max_width) : x;
  BLF_clipping(font_id, draw_x, y - size, draw_x + max_width, y + size);
  const float *ink = ui::mixar_tokens::mixar_zen().text;
  BLF_color4f(font_id, ink[0], ink[1], ink[2], alpha);
  BLF_position(font_id, draw_x, y, 0.0f);
  BLF_draw(font_id, text, strlen(text));
  BLF_disable(font_id, BLF_CLIPPING);
}

rctf moodboard_node_title_rect(const rctf &card, const float reserved_width)
{
  const auto metrics = ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC);
  const float bottom = card.ymax + MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC;
  return {card.xmin + metrics.padding, card.xmax - metrics.padding - reserved_width,
          bottom, bottom + MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC};
}

void moodboard_draw_card_title(const char *title,
                               const rctf &card,
                               const bool selected,
                               const float reserved_width)
{
  const rctf rect = moodboard_node_title_rect(card, reserved_width);
  if (BLI_rctf_size_x(&rect) <= 0.0f) {
    return;
  }
  draw_header_text(title, rect.xmin, rect.ymin + BLI_rctf_size_y(&rect) * 0.1f,
                   BLI_rctf_size_x(&rect), selected ? 0.98f : 0.82f, false);
}

void moodboard_draw_node_header(PointerRNA *node,
                                const rctf &rect,
                                const bool selected,
                                const float reserved_width)
{
  /* Identity on the left, live state on the right, on the row floating just
   * ABOVE the card -- the same row the Edit/Export icons use, and the same
   * relationship the settings panel has to the card's left edge. Nothing is
   * laid over the card, so a result is never covered and the text is never
   * clipped by the card's own rounded border.
   *
   * The two never collide: the state text only exists while the node is
   * generating, and the icons only once it has finished.
   *
   * Everything here is painted in screen space, independently of canvas zoom. */
  const rctf title_rect = moodboard_node_title_rect(rect);
  const float row_h = BLI_rctf_size_y(&title_rect);
  const float row_y = title_rect.ymin;
  /* A third of the way up the row would optically centre the text. Sitting a
   * little lower than that tucks it toward the card it labels, so it reads as
   * belonging to the card rather than floating midway between it and the
   * canvas. The icons keep the true centre -- they are a target, not a label. */
  const float baseline = row_y + row_h * 0.1f;
  const float left = title_rect.xmin;
  const float right = title_rect.xmax - reserved_width;

  /* State first: the name yields to it, never the other way round. */
  const bool is_action = RNA_struct_find_property(node, "action_type") != nullptr;
  char progress[MIXIE_GRAPH_PROGRESS_BUF] = "";
  if (is_action) {
    mixie_rna_string_get_clamped(node, "progress_text", progress, sizeof(progress));
  }
  float state_width = 0.0f;
  if (progress[0] != '\0') {
    const int font_id = BLF_default();
    BLF_size(font_id, ui::mixar_text_style(ui::MixarTextRole::Caption, UI_SCALE_FAC).size);
    state_width = BLF_width(font_id, progress, strlen(progress)) +
                  MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC;
    draw_header_text(progress, right, baseline, right - left, 0.72f, true);
  }

  /* The user's name if they gave one, otherwise the node type's own label --
   * resolved from the enum so there is no second copy of those names to drift.
   */
  char label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(node, is_action ? "label" : "title", label, sizeof(label));
  const char *title = label;
  if (label[0] == '\0') {
    PropertyRNA *prop = RNA_struct_find_property(node, "action_type");
    const char *name = nullptr;
    if (prop && RNA_property_enum_name(
                    nullptr, node, prop, RNA_property_enum_get(node, prop), &name))
    {
      title = name;
    }
  }
  moodboard_draw_card_title(title, rect, selected, reserved_width + state_width);
}

void moodboard_draw_graph_notice(PointerRNA *scene_ptr)
{
  /* Why the last connection was refused, on the canvas beside the node it was
   * aimed at. `connect_nodes` already produces a specific sentence ("That input
   * socket is already connected", "This model accepts fewer image inputs") --
   * it was just going to the status bar, which is not where the user is looking
   * when they release a noodle. Cleared by a one-shot timer in Python, so this
   * only ever READS. */
  char notice[MIXIE_GRAPH_NOTICE_BUF];
  mixie_rna_string_get_clamped(scene_ptr, "mixie_moodboard_graph_notice",
                               notice, sizeof(notice));
  if (notice[0] == '\0') {
    return;
  }
  const float x = RNA_float_get(scene_ptr, "mixie_moodboard_graph_notice_x");
  const float y = RNA_float_get(scene_ptr, "mixie_moodboard_graph_notice_y");

  const int font_id = BLF_default();
  const float size = 15.0f * UI_SCALE_FAC;
  BLF_size(font_id, size);
  const float text_w = BLF_width(font_id, notice, strlen(notice));
  const float pad = 10.0f * UI_SCALE_FAC;
  const float box_h = size + pad * 2.0f;
  /* Sits above the anchor, which is the target card's top-left, so it never
   * covers the card the message is about. */
  const rctf box = {x, x + text_w + pad * 2.0f, y + pad, y + pad + box_h};

  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  const float background[4] = {0.16f, 0.07f, 0.07f, 0.96f};
  const float border[4] = {0.78f, 0.32f, 0.30f, 0.90f};
  ui::draw_roundbox_4fv(&box, true, 8.0f * UI_SCALE_FAC, background);
  ui::draw_roundbox_4fv(&box, false, 8.0f * UI_SCALE_FAC, border);

  BLF_color4f(font_id, 0.98f, 0.82f, 0.80f, 0.96f);
  BLF_position(font_id, box.xmin + pad, box.ymin + pad * 0.9f, 0.0f);
  BLF_draw(font_id, notice, strlen(notice));
}

}  // namespace blender::ed::mixie
