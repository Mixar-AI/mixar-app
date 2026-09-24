/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Hold-to-dictate for native text fields. Left Option/Alt held alone records; modifier chords keep native behavior.
 * Python owns capture/transport; the live edit buffer owns insertion and undo.
 * No transcript is allowed to outlive its original field or overwrite an edit.
 */
#include "interface_text_dictation.hh"

#include <algorithm>

#include "BKE_context.hh"
#include "BKE_report.hh"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "RNA_access.hh"
#include "RNA_prototypes.hh"
#include "WM_api.hh"
#include "WM_types.hh"
#include "interface_intern.hh"

namespace blender::ui {

static constexpr double HOLD_SECONDS = 0.30;
static constexpr const char *TOKEN = "mixie_chat_voice_field_token";
static constexpr const char *TEXT = "mixie_chat_voice_field_text";
static constexpr const char *READY = "mixie_chat_voice_field_ready";

static PointerRNA manager_pointer(bContext *C)
{
  return RNA_pointer_create_discrete(&CTX_wm_manager(C)->id,
                                     RNA_WindowManager,
                                     CTX_wm_manager(C));
}

static bool matches(bContext *C, const TextDictation &state)
{
  PointerRNA wm = manager_pointer(C);
  return RNA_struct_find_property(&wm, TOKEN) && RNA_string_get(&wm, TOKEN) == state.token;
}

static wmOperatorStatus call(bContext *C,
                             const char *idname,
                             const std::string &token,
                             bool discard = false,
                             bool chat_target = false)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (!ot) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA props = WM_operator_properties_create_ptr(ot);
  if (RNA_struct_find_property(&props, "field_token")) {
    RNA_string_set(&props, "field_token", token.c_str());
  }
  if (RNA_struct_find_property(&props, "chat_target")) {
    RNA_boolean_set(&props, "chat_target", chat_target);
  }
  if (RNA_struct_find_property(&props, "discard")) {
    RNA_boolean_set(&props, "discard", discard);
  }
  /* Never InvokeDefault here: adding a modal frees the current text handler. */
  const wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &props, nullptr);
  WM_operator_properties_free(&props);
  return result;
}

void text_dictation_end(bContext *C,
                        wmWindowManager *wm,
                        wmWindow *window,
                        TextDictation &state)
{
  if (state.timer) {
    WM_event_timer_remove(wm, window, state.timer);
  }
  if (!state.token.empty()) {
    call(C, "MIXIE_CHAT_OT_voice_field_cancel", state.token);
    ED_workspace_status_text(C, nullptr);
  }
  state = {};
}

static void end(bContext *C, TextDictation &state)
{
  text_dictation_end(C, CTX_wm_manager(C), CTX_wm_window(C), state);
}

static void finish_hold(bContext *C, TextDictation &state)
{
  const bool suppress = !state.released;
  end(C, state);
  state.suppress_repeats = suppress;
}

static void show_status(bContext *C, TextDictation &state)
{
  PointerRNA wm = manager_pointer(C);
  std::string status = RNA_string_get(&wm, "mixie_chat_voice_status");
  status += state.released ? ": Esc to cancel" : ": release Option/Alt to finish, Esc to cancel";
  if (status != state.displayed_status) {
    state.displayed_status = status;
    ED_workspace_status_text(C, status.c_str());
  }
}

static bool can_start(bContext *C, const Button *but)
{
  /* Numeric editing has its own expression grammar, and is not a string field. */
  if (!ELEM(but->type, ButtonType::Text, ButtonType::SearchMenu, ButtonType::TextBox)) {
    return false;
  }
  wmOperatorType *ot = WM_operatortype_find("MIXIE_CHAT_OT_voice_push_to_talk", true);
  PointerRNA wm = manager_pointer(C);
  return ot && WM_operator_poll(C, ot) && RNA_struct_find_property(&wm, TOKEN) &&
         !RNA_boolean_get(&wm, "mixie_chat_voice_listening");
}

TextDictationEvent text_dictation_event(bContext *C,
                                        Button *but,
                                        TextDictation &state,
                                        const wmEvent *event,
                                        const bool ime_composing,
                                        const bool multiline)
{
  const bool trigger = event->type == EVT_LEFTALTKEY;
  const bool press = event->val == KM_PRESS;
  const bool release = trigger && event->val == KM_RELEASE;
  const bool bare = (event->modifier & (KM_CTRL | KM_OSKEY | KM_SHIFT)) == 0;
  const bool timer = state.timer && event->type == TIMER && event->customdata == state.timer;

  if (state.suppress_repeats) {
    if (release) {
      state.suppress_repeats = false;
    }
    return {trigger && (bare || release), {}};
  }
  if (state.token.empty()) {
    if (trigger && press && bare && !ime_composing && !(event->flag & WM_EVENT_IS_REPEAT) &&
        can_start(C, but))
    {
      static uint64_t next_token = 0;
      state.token = std::to_string(++next_token);
      state.chat_target = but->rnaprop &&
                          STREQ(RNA_property_identifier(but->rnaprop), "mixie_chat_input");
      state.base = but->editstr;
      state.cursor = but->pos;
      state.selection_start = but->selsta;
      state.selection_end = but->selend;
      state.timer = WM_event_timer_add(CTX_wm_manager(C), CTX_wm_window(C), TIMER, 0.025);
      return {true, {}};
    }
    return {};
  }

  if (event->type == WINDEACTIVATE || ime_composing || state.base != but->editstr) {
    finish_hold(C, state);
    return {};
  }
  if (state.started && event->type == EVT_ESCKEY && press) {
    finish_hold(C, state);
    return {true, {}};
  }
  if ((press && !trigger && event->type != TIMER) || (trigger && press && !bare)) {
    /* Another key or mouse press turns this into a normal modifier chord.
     * Discard any capture already started; never consume the chord's event. */
    finish_hold(C, state);
    return {};
  }

  if (!state.started) {
    if (timer && state.timer->time_duration >= HOLD_SECONDS) {
      call(C, "MIXIE_CHAT_OT_voice_push_to_talk", state.token, false, state.chat_target);
      if (!matches(C, state)) {
        finish_hold(C, state);
        return {true, {}};
      }
      state.started = true;
      show_status(C, state);
    }
    else if (release) {
      /* A tap remains an ordinary modifier tap: no character and no audio. */
      end(C, state);
      return {};
    }
    return {trigger || timer, {}};
  }

  if (!matches(C, state)) {
    finish_hold(C, state);
    return {trigger || timer, {}};
  }
  if (release) {
    /* Modifiers may change after the initial press. Ownership, not the current
     * modifier mask, determines whether this release finishes the hold. */
    call(C, "MIXIE_CHAT_OT_voice_push_to_talk_release", state.token);
    state.released = true;
    show_status(C, state);
  }
  if (timer) {
    show_status(C, state);
    PointerRNA wm = manager_pointer(C);
    if (RNA_boolean_get(&wm, READY)) {
      std::string text = RNA_string_get(&wm, TEXT);
      if (!multiline) {
        /* Keep all dictated words while respecting single-line field semantics.
         * The mailbox already normalizes CRLF and removes other controls. */
        std::replace(text.begin(), text.end(), '\n', ' ');
      }
      /* Reject oversized results before deleting the user's selection. */
      const int max_size = button_string_get_maxncpy(but);
      const size_t needed = state.base.size() - (state.selection_end - state.selection_start) +
                            text.size() + 1;
      if (max_size && needed > size_t(max_size)) {
        WM_global_report(RPT_WARNING, "Voice text is too long for this field; text was preserved");
        text.clear();
      }
      if (!text.empty()) {
        but->pos = state.cursor;
        but->selsta = state.selection_start;
        but->selend = state.selection_end;
      }
      finish_hold(C, state);
      return {true, std::move(text)};
    }
  }
  return {trigger || timer, {}};
}

}  // namespace blender::ui
