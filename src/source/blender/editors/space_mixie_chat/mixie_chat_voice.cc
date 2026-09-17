/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * The composer's mic button, and what it shows while it listens.
 *
 * Split the way the Send button is split, and for the same reason: a
 * transparent `uiBut` click target keeps hover, tooltips and operator dispatch
 * inside Blender's widget system, while a GPU overlay paints a glyph the
 * widget system could neither size nor animate.
 *
 * While recording, the composer's own text is replaced on screen by a live
 * waveform and a clock. That is deliberate — the input field is empty at that
 * moment anyway (words are arriving as sound, not keystrokes), and a meter
 * where the text goes is the clearest possible answer to "is it hearing me".
 * The field itself is untouched: anything typed before the mic was pressed is
 * still there, and the transcript is APPENDED to it (see
 * `voice/core/targets.py`).
 *
 * The Agent Bubble reuses this footer wholesale, so everything here lands in
 * both surfaces with no second implementation.
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_ref.hh"
#include "BLI_time.h"
#include "BLI_utildefines.h" /* STREQ */

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "ED_mixar_audio.hh"
#include "ED_mixar_audio_ui.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_api.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"

namespace {

std::string voice_tooltip_func(bContext * /*C*/, void *argN, const blender::StringRef /*tip*/)
{
  return std::string(static_cast<const char *>(argN));
}

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

int mixie_chat_voice_add_button(uiBlock *block,
                                FooterElementPositions &pos,
                                int x,
                                float scale)
{
  const int size = voice_button_size(scale);
  pos.voice_btn_x = x;
  pos.voice_btn_size = size;

  /* An empty label, not an icon: the glyph is painted by the overlay below.
   * The button still owns the click, the hover highlight and the tooltip. */
  uiBut *but = uiDefButO(block,
                         ButType::But,
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
    RNA_string_set(UI_but_operator_ptr_ensure(but), "target", "chat");
    /* The button owns the copy and frees it with the block: `uiBut::tip` is a
     * NON-owning StringRef, so a locally built string would dangle by the
     * time the tooltip is actually read during event handling. */
    UI_but_func_tooltip_set(
        but,
        voice_tooltip_func,
        BLI_strdup("Dictate\n\nRecord your voice and add the transcript to "
                   "your message. Press again to stop."),
        MEM_freeN);
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
