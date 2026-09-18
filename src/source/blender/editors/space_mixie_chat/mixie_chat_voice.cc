/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * The chat's two voice surfaces, which are deliberately not the same feature.
 *
 * 1. The HEADER's dictation operators — the trio Python drives to reach the
 *    platform speech recogniser (GHOST_MixarSpeechCocoa.mm on macOS):
 *
 *      * mixie_chat.voice_start / voice_stop bracket a dictation session. The
 *        start poll is the platform capability, so the Python toggle and the
 *        surfaces that draw it (island chip, chat and bubble headers) can ask
 *        ONE question and keep no platform table.
 *      * mixie_chat.voice_poll pops ONE recogniser event into the
 *        Python-registered WindowManager properties (`mixie_chat_voice_event_*`)
 *        and returns FINISHED; CANCELLED when nothing is queued. Partial
 *        transcriptions are produced on a system queue; this is the only place
 *        they cross into Blender, from a Python timer on the main thread.
 *
 *    Python owns everything the user sees: which text lands in the composer,
 *    the Listening state, the permission and error notices.
 *
 * 2. The COMPOSER's mic button, and what it shows while it listens. This one
 *    is the cross-platform hold-to-talk path (`modules/voice/` +
 *    `editors/mixar_audio/`): it records, the backend transcribes, and the
 *    transcript is appended to the field the recording started in. It needs no
 *    platform recogniser, so it draws everywhere the app runs.
 *
 *    Split the way the Send button is split, and for the same reason: a
 *    transparent `ui::Button` click target keeps hover, tooltips and operator
 *    dispatch inside Blender's widget system, while a GPU overlay paints a
 *    glyph the widget system could neither size nor animate.
 *
 *    While recording, the composer's own text is replaced on screen by a live
 *    waveform and a clock. That is deliberate — the input field is empty at
 *    that moment anyway (words are arriving as sound, not keystrokes), and a
 *    meter where the text goes is the clearest possible answer to "is it
 *    hearing me". The field itself is untouched: anything typed before the mic
 *    was pressed is still there, and the transcript is APPENDED to it (see
 *    `voice/core/targets.py`).
 *
 *    The Agent Bubble reuses this footer wholesale, so everything here lands in
 *    both surfaces with no second implementation.
 */

#include <cstddef>
#include <optional>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "ED_mixar_audio.hh"
#include "ED_mixar_audio_ui.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
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

/* -------------------------------------------------------------------- */
/** \name The Composer's Mic Button
 * \{ */

namespace {

/* The button is the same size as the other footer icons, so the row reads as
 * one set of controls rather than a mic bolted onto the end of it. */
int voice_button_size(float scale)
{
  return int(chat_ui_get_attach_button_size() * scale);
}

void format_clock(float seconds, char *out, size_t out_len)
{
  const int total = int(seconds);
  BLI_snprintf(out, out_len, "%d:%02d", total / 60, total % 60);
}

}  // namespace

int mixie_chat_voice_add_button(ui::Block *block,
                                FooterElementPositions &pos,
                                int x,
                                float scale)
{
  const int size = voice_button_size(scale);
  pos.voice_btn_x = x;
  pos.voice_btn_size = size;

  /* An empty label, not an icon: the glyph is painted by the overlay below.
   * The button still owns the click, the hover highlight and the tooltip. */
  ui::Button *but = ui::uiDefButO(block,
                                  ui::ButtonType::But,
                                  "MIXAR_OT_voice_record_toggle",
                                  blender::wm::OpCallContext::ExecDefault,
                                  "",
                                  x,
                                  pos.buttons_y,
                                  size,
                                  pos.button_row_height,
                                  std::nullopt);
  if (but != nullptr) {
    /* The target is captured HERE, at the press, and carried to the end —
     * the transcript belongs to the composer even if the user clicks a node
     * while it is being transcribed. */
    RNA_string_set(ui::button_operator_ptr_ensure(but), "target", "chat");
    /* `ui::Button::tip` is a NON-owning StringRef, so a locally built string
     * would dangle by the time the tooltip is actually read during event
     * handling; this takes a copy the button owns and frees. */
    ui::mixar_button_tooltip_owned(but,
                                   "Dictate\n\nRecord your voice and add the transcript to "
                                   "your message. Press again to stop.");
  }
  return x + size + int(FOOTER_BUTTON_SPACING_BASE * scale);
}

void mixie_chat_voice_draw(const bContext *C,
                           ARegion *region,
                           const FooterElementPositions &pos,
                           float scale)
{
  if (region == nullptr || pos.voice_btn_size <= 0) {
    return;
  }

  const MixarVoiceVisual state = ED_mixar_voice_visual_state(C);
  const float pulse = float(BLI_time_now_seconds());

  /* The level comes straight from the capture engine rather than through RNA:
   * this is a draw pass, and the engine's reading is an atomic load. */
  const float level = ED_mixar_audio_level();

  rctf button;
  button.xmin = float(pos.voice_btn_x);
  button.xmax = float(pos.voice_btn_x + pos.voice_btn_size);
  button.ymin = float(pos.buttons_y);
  button.ymax = float(pos.buttons_y + pos.button_row_height);
  /* Square it inside the row so the halo stays circular. */
  const float row_h = BLI_rctf_size_y(&button);
  const float btn_w = BLI_rctf_size_x(&button);
  if (row_h > btn_w) {
    const float inset = (row_h - btn_w) * 0.5f;
    button.ymin += inset;
    button.ymax -= inset;
  }

  ED_mixar_voice_draw_button(&button, state, level, pulse, false);

  if (state != MixarVoiceVisual::Recording || !ED_mixar_voice_target_is(C, "chat")) {
    return;
  }

  /* Live waveform + clock across the composer. */
  char clock[16];
  format_clock(ED_mixar_audio_duration(), clock, sizeof(clock));

  const float pad = 10.0f * scale;
  const float clock_w = 46.0f * scale;

  rctf wave;
  wave.xmin = float(pos.input_x) + pad;
  wave.xmax = float(pos.input_x + pos.input_w) - pad - clock_w;
  wave.ymin = float(pos.input_y) + BLI_rctf_size_y(&button) * 0.25f;
  wave.ymax = float(pos.input_y + pos.input_height) - BLI_rctf_size_y(&button) * 0.25f;

  float levels[MIXAR_AUDIO_LEVEL_HISTORY];
  const int count = ED_mixar_audio_levels(levels, MIXAR_AUDIO_LEVEL_HISTORY);
  ED_mixar_voice_draw_waveform(&wave, levels, count);

  const float clock_color[4] = {0.94f, 0.42f, 0.44f, 1.0f};
  chat_ui_draw_label(clock,
                     float(pos.input_x + pos.input_w) - pad,
                     (wave.ymin + wave.ymax) * 0.5f - 5.0f * scale,
                     int(11 * scale),
                     0,
                     clock_color,
                     true);
}

/** \} */

}  // namespace blender
