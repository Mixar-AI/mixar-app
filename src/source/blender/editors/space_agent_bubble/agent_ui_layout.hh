/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Resolved geometry for the Agent island.
 *
 * The artboard measures downward from the island's top-left; Blender regions
 * measure upward from the bottom-left. That flip is applied in exactly one
 * place (`agent_ui_layout_build`) and nowhere else — every consumer reads
 * finished, y-up `rctf`s out of this struct.
 *
 * The painter draws from these rects and the region places its uiButs over
 * exactly the same ones, so a control can never drift from the pixels it sits
 * on. Interaction itself is Blender's — there is deliberately no hand-rolled
 * hit test here to fall out of step with the layout.
 */

#pragma once

#include "BLI_rect.h"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;

/** A tab in the strip. Order is the artboard's, left to right. */
enum AgentTabId {
  AGENT_TAB_AGENT = 0,
  AGENT_TAB_3D,
  AGENT_TAB_MEDIA,
  AGENT_TAB_SPLAT,
  AGENT_TAB_GENERATIONS,
  AGENT_TAB_QUEUE,

  AGENT_TAB_COUNT,
};

struct AgentTabLayout {
  rctf pill;      /* Full pill rect, including the active pill's 1-unit bleed. */
  rctf icon;      /* 24-unit icon box. */
  float label_x;  /* Left edge of the label baseline run. */
  bool active;
};

struct AgentIslandLayout {
  /* True once the region is large enough to hold the island. When false the
   * draw pass bails rather than painting a squashed island — a clipped card reads
   * as a rendering bug, an empty region reads as "too small", which is true. */
  bool valid;

  float scale; /* AGENT_DU(1) — one artboard unit in device pixels. */

  rctf island;
  rctf pill;
  rctf pill_dot;
  float pill_label_x;

  rctf strip;
  AgentTabLayout tabs[AGENT_TAB_COUNT];
  rctf queue_count;
  rctf new_badge;

  /* Gradient axis endpoints in region pixels. The artboard's ramp runs well
   * past the card's bottom edge, so sampling it over the card rect alone
   * would darken the card badly — carry the real axis instead. */
  float card_grad_a[2];
  float card_grad_b[2];

  rctf card;         /* Outer border rect. */
  rctf card_fill;    /* Inset by the border width. */
  rctf card_header;  /* Gradient band above the panel. */
  rctf hdr_history;
  rctf hdr_new_chat;
  rctf hdr_faq;
  float hdr_title_cx;
  float hdr_title_y;

  rctf panel;
  rctf transcript; /* Upper panel — the messages region's slice. */
  rctf input;      /* Input line, just above the chip row. */
  float prompt_x;
  float prompt_y;

  rctf chip_upload;
  rctf btn_generate;
};

/**
 * Resolve the island against `region`, anchored to the region's top-left.
 *
 * `agent_mode_active` is kept in the signature for ABI stability but unused
 * covers; `active_tab` picks the filled pill.
 */
/**
 * Resolve the island against the WINDOW, not a region.
 *
 * The island spans three regions; each one draws this same layout with the
 * matrix translated by its own `winrct` origin, so the region's scissor slices
 * the card rather than any code splitting it. One layout, three views of it.
 */
void agent_ui_layout_build(int window_w,
                           int window_h,
                           AgentTabId active_tab,
                           bool agent_mode_active,
                           bool has_transcript,
                           AgentIslandLayout *r_layout);

}  // namespace blender
