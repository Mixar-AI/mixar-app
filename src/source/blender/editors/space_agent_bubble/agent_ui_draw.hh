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

#include "agent_ui_cat_activity.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct AgentIslandLayout;
struct bContext;

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
  /* Background work with the turn itself idle (an open run's workers): lights
   * the same dot without claiming the agent is busy. */
  bool status_active;
  MixieCatActivity cat_activity;
  MixieCatCatch cat_catch;  /* Live flight aim; ignored unless activity is Catching. */
  const void *cat_scene;    /* Reset transient expression when the scene changes. */

  char title[128];
  /* Last USER message, for the minimised pill's preview line. Empty when the
   * conversation has none. */
  char last_prompt[160];          /* Card header — the current session's history title. */
  char input_text[512];           /* Current composer input / recognized scribble text. */
  char sketch_prompt[512];        /* UTF-8 tail of the live draft for the resting pill. */
  const char *placeholder;  /* Drawn only while the input is empty. */
  bool prompt_empty;
  /* The primary button reads Stop instead of Send: busy AND nothing typed.
   * A non-empty composer always sends (an interjection joins the open run). */
  bool stop_visible;
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

  /* Sketch reflects the viewport freeze and DRAFT marks. Handwriting is
   * an independent, explicitly opened prompt input method. */
  bool scribble_available;
  bool scribble_armed;      /* Viewport annotation only. */
  bool handwriting_available;
  bool ink_visible;         /* The chat handwriting canvas is open. */
  int mark_count;           /* DRAFT marks queued for the next message. */
  char mark_intent[32];     /* UI name: Auto detect / Draw to build / Point to edit. */

  /* Voice input (space_mixie_chat/core/voice.py). Absent until Python
   * registers mixie_chat.voice_toggle, which it does only on platforms with a
   * recogniser — so no surface ever draws a dead microphone. */
  bool voice_available;
  char voice_status[32];
  bool voice_listening;     /* A dictation session is up. */
  /* The microphone is recording (status "Listening"): the control reads
   * Stop and shows the live ECG trace. False while permission is pending or
   * the transcript is finishing — clicking then cancels, not stops. */
  bool voice_capturing;
  float voice_level;        /* Smoothed input level 0..1 while capturing. */

  /* Auto mode (scene.mixie_chat_auto_mode, space_mixie_chat/ui/properties/
   * chat_props.py). While set, every send carries `auto_mode: true` and the
   * agent decides open choices itself instead of asking. The composer chip's
   * switch thumb sits on the ON side. */
  bool auto_mode;

  /* Hosted agent model pick, mirrored onto the WindowManager by the Python
   * half (byok). `model_available` is false until those properties are
   * registered — the chip is then not laid out or drawn at all, rather than
   * offering a menu that does not exist yet. `model_byok_active` means the
   * user's own API key overrides the hosted pick, so the chip is inert. */
  bool model_available;
  bool model_byok_active;
  char model_label[96];
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
void agent_ui_draw_handwriting_control(ARegion *region, const AgentIslandLayout *layout,
                                       const AgentIslandState *state);
void agent_ui_draw_chip_row(ARegion *region, const AgentIslandLayout *layout, const AgentIslandState *state);

/** Translucent moodboard dot grid overlay covering the normal text input field during scribble. */

}  // namespace blender
