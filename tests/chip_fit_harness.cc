/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Drive the shipped chip-row fitter across window widths, text sizes and
 * composer states — no Mixar binary. Text is measured at a fixed advance per
 * character (Manrope's average is ~0.55 em), which is all the fitter needs.
 *
 *   c++ -std=c++17 -I src/source/blender/editors/space_agent_bubble \
 *       tests/chip_fit_harness.cc -o chip_fit_harness
 *
 * One line per case:
 *   fit <scenario> <text_size> <window_px> span=.. used=.. fits=0|1 forms=a,b,.. widths=a,b,..
 * `forms` holds -1 for a chip that is not shown at all.
 */

#include "agent_ui_chip_fit.hh"

#include <cstdio>
#include <cstring>

using namespace blender;

/* Island artboard constants mirrored from agent_ui_theme.hh (the harness must
 * not include Blender headers); tests/test_island_voice_and_sketch_pill.py
 * checks these numbers against the theme so they cannot drift. */
static constexpr float ISLAND_W = 1310.0f;
static constexpr float SEG_X = 24.0f;
static constexpr float SEND_W = 114.0f;
static constexpr float CHIP_GAP = 12.0f;
static constexpr float CHIP_ICON = 18.0f;
static constexpr float CHIP_ICON_GAP = 8.0f;
static constexpr float CHIP_PAD_X = 12.0f;
static constexpr float SWITCH_W = 40.0f;
static constexpr float CLEAR_W = 44.0f;
static constexpr float WAVE_W = 30.0f;

struct Scenario {
  const char *name;
  AgentChipRowInputs in;
};

static void run(const Scenario &sc, const float text_size, const float window_px)
{
  const float u = window_px / ISLAND_W;
  const AgentChipMetrics m{CHIP_ICON * u,
                           CHIP_ICON_GAP * u,
                           CHIP_PAD_X * u,
                           SWITCH_W * u,
                           CLEAR_W * u,
                           WAVE_W * u,
                           text_size};
  AgentChipForms chips[AGENT_CHIP_SLOT_COUNT];
  agent_chip_forms(
      sc.in, m, [&](const char *s) { return float(std::strlen(s)) * text_size * 0.55f; }, chips);
  const float span = (ISLAND_W - SEG_X * 2.0f - SEND_W) * u;
  const float gap = CHIP_GAP * u;
  const AgentChipFit fit = agent_chip_fit(chips, span, gap);

  float used = 0.0f;
  for (int i = 0; i < AGENT_CHIP_SLOT_COUNT; i++) {
    if (fit.width[i] > 0.0f) {
      used += fit.width[i] + gap;
    }
  }
  std::printf("fit %s %.2f %.0f span=%.3f used=%.3f fits=%d forms=", sc.name,
              double(text_size), double(window_px), double(span), double(used), int(fit.fits));
  for (int i = 0; i < AGENT_CHIP_SLOT_COUNT; i++) {
    const int shown = chips[i].count;
    std::printf("%s%d", i ? "," : "", shown ? fit.form[i] : -1);
  }
  std::printf(" counts=");
  for (int i = 0; i < AGENT_CHIP_SLOT_COUNT; i++) {
    std::printf("%s%d", i ? "," : "", chips[i].count);
  }
  std::printf(" widths=");
  for (int i = 0; i < AGENT_CHIP_SLOT_COUNT; i++) {
    std::printf("%s%.3f", i ? "," : "", double(fit.width[i]));
  }
  std::printf(" full=");
  for (int i = 0; i < AGENT_CHIP_SLOT_COUNT; i++) {
    std::printf("%s%.3f", i ? "," : "", double(chips[i].count ? chips[i].width[0] : 0.0f));
  }
  std::printf("\n");
}

int main()
{
  AgentChipRowInputs idle;
  idle.scribble_available = true;
  idle.voice_available = true;
  idle.model_available = true;
  idle.model_label = "Mixie";

  AgentChipRowInputs capturing = idle;
  capturing.voice_listening = true;
  capturing.voice_capturing = true;
  capturing.voice_status = "Listening";

  AgentChipRowInputs sketching = capturing;
  sketching.scribble_armed = true;
  sketching.mark_intent = "Point to edit";
  sketching.model_label = "Claude Sonnet 4.6 · High";

  AgentChipRowInputs queued = idle;
  queued.mark_count = 2;
  queued.mark_intent = "Draw to build";
  queued.voice_listening = true;
  queued.voice_status = "Allow microphone";

  AgentChipRowInputs long_model = idle;
  long_model.model_label = "Claude Opus 5 · Extended thinking";

  AgentChipRowInputs no_voice = idle;
  no_voice.voice_available = false;

  const Scenario scenarios[] = {
      {"idle", idle},
      {"capturing", capturing},
      {"sketching", sketching},
      {"queued", queued},
      {"long_model", long_model},
      {"no_voice", no_voice},
  };
  /* Native widget text at 100% / 125% / 15-point / 15-point at 125%. */
  const float sizes[] = {11.0f, 13.75f, 15.0f, 18.75f};
  for (const Scenario &sc : scenarios) {
    for (const float size : sizes) {
      for (float w = 300.0f; w <= 1400.0f; w += 10.0f) {
        run(sc, size, w);
      }
    }
  }
  return 0;
}
