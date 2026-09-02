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

struct rctf;

enum AgentIcon {
  /* Tab strip. Only three tabs carry a mark in the design — Agent, Gaussian
   * Splat and My Generations. 3D and Media are deliberately text-only, so
   * there is no glyph here for them and none should be invented. */
  AGENT_ICON_AGENT = 0, /* Person in a ring. */
  AGENT_ICON_THUMB,     /* Thumbs-up — My Generations. */
  AGENT_ICON_SPLAT,     /* Nine-dot rosette — Gaussian Splat. */

  /* Card header. */
  AGENT_ICON_CLOCK,
  AGENT_ICON_PLUS,

  /* Chip row. */
  AGENT_ICON_IMAGE,
  AGENT_ICON_STAR,
  AGENT_ICON_CHEVRON_DOWN,
  AGENT_ICON_SORT, /* Down + up arrow pair — the generations sort chip. */
  AGENT_ICON_MESH, /* Isometric cube — a 3D asset with no preview yet. */

  AGENT_ICON_COUNT,
};

/**
 * Draw \a icon centred in \a box.
 *
 * \a backdrop is the colour the glyph sits ON. Monoline glyphs are drawn as a
 * filled silhouette punched out by the same silhouette inset by one stroke
 * width — overlapping outlines cannot express a thumbs-up without drawing a
 * seam where the thumb meets the fist, and at 16 px that seam is the whole
 * icon. Pass the exact fill of the pill or chip underneath.
 *
 * Expects `GPU_blend` to already be enabled — the island's draw pass sets it
 * once for the whole surface rather than thrashing state per glyph.
 */
void agent_ui_icon_draw(AgentIcon icon,
                        const rctf *box,
                        const float color[4],
                        const float backdrop[4]);
