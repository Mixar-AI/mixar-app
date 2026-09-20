/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Shared internals of the project-rules overlay, split (like the
 * past-chats overlay it is styled after) across:
 *   - mixie_chat_rules_overlay.cc  (panel layout + drawing)
 *   - mixie_chat_rules_events.cc   (text editing, clicks, scroll, cursor)
 *   - mixie_chat_rules_util.cc     (RNA bridge, line wrap, caret math)
 *
 * The panel chrome (card, header, close X, scrim, colors, open animation,
 * smooth scrolling) deliberately reuses the HIST_* constants + helpers
 * from mixie_chat_history_intern.hh so the two overlays read as one
 * design family.
 *
 * Data flows one way from Python (rules_ops.py):
 *   - visibility: WindowManager.mixie_chat_rules_visible
 *   - rule cards: WindowManager.mixie_chat_rule_entries (text + enabled),
 *     the runtime mirror of the scene.mixie_chat_rules JSON store
 *   - edits dispatch mixie_chat.rule_add / rule_update / rule_toggle /
 *     rule_delete (same operator-dispatch pattern as history rows)
 */

#pragma once

#include "BLI_vector.hh"

#include "mixie_chat_history_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct MixieChatRuntime;
struct RulesLineSpan;
struct bContext;
struct wmWindowManager;

/* -------------------------------------------------------------------- */
/** \name Geometry Constants (base px, scaled by UI_SCALE_FAC at draw time)
 * \{ */

/** Composer / in-place editor box: grows with content between these. */
inline constexpr float RULES_EDITOR_MIN_LINES = 2.0f;
inline constexpr float RULES_EDITOR_MAX_LINES = 8.0f;

/** Visual line advance inside editors and rule cards. */
inline constexpr float RULES_LINE_HEIGHT = 20.0f;

/** Inner padding between a rounded box edge and its text. */
inline constexpr float RULES_TEXT_PAD = 10.0f;

/** Submit button (accent pill under the active editor). */
inline constexpr float RULES_SUBMIT_H = 26.0f;

/** Rule card metrics. The left column stacks the enable/disable toggle
 * with the edit (pencil) button under it. */
inline constexpr float RULES_CARD_GAP = 8.0f;
inline constexpr float RULES_CARD_PAD = 10.0f;
inline constexpr float RULES_TEXT_INDENT = 40.0f; /* toggle column width */
inline constexpr float RULES_TOGGLE_W = 26.0f;
inline constexpr float RULES_TOGGLE_H = 14.0f;
inline constexpr float RULES_EDIT_SIZE = 20.0f;
inline constexpr float RULES_EDIT_GAP = 6.0f; /* toggle -> pencil spacing */

/** Scope chip ("Global"/"Project", top-right of each card) + the section
 * headers separating global rules from this file's rules. */
inline constexpr float RULES_SCOPE_CHIP_W = 52.0f;
inline constexpr float RULES_SCOPE_CHIP_H = 17.0f;
inline constexpr float RULES_GROUP_HEADER_H = 22.0f;

/** Scrollable card-list viewport cap. */
inline constexpr float RULES_LIST_MAX_HEIGHT = 300.0f;

/** Muted one-line hint under the list. */
inline constexpr float RULES_FOOTER_HEIGHT = 26.0f;

/** Byte capacity of the runtime edit buffer (incl. terminator). Must stay
 * in lockstep with CHAT_RULES_MAXLEN in the Python constants — the RNA
 * property truncates anything longer. */
inline constexpr int RULES_TEXT_MAX = 10000;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Shared Types + Helpers (mixie_chat_rules_util.cc)
 * \{ */

/** Local snapshot of one rule entry read from the WM mirror. The mirror
 * lists GLOBAL rules first (disk store, every .mixar file), then this
 * file's rules — the unified index the rule operators expect. */
struct RuleDrawEntry {
  char text[2048];
  bool enabled;
  bool is_global;
};

bool mixie_chat_rules_read_visible(wmWindowManager *wm);
void mixie_chat_rules_read_entries(wmWindowManager *wm,
                                   blender::Vector<RuleDrawEntry> &r_items);
void mixie_chat_rules_reset_runtime(MixieChatRuntime *rt);

/** Dispatch a rule operator; `index` < 0 / `text` == nullptr skip that prop. */
void mixie_chat_rules_dispatch_op(
    bContext *C, ARegion *region, const char *op_idname, int index, const char *text);

/** Greedy word wrap of arbitrary text at `wrap_w` px. Returns line count. */
int mixie_chat_rules_wrap_text(const char *text,
                               int font_id,
                               int font_px,
                               float wrap_w,
                               blender::Vector<RulesLineSpan> &r_lines);

/** Rebuild rt->rules_lines for the ACTIVE editor buffer (rt->rules_text)
 * at rt->rules_wrap_w. Returns content height in px (0 before first draw). */
float mixie_chat_rules_relayout(MixieChatRuntime *rt);

/** Index of the wrapped line containing byte offset `cursor`. */
int mixie_chat_rules_line_of_offset(const MixieChatRuntime *rt, int cursor);

/** Caret x (px from the text origin) for `cursor` on its line. */
float mixie_chat_rules_offset_to_x(const MixieChatRuntime *rt, int line, int cursor);

/** Byte offset on `line` closest to x px from the text origin. */
int mixie_chat_rules_x_to_offset(const MixieChatRuntime *rt, int line, float x);

/** Keep the caret line visible inside the editor box (writes
 * rt->rules_editor_scroll; `view_h` is the editor's inner text height). */
void mixie_chat_rules_editor_follow_caret(MixieChatRuntime *rt, float view_h);

/** GPU-line pencil glyph (per-card edit button). */
void rules_draw_edit_glyph(float cx, float cy, float half, const float color[4], float scale);

/** \} */
}  // namespace blender
