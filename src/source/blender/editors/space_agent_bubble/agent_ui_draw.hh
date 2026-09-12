/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Painter for the Agent island.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct AgentIslandLayout;
struct bContext;
enum class MixieCatActivity;

/**
 * Everything the island shows, gathered by the caller before drawing.
 *
 * The painter reads and never queries: a draw callback runs on every mouse
 * move, and the chat's rule is that draw callbacks only read — no property
 * writes, no fetches.
 */
struct AgentIslandState {
  char status_text[64];     /* Status pill label, from the state enum's UI name. */
  bool status_busy;         /* Lights the pill's dot. */
  MixieCatActivity cat_activity;
  const void *cat_scene;    /* Reset transient expression when the scene changes. */

  char title[128];
  /* Last USER message, for the minimised pill's preview line. Empty when the
   * conversation has none. */
  char last_prompt[160];          /* Card header — the current session's history title. */
  char input_text[512];           /* Current composer input / recognized scribble text. */
  const char *placeholder;  /* Drawn only while the input is empty. */
  bool prompt_empty;
  /* A conversation exists, so the panel splits: transcript above, input below.
   * Empty, the input takes the whole panel exactly as the artboard draws it. */
  bool has_transcript;

  int active_tab;           /* AgentTabId. */
  bool agent_mode;          /* False puts the segmented thumb on Generate Mode. */
  int queue_count;          /* Shown in the Queue pill; 0 hides the count chip. */
  /* Credits left, 0..1. The card's border is a meter for it: a full ring at
   * 100%, shortening anticlockwise as credits are spent. -1 means "unknown"
   * (not fetched, or a free account with no allowance) and draws the ring
   * whole, because a border that reads empty would look like a bug. */
  float credits_remaining;
  bool splat_is_new;        /* Draws the NEW badge on the Gaussian Splat tab. */

  /* Scribble (modules/scribble_mark + the chat ink canvas). The composer chip
   * mirrors what the chat and bubble headers show: pressed while EITHER half is
   * up, the DRAFT mark count riding with the next message, and how that ink is
   * read. Absent until Python registers mixar.scribble_toggle. */
  bool scribble_available;
  bool scribble_armed;      /* Viewport freeze up, or the chat ink canvas open. */
  bool ink_visible;         /* The chat handwriting canvas is open. */
  int mark_count;           /* DRAFT marks queued for the next message. */
  char mark_intent[32];     /* UI name of wm.mixar_mark_intent (Auto / Sketch / Marks). */

  /* Voice input (space_mixie_chat/core/voice.py). Absent until Python
   * registers mixie_chat.voice_toggle, which it does only on platforms with a
   * recogniser — so no surface ever draws a dead microphone. */
  bool voice_available;
  bool voice_listening;     /* A dictation session is up. */

};

/** Fill \a r_state from the chat's existing properties. Read-only. */
void agent_ui_state_gather(const bContext *C, AgentIslandState *r_state);

/**
 * Paint the status pill, filling its own window's region.
 *
 * The pill is a separate always-on-top window parented to the bubble, not part
 * of the island: the artboard floats it over the viewport, and the bubble
 * window cannot do that — it composites alpha as opaque, so an in-island pill
 * band showed up as a black bar above the tab strip.
 */
void agent_ui_draw_status_pill(ARegion *region, float width, float height, const AgentIslandState *state);

/** Paint the island. `GPU_blend` is set and restored internally. */
void agent_ui_draw_island(ARegion *region,
                          const AgentIslandLayout *layout,
                          const AgentIslandState *state);

/** Fixed-geometry chrome, with region-owned native interaction feedback. */
void agent_ui_draw_tab_strip(ARegion *region, const AgentIslandLayout *layout, const AgentIslandState *state);
void agent_ui_draw_chip_row(ARegion *region, const AgentIslandLayout *layout, const AgentIslandState *state);

/** Translucent moodboard dot grid overlay covering the normal text input field during scribble. */

}  // namespace blender
