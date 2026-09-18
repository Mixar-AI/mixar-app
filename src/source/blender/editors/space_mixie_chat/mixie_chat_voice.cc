/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Voice input — the operator trio Python drives to reach the platform speech
 * recogniser (GHOST_MixarSpeechCocoa.mm on macOS):
 *
 *   * mixie_chat.voice_start / voice_stop bracket a dictation session. The
 *     start poll is the platform capability, so the Python toggle and the
 *     surfaces that draw it (island chip, chat and bubble headers) can ask
 *     ONE question and keep no platform table.
 *   * mixie_chat.voice_poll pops ONE recogniser event into the
 *     Python-registered WindowManager properties (`mixie_chat_voice_event_*`)
 *     and returns FINISHED; CANCELLED when nothing is queued. Partial
 *     transcriptions are produced on a system queue; this is the only place
 *     they cross into Blender, from a Python timer on the main thread.
 *
 * Python owns everything the user sees: which text lands in the composer,
 * the Listening state, the permission and error notices.
 */

#include <cstring>

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

#ifdef __APPLE__
extern "C" bool Mixar_SpeechAvailable(void);
extern "C" bool Mixar_SpeechIsListening(void);
extern "C" bool Mixar_SpeechStart(void);
extern "C" void Mixar_SpeechStop(void);
extern "C" bool Mixar_SpeechPopEvent(int *r_kind, char *r_text, int text_maxlen);
#endif

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static constexpr int VOICE_TEXT_MAX = 4096;

static bool voice_available()
{
#ifdef __APPLE__
  return Mixar_SpeechAvailable();
#else
  return false;
#endif
}

static bool voice_poll_available(bContext * /*C*/)
{
  return voice_available();
}

/* -------------------------------------------------------------------- */
/** \name MIXIE_CHAT_OT_voice_start / voice_stop
 * \{ */

static wmOperatorStatus voice_start_exec(bContext * /*C*/, wmOperator * /*op*/)
{
#ifdef __APPLE__
  return Mixar_SpeechStart() ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
#else
  return OPERATOR_CANCELLED;
#endif
}

void MIXIE_CHAT_OT_voice_start(wmOperatorType *ot)
{
  ot->name = "Start Voice Input";
  ot->idname = "MIXIE_CHAT_OT_voice_start";
  ot->description = "Start dictating into the chat composer";
  ot->exec = voice_start_exec;
  ot->poll = voice_poll_available;
  ot->flag = OPTYPE_INTERNAL;
}

static wmOperatorStatus voice_stop_exec(bContext * /*C*/, wmOperator * /*op*/)
{
#ifdef __APPLE__
  Mixar_SpeechStop();
  return OPERATOR_FINISHED;
#else
  return OPERATOR_CANCELLED;
#endif
}

void MIXIE_CHAT_OT_voice_stop(wmOperatorType *ot)
{
  ot->name = "Stop Voice Input";
  ot->idname = "MIXIE_CHAT_OT_voice_stop";
  ot->description = "Stop dictating";
  ot->exec = voice_stop_exec;
  ot->poll = voice_poll_available;
  ot->flag = OPTYPE_INTERNAL;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name MIXIE_CHAT_OT_voice_poll
 * \{ */

static bool voice_poll_poll(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm || !voice_available()) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  return RNA_struct_find_property(&wm_ptr, "mixie_chat_voice_event_kind") != nullptr;
}

static wmOperatorStatus voice_poll_exec(bContext *C, wmOperator * /*op*/)
{
#ifdef __APPLE__
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return OPERATOR_CANCELLED;
  }
  int kind = 0;
  char text[VOICE_TEXT_MAX];
  text[0] = '\0';
  if (!Mixar_SpeechPopEvent(&kind, text, VOICE_TEXT_MAX)) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  if (PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_voice_event_kind")) {
    RNA_property_int_set(&wm_ptr, prop, kind);
  }
  if (PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_voice_event_text")) {
    RNA_property_string_set(&wm_ptr, prop, text);
  }
  return OPERATOR_FINISHED;
#else
  (void)C;
  return OPERATOR_CANCELLED;
#endif
}

void MIXIE_CHAT_OT_voice_poll(wmOperatorType *ot)
{
  ot->name = "Poll Voice Input";
  ot->idname = "MIXIE_CHAT_OT_voice_poll";
  ot->description = "Move one speech recogniser event into the window-manager properties";
  ot->exec = voice_poll_exec;
  ot->poll = voice_poll_poll;
  ot->flag = OPTYPE_INTERNAL;
}

/** \} */

}  // namespace blender
