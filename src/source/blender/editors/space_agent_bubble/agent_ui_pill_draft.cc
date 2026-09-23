/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** The minimised Sketch pill's content left of the cat: the live draft with a
 *  blinking caret (typing over the viewport lands here), the title line, and
 *  the Voice button. Painting, the native hit test and QA share one set of
 *  rectangles, all in the pill window's pixels (the painter runs under the
 *  header draw's -winrct translation, so its coordinates ARE window pixels). */
#include <algorithm>
#include <limits>
#include <string>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "UI_mixar_motion.hh"
#include "../interface/interface_qa_inspect.hh"
#include "agent_ui_draw_primitives.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_pill_draft.hh"
#include "agent_ui_theme.hh"
#include "agent_ui_voice_motion.hh"
#include "agent_ui_voice_paint.hh"

namespace blender {
namespace {
rcti preview_rect;
std::string preview_text;
std::string preview_draft;
bool preview_valid = false;

/* Caret: solid while the draft changes, then blinking from that moment. */
std::string caret_draft;
double caret_epoch = 0.0;
bool caret_shown = false;

/* Voice button; empty when the platform has no recogniser. */
rctf voice_rect = {};
bool voice_valid = false;
bool voice_listening = false;
bool voice_capturing = false;

bool pill_only(const ScrArea *area, const ARegion *region)
{
  if (!area || !region || area->spacetype != SPACE_AGENT_BUBBLE ||
      region->regiontype != RGN_TYPE_HEADER)
  {
    return false;
  }
  for (const ARegion &other : area->regionbase) {
    if (ELEM(other.regiontype, RGN_TYPE_WINDOW, RGN_TYPE_TOOLS)) {
      return false;
    }
  }
  return true;
}

void draft_targets(const wmWindow *, const ScrArea *area, const ARegion *region,
                   std::vector<MixarQATarget> &targets)
{
  if (!preview_valid || !pill_only(area, region)) {
    return;
  }
  MixarQATarget target;
  target.surface = "pill_draft_preview";
  target.text = preview_text;
  target.value = preview_draft;
  target.detail = caret_shown ? "caret" : "";
  target.rect_win = preview_rect;
  BLI_rcti_translate(&target.rect_win, region->winrct.xmin, region->winrct.ymin);
  targets.push_back(std::move(target));

  if (voice_valid) {
    MixarQATarget voice;
    voice.surface = "pill_voice";
    voice.text = voice_capturing ? "Stop" : "Voice";
    voice.value = voice_capturing ? "capturing" : voice_listening ? "listening" : "idle";
    voice.sel = voice_listening;
    /* Already window pixels: the same rectangle the click is tested against. */
    BLI_rcti_rctf_copy_round(&voice.rect_win, &voice_rect);
    targets.push_back(std::move(voice));
  }
}

void draw_voice_button(const AgentIslandState &state, const rctf &disc)
{
  MIXAR_THEME_LOAD(chip, Chip);
  MIXAR_THEME_LOAD(accent, AgentAccent);
  MIXAR_THEME_LOAD(text, Text);
  float fill[4];
  std::copy_n(state.voice_listening ? accent : chip, 4, fill);
  if (state.voice_listening && !state.voice_capturing) {
    fill[3] *= 0.6f; /* Permission or finishing: lit, but a click only cancels. */
  }
  fill_round(&disc, BLI_rctf_size_x(&disc) * 0.5f, fill);
  rctf glyph = disc;
  BLI_rctf_scale(&glyph, 0.5f);
  if (state.voice_capturing) {
    agent_ui_draw_stop_glyph(glyph, text);
  }
  else {
    agent_ui_icon_draw(AGENT_ICON_MIC, &glyph, text, fill);
  }
}
}  // namespace

void agent_ui_draw_pill_draft(const AgentIslandState &state,
                              const float left,
                              float right,
                              const float height,
                              const float font_size,
                              const float u)
{
  const double now = BLI_time_now_seconds();
  voice_valid = state.voice_available;
  voice_listening = state.voice_listening;
  voice_capturing = state.voice_capturing;
  if (voice_valid) {
    /* Right of the text, left of the cat, vertically centred. */
    const float d = 60.0f * u;
    const float cy = height * 0.5f;
    voice_rect = {right - d, right, cy - d * 0.5f, cy + d * 0.5f};
    draw_voice_button(state, voice_rect);
    right = voice_rect.xmin - 16.0f * u;
  }

  preview_draft = state.sketch_prompt;
  if (preview_draft != caret_draft) {
    caret_draft = preview_draft;
    caret_epoch = now;
  }
  const bool empty = preview_draft.empty();
  std::string text = empty ? "Type instructions..." : preview_draft;
  for (char &c : text) {
    if (c == '\n' || c == '\r' || c == '\t') {
      c = ' ';
    }
  }
  /* Room for the caret after the text (or before the placeholder). */
  const float caret_w = std::max(1.0f, float(int(font_size * 0.08f + 0.5f)));
  const float caret_room = caret_w + font_size * 0.25f;
  const float width = std::max(0.0f, right - left - caret_room);
  size_t offset = 0;
  preview_text = text;
  /* Keep the newest typed characters visible; never split a UTF-8 codepoint. */
  while (text_width(preview_text.c_str(), font_size) > width && offset < text.size()) {
    do {
      offset++;
    } while (offset < text.size() && (text[offset] & 0xc0) == 0x80);
    preview_text = "..." + text.substr(offset);
  }

  const float title_color[4] = AGENT_COL_TEXT_DIM;
  const float text_color[4] = AGENT_COL_TEXT;
  const float placeholder_color[4] = AGENT_COL_TEXT_DIM;
  const std::string title = state.voice_status[0] ?
                                std::string(state.voice_status) + " · Enter to send" :
                                "Sketch · Enter to send";
  const float title_size = font_size * 0.75f;
  const float title_y = height * 0.72f;
  float title_x = left;
  if (state.voice_capturing) {
    /* The live trace leads the title: the pill is hearing you. */
    MIXAR_THEME_LOAD(border, AgentBorder);
    const float wave_w = title_size * 2.2f;
    const rctf wave{left, left + wave_w, title_y - title_size * 0.55f, title_y + title_size * 0.55f};
    agent_ui_draw_voice_wave(wave, now, state.voice_level, border);
    title_x += wave_w + title_size * 0.5f;
  }
  label_left(title.c_str(), title_x, title_y, title_size, title_color);

  const float line_y = height * 0.32f;
  const float text_x = empty ? left + caret_room : left;
  label_left(preview_text.c_str(), text_x, line_y, font_size, empty ? placeholder_color : text_color);

  caret_shown = agent_caret_visible(now, caret_epoch, ui::mixar_motion_reduced());
  if (caret_shown) {
    MIXAR_THEME_LOAD(border, AgentBorder);
    const float caret_x = empty ? left :
                                  left + text_width(preview_text.c_str(), font_size) +
                                      font_size * 0.08f;
    const rctf caret{caret_x, caret_x + caret_w, line_y - font_size * 0.62f, line_y + font_size * 0.62f};
    fill_round(&caret, caret_w * 0.5f, border);
  }
  BLI_rcti_init(&preview_rect, int(left), int(right), int(height * 0.08f), int(height * 0.94f));
  preview_valid = true;
}

double agent_ui_pill_draft_next_frame()
{
  if (!preview_valid) {
    return std::numeric_limits<double>::infinity();
  }
  const double now = BLI_time_now_seconds();
  const bool reduced = ui::mixar_motion_reduced();
  double next = agent_caret_next_change(now, caret_epoch, reduced);
  if (voice_capturing && !reduced) {
    next = std::min(next, AGENT_VOICE_WAVE_FRAME_SECONDS);
  }
  return next;
}

bool agent_ui_pill_voice_hit(const int x, const int y)
{
  if (!preview_valid || !voice_valid) {
    return false;
  }
  /* The disc, not its bounding square: a corner press still opens the chat. */
  const float dx = float(x) - BLI_rctf_cent_x(&voice_rect);
  const float dy = float(y) - BLI_rctf_cent_y(&voice_rect);
  const float r = BLI_rctf_size_x(&voice_rect) * 0.5f;
  return dx * dx + dy * dy <= r * r;
}

void agent_ui_pill_draft_clear()
{
  preview_valid = false;
  voice_valid = false;
}

void agent_ui_pill_draft_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, draft_targets);
}
}  // namespace blender
