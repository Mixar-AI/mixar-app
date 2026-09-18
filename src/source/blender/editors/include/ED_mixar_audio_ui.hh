/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup editors
 *
 * The mic button's pixels, shared by every surface that draws one.
 *
 * Blender ships no microphone icon, and the stock `ICON_*` set is weighted for
 * toolbars — at the size a composer button wants it out-shouts the text beside
 * it. So the glyph is painted from the same rounded-box and arc primitives the
 * account card's icons use, and it is painted HERE rather than in each surface
 * so the chat footer, the moodboard node tile and anything added later cannot
 * drift into three different mics.
 *
 * The painters are pure: they take a rect and a state, draw, and touch no
 * global state of their own. Both work in whatever projection is current, so
 * the chat's screen-space footer and the moodboard's zoomed canvas can each
 * call them without converting coordinates.
 *
 * NOTHING here reads the recorder. The caller passes `level` and `pulse`,
 * because the two surfaces sample them at different moments — the footer every
 * redraw, the canvas on its own pulse timer — and a painter that read the
 * atomics itself would make the same frame show two different levels.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. `bContext` and `rctf` live in
 * `namespace blender` in 5.2, so declaring them here at global scope minted a
 * SECOND, unrelated `::bContext` -- which then collided with `space_mixie`'s
 * `using bContext = blender::bContext;` (mixie_intern.hh) in every translation
 * unit that saw both, and made every call from blender-scoped code pass the
 * wrong pointer type. Declared inside the namespace, as ED_moodboard_attachment.hh
 * and agent_ui_icons.hh do. */
namespace blender {

struct bContext;
struct rctf;

/** What the button is showing. Mirrors the Python session's states; the
 * painter never infers one from `level` (a silent moment while recording is
 * not idle). */
enum class MixarVoiceVisual {
  Idle = 0,
  Recording,
  Transcribing,
  Error,
};

/** The voice session's state, read from its WindowManager mirror.
 *
 * The session is Python; this is the ONE C++ reader of that mirror, so no two
 * surfaces can disagree about what "recording" means. Returns `Idle` when the
 * voice module has not registered yet — with no session, nothing is recording.
 */
MixarVoiceVisual ED_mixar_voice_visual_state(const bContext *C);

/** Whether the CURRENT recording is bound to `target`.
 *
 * Surfaces use this before drawing anything that claims the recording as their
 * own: the chat footer must not paint a waveform over its composer for a
 * recording that a moodboard node started, because those words are going
 * somewhere else. Target strings are the ones `voice/core/targets.py` builds.
 */
bool ED_mixar_voice_target_is(const bContext *C, const char *target);

/** Paint one mic button inside `rect`.
 *
 * \param level: 0..1 input level. Drives the halo while Recording; ignored
 *   otherwise.
 * \param pulse: monotonic seconds, used for the transcribing spinner and the
 *   recording halo's breathing. Pass the same clock the caller redraws on.
 * \param hovered: draws the hover plate. Surfaces that host the button inside
 *   a `uiBut` pass false and let the widget system own hover.
 */
void ED_mixar_voice_draw_button(const rctf *rect,
                                MixarVoiceVisual state,
                                float level,
                                float pulse,
                                bool hovered);

/** Paint a level history as a bar waveform inside `rect`.
 *
 * `levels` is oldest-first (what `ED_mixar_audio_levels` returns). Bars are
 * centred on the rect's vertical midline and fade toward the oldest sample, so
 * the shape reads as time moving left to right. A `count` of zero draws the
 * resting line rather than nothing — an empty strip where a waveform belongs
 * reads as a broken meter.
 */
void ED_mixar_voice_draw_waveform(const rctf *rect, const float *levels, int count);

}  // namespace blender
