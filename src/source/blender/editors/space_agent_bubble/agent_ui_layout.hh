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

#include "agent_ui_chip_fit.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct bContext;
struct AgentIslandState;
struct AgentIslandLayout;
/** Resolve current host geometry without GPU state or window mutations. */
bool agent_bubble_island_layout_get(const bContext *C, AgentIslandState *state, AgentIslandLayout *layout);

/** A tab in the strip. Order is the artboard's, left to right. */
enum AgentTabId {
  AGENT_TAB_AGENT = 0,
  AGENT_TAB_3D,
  AGENT_TAB_IMAGE,
  AGENT_TAB_VIDEO,
  AGENT_TAB_SPLAT,
  AGENT_TAB_GENERATIONS,
  AGENT_TAB_QUEUE,

  AGENT_TAB_COUNT,
};

/** Content starts below session actions only on the Agent tab. */
float agent_ui_panel_top(AgentTabId tab);

/** Shared by text measurement and tab painting. */
const char *agent_ui_tab_label(AgentTabId tab);

struct AgentTabLayout {
  rctf pill;      /* Full pill rect, including the active pill's 1-unit bleed. */
  rctf icon;      /* 24-unit icon box. */
  float label_x;  /* Left edge of the label baseline run. */
  bool active;
};

struct AgentIslandState;

/**
 * How much of the model chip survives the chip row's width budget.
 *
 * The row is budgeted (see #agent_ui_layout_fit_controls): every chip's width
 * is taken out of the span between Upload Reference and Send, and whatever is
 * left is Upload's. The model chip therefore steps DOWN this ladder — and is
 * dropped entirely — before Upload is allowed below its icon-only floor.
 */
enum class AgentModelChipForm {
  Full = 0, /* Icon + model label + chevron. */
  Label,    /* Icon + model label. */
  Icon,     /* Icon alone. */
};

struct AgentIslandLayout {
  /* True once the region is large enough to hold the island. When false the
   * draw pass bails rather than painting a squashed island — a clipped card reads
   * as a rendering bug, an empty region reads as "too small", which is true. */
  bool valid;

  /* Scribble pad: the island is a tall, narrow writing pad. No tab strip is
   * laid out (the painter and the header controls skip it), and the card,
   * panel and composer are re-flowed to the pad's width instead of the
   * artboard's 1310 units. */
  bool pad;

  float scale; /* AGENT_DU(1) — one artboard unit in device pixels. */

  rctf island;
  rctf pill;
  rctf pill_dot;
  float pill_label_x;

  rctf strip;
  AgentTabLayout tabs[AGENT_TAB_COUNT];
  rctf queue_count;
  rctf new_badge;

  rctf card;         /* Outer border rect. */
  rctf card_fill;    /* Inset by the border width — the card bed's own rect. */
  rctf card_header;  /* Gradient band above the panel. */
  rctf hdr_history;
  rctf hdr_new_chat;
  rctf hdr_handwriting; /* Signature disc — explicit handwriting, separate from Sketch. */
  rctf hdr_checkpoints; /* Turn checkpoints — restore an earlier turn. */
  rctf hdr_rules; /* Rules text-document icon, beside Checkpoints. */
  float hdr_title_cx;
  float hdr_title_y;

  rctf panel;
  rctf transcript; /* Upper panel — the messages region's slice. */
  rctf input;      /* Input line, just above the chip row. */
  float prompt_x;
  float prompt_y;

  bool compact_reference;
  rctf chip_upload;
  /* Scribble: toggle, then (only with queued marks) the reading dropdown and
   * the clear X. Always laid out; the painter and the controls skip the two
   * conditional chips, and the attachment thumbnails start after the last one
   * actually shown. */
  rctf chip_scribble;
  /* Voice input, right of Scribble; the caller empties it and closes the gap
   * when no recogniser is registered (agent_bubble_island_begin). */
  rctf chip_voice;
  /* Auto mode switch, right of Voice (closes the gap with it when Voice is
   * absent). Always drawn: the flag is a plain scene property. */
  rctf chip_auto;
  /* Hosted model pick, right of Auto. Empty when the Python half has not
   * registered its WindowManager mirror yet, or when the row is too narrow
   * to carry it without eating Upload Reference. */
  rctf chip_model;
  AgentModelChipForm model_form;
  /* Form each chip was fitted at (#agent_chip_fit): 0 is the full label; a
   * higher index sheds text down to the chip's icon. Painters read this. */
  int chip_form[AGENT_CHIP_SLOT_COUNT];
  rctf chip_reading;
  rctf chip_clear;
  rctf btn_generate;
};

void agent_ui_layout_fit_controls(AgentIslandLayout &layout, const AgentIslandState &state);

/**
 * Resolve the island against `region`, anchored to the region's top-left.
 *
 * `agent_mode_active` is kept in the signature for ABI stability but unused
 * covers; `active_tab` picks the filled pill.
 */
void agent_ui_layout_fit_controls(AgentIslandLayout &layout, const AgentIslandState &state);

/**
 * Resolve the island against the WINDOW, not a region.
 *
 * The island spans three regions; each one draws this same layout with the
 * matrix translated by its own `winrct` origin, so the region's scissor slices
 * the card rather than any code splitting it. One layout, three views of it.
 */
/**
 * `window_w` is the width the island UNIT is derived from (window_w / 1310)
 * and, in the normal layout, also the width everything is laid out across.
 * For the Scribble pad the caller passes the width that yields the island's
 * default-width unit in `window_w` and the pad window's REAL width in
 * `pad_real_w` (0 otherwise): the unit stays the island's, the geometry
 * re-flows to the pad. Keeping the unit line untouched is deliberate — the
 * chrome-scaling contract pins it.
 */
void agent_ui_layout_build(int window_w,
                           int window_h,
                           AgentTabId active_tab,
                           bool agent_mode_active,
                           bool has_transcript,
                           AgentIslandLayout *r_layout,
                           int pad_real_w,
                           int input_lines = 1);

/** Pixel wrap width of the composer field for the given window / pad. */
float agent_ui_composer_wrap_width_px(int window_w, int pad_real_w);

/** Visual wrapped lines in `text`, clamped to 1..AGENT_INPUT_MAX_LINES. */
int agent_ui_composer_visual_lines(const char *text, float wrap_width_px);

/** Artboard-unit height of the post-transcript input strip. */
float agent_ui_composer_strip_h(int visual_lines);

}  // namespace blender
