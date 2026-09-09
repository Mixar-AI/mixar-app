/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Card chrome painters for the moodboard graph.
 *
 * Split out of #mixie_draw_moodboard_graph.cc (500-line rule). Chrome is what
 * a card wears rather than what it contains: affordances the user grabs, drawn
 * in canvas units so they line up with the hit-tests in
 * #mixie_moodboard_ops_graph_resize.cc at any zoom.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BLI_time.h"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "BLF_api.hh"

#include "GPU_immediate_util.hh"

/* The card painters moved here from the graph pass draw roundboxes. */
#include "UI_interface_c.hh"

namespace blender::ed::mixie {

void moodboard_draw_card_background(const rctf &rect, const bool selected)
{
  const float background[4] = {0.105f, 0.105f, 0.11f, 0.99f};
  const float border[4] = {0.38f, 0.39f, 0.42f, selected ? 0.92f : 0.58f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, true, 22.0f, background);
  UI_draw_roundbox_4fv(&rect, false, 22.0f, border);
}

void moodboard_draw_running_glow(const rctf &rect)
{
  /* Subtle "generating" pulse while a node is QUEUED/RUNNING: an accent border
   * that breathes in alpha plus a faint outset halo. Kept deliberately dim —
   * never a harsh bright ring. The Python pulse timer
   * (node_job_bridge.ensure_pulse_timer) supplies the continuous redraws; the
   * wall clock supplies the phase (~2.9s breathe). */
  const float pulse = 0.5f + 0.5f * float(std::sin(BLI_time_now_seconds() * 2.2));
  const float accent[3] = {0.32f, 0.72f, 0.55f}; /* muted Mixar green */
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  rctf halo = rect;
  halo.xmin -= 3.0f;
  halo.ymin -= 3.0f;
  halo.xmax += 3.0f;
  halo.ymax += 3.0f;
  const float halo_color[4] = {accent[0], accent[1], accent[2], 0.05f + 0.10f * pulse};
  UI_draw_roundbox_4fv(&halo, false, 25.0f, halo_color);
  const float border[4] = {accent[0], accent[1], accent[2], 0.24f + 0.30f * pulse};
  UI_draw_roundbox_4fv(&rect, false, 22.0f, border);
}

void moodboard_draw_node_resize_grip(const rctf &rect, const bool selected)
{
  /* A quiet corner wedge, the same idea as an image tile's resize handle. Its
   * size is MOODBOARD_NODE_RESIZE_GRIP in CANVAS units — the identical box the
   * grip hit-test uses — so the pixels the user aims at and the region that
   * responds can never drift apart. */
  const float grip = MOODBOARD_NODE_RESIZE_GRIP;
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.55f, 0.56f, 0.60f, selected ? 0.95f : 0.5f);
  immBegin(GPU_PRIM_TRIS, 3);
  immVertex2f(pos, rect.xmax - grip, rect.ymin);
  immVertex2f(pos, rect.xmax, rect.ymin);
  immVertex2f(pos, rect.xmax, rect.ymin + grip);
  immEnd();
  immUnbindProgram();
}

/* One line of header text, clipped to `max_width` so a long name can never run
 * into the state on the other side. Canvas units; BLF is given the size the
 * caller wants and the view matrix does the rest. */
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
  BLF_size(font_id, 15.0f * UI_SCALE_FAC);
  BLF_enable(font_id, BLF_CLIPPING);
  const float width = BLF_width(font_id, text, strlen(text));
  const float draw_x = right_aligned ? x - std::min(width, max_width) : x;
  BLF_clipping(font_id, draw_x, y - 20.0f, draw_x + max_width, y + 20.0f);
  BLF_color4f(font_id, 0.90f, 0.91f, 0.94f, alpha);
  BLF_position(font_id, draw_x, y, 0.0f);
  BLF_draw(font_id, text, strlen(text));
  BLF_disable(font_id, BLF_CLIPPING);
}

void moodboard_draw_node_header(PointerRNA *node, const rctf &rect, const bool selected)
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
   * Everything here is PAINTED, never a widget, so the strip stays a reliable
   * drag handle for the card -- its body is covered by the prompt field and
   * Generate, which is what made cards hard to grab. */
  const float row_h = MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC;
  const float row_y = rect.ymax + MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC;
  /* A third of the way up the row would optically centre the text. Sitting a
   * little lower than that tucks it toward the card it labels, so it reads as
   * belonging to the card rather than floating midway between it and the
   * canvas. The icons keep the true centre -- they are a target, not a label. */
  const float baseline = row_y + row_h * 0.1f;
  const float left = rect.xmin;
  const float right = rect.xmax;

  /* State first: the name yields to it, never the other way round. */
  char progress[MIXIE_GRAPH_PROGRESS_BUF];
  mixie_rna_string_get_clamped(node, "progress_text", progress, sizeof(progress));
  float state_width = 0.0f;
  if (progress[0] != '\0') {
    const int font_id = BLF_default();
    BLF_size(font_id, 15.0f * UI_SCALE_FAC);
    state_width = BLF_width(font_id, progress, strlen(progress)) +
                  MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC;
    draw_header_text(progress, right, baseline, right - left, 0.72f, true);
  }

  /* The user's name if they gave one, otherwise the node type's own label --
   * resolved from the enum so there is no second copy of those names to drift.
   */
  char label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(node, "label", label, sizeof(label));
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
  draw_header_text(
      title, left, baseline, std::max(right - left - state_width, 1.0f),
      selected ? 0.98f : 0.82f, false);
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

  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  const float background[4] = {0.16f, 0.07f, 0.07f, 0.96f};
  const float border[4] = {0.78f, 0.32f, 0.30f, 0.90f};
  UI_draw_roundbox_4fv(&box, true, 8.0f * UI_SCALE_FAC, background);
  UI_draw_roundbox_4fv(&box, false, 8.0f * UI_SCALE_FAC, border);

  BLF_color4f(font_id, 0.98f, 0.82f, 0.80f, 0.96f);
  BLF_position(font_id, box.xmin + pad, box.ymin + pad * 0.9f, 0.0f);
  BLF_draw(font_id, notice, strlen(notice));
}

}  // namespace blender::ed::mixie
