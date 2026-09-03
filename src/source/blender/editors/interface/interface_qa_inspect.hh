/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar QA harness: serialize every live UI widget (uiBut) of every window —
 * regular regions, global areas (topbar/statusbar) and screen-level popup
 * regions — to JSON, so external test drivers can target widgets by meaning
 * (operator idname, property, label) instead of guessed pixel coordinates.
 *
 * Read-only introspection over already-built uiBlocks; never mutates UI state.
 * Consumed by ``WindowManager.mixar_qa_ui_dump`` (rna_wm_mixar.cc).
 */

#pragma once

#include <string>
#include <vector>

#include "BLI_rect.h"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct ScrArea;
struct wmWindow;
struct wmWindowManager;

std::string Mixar_ui_qa_inspect_json(const wmWindowManager *wm);

/* -------------------------------------------------------------------- */
/** \name Custom-surface hit targets
 *
 * Custom-drawn Mixar surfaces (chat message buttons, moodboard canvas,
 * Director timeline) own their geometry outside the uiBut system. Each space
 * registers a provider that exports its clickable targets; the inspector
 * merges them into the same widget dump with ``"type": "Custom"`` and a
 * ``"surface"`` tag, so external drivers can target them semantically.
 * Providers must be READ-ONLY over already-computed layout/runtime state.
 * \{ */

struct MixarQATarget {
  /** Stable surface tag, e.g. "chat_action", "moodboard_node", "director_beat". */
  std::string surface;
  /** Human-visible label or stable id (used for text matching). */
  std::string text;
  /** Dispatch value / node id — whatever the click would act on. */
  std::string value;
  /** Secondary id (e.g. socket_id). */
  std::string detail;
  /** Ordinal within its group (star index, beat index, socket index). */
  int index = -1;
  /** WINDOW pixels, origin bottom-left — ready for Window.event_simulate. */
  rcti rect_win = {};
  bool enabled = true;
  /** Active/selected state (e.g. the active sidebar category tab). */
  bool sel = false;
};

using MixarQATargetProvider = void (*)(const wmWindow *win,
                                       const ScrArea *area,
                                       const ARegion *region,
                                       std::vector<MixarQATarget> &r_targets);

/** Register at spacetype-registration time; providers run for every visible
 * region of areas whose ``spacetype`` matches. */
void Mixar_qa_register_target_provider(int spacetype, MixarQATargetProvider fn);

/** \} */

}  // namespace blender
