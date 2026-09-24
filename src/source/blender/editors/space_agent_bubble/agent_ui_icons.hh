/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The Agent island's glyph set.
 *
 * Hand-drawn for the same reason the account card draws its own: Blender's
 * stock `ICON_*` set is weighted for toolbars and out-shouts the island's
 * labels at this size. Every glyph is expressed as fractions of its box, so
 * one definition holds at any DPI.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct rctf;

enum AgentIcon {
  /* Category tabs have distinct marks; Library is label-only. */
  AGENT_ICON_AGENT = 0, /* Person in a ring. */
  AGENT_ICON_VIDEO,     /* Video camera. */
  AGENT_ICON_SPLAT,     /* Nine-dot rosette — Gaussian Splat. */

  /* Card header. */
  AGENT_ICON_CLOCK,
  AGENT_ICON_PLUS,
  AGENT_ICON_RESTORE, /* Counter-clockwise arrow arc — turn checkpoints. */
  AGENT_ICON_RULES,   /* Document outline — project/global rules. */
  AGENT_ICON_SIGNATURE, /* Handwritten stroke — the Handwriting control. */

  /* Chip row, and the two tabs the design leaves unmarked. */
  AGENT_ICON_IMAGE, /* Framed picture — Image tab and Upload Reference. */
  AGENT_ICON_STAR,
  AGENT_ICON_CHEVRON_DOWN,
  AGENT_ICON_SORT, /* Down + up arrow pair — the generations sort chip. */
  AGENT_ICON_MESH, /* Isometric cube — a preview-less 3D asset, and the 3D tab. */
  AGENT_ICON_PEN,  /* Stylus at 45° — the Scribble chip. */
  AGENT_ICON_CROSS, /* X — clear the queued marks. */
  AGENT_ICON_MIC,   /* Microphone — the Voice chip. */

  AGENT_ICON_COUNT,
};

void agent_ui_tab_icon_draw(AgentIcon icon, float cx, float cy, float size, const float color[4]);

/** Inset header artwork without reducing the native button's hit rectangle. */
void agent_ui_header_icon_draw(AgentIcon icon,
                               const rctf *button,
                               const float color[4],
                               const float backdrop[4]);

/**
 * Draw \a icon centred in \a box.
 *
 * \a backdrop is the colour the glyph sits ON. Monoline glyphs are drawn as a
 * filled silhouette punched out by the same silhouette inset by one stroke
 * width — overlapping outlines seam where shapes meet, and at 16 px that
 * seam is the whole icon. Pass the exact fill of the pill or chip underneath.
 *
 * Expects `GPU_blend` to already be enabled — the island's draw pass sets it
 * once for the whole surface rather than thrashing state per glyph.
 */
void agent_ui_icon_draw(AgentIcon icon,
                        const rctf *box,
                        const float color[4],
                        const float backdrop[4]);

}  // namespace blender
