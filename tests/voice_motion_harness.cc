/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Sample the shipped caret-blink and ECG-trace math — no Mixar binary.
 *
 *   c++ -std=c++17 -I src/source/blender/editors/space_agent_bubble \
 *       tests/voice_motion_harness.cc -o voice_motion_harness
 *
 * Lines:
 *   caret <now> <epoch> <reduced> visible=0|1 next=<seconds|inf>
 *   wave <now> <level> <reduced> n=<count> min_x=.. max_x=.. min_y=.. max_y=.. mono=0|1 pts=x:y;..
 */

#include "agent_ui_voice_motion.hh"

#include <cmath>
#include <cstdio>

using namespace blender;

static void caret(const double now, const double epoch, const bool reduced)
{
  const double next = agent_caret_next_change(now, epoch, reduced);
  std::printf("caret %.4f %.4f %d visible=%d next=", now, epoch, int(reduced),
              int(agent_caret_visible(now, epoch, reduced)));
  if (std::isinf(next)) {
    std::printf("inf\n");
  }
  else {
    std::printf("%.6f\n", next);
  }
}

static void wave(const double now, const float level, const bool reduced)
{
  float pts[AGENT_VOICE_WAVE_MAX_POINTS][2];
  const int n = agent_voice_wave_points(now, level, reduced, pts);
  float min_x = 1e9f, max_x = -1e9f, min_y = 1e9f, max_y = -1e9f;
  bool mono = true;
  for (int i = 0; i < n; i++) {
    min_x = std::fmin(min_x, pts[i][0]);
    max_x = std::fmax(max_x, pts[i][0]);
    min_y = std::fmin(min_y, pts[i][1]);
    max_y = std::fmax(max_y, pts[i][1]);
    if (i > 0 && pts[i][0] < pts[i - 1][0] - 1e-6f) {
      mono = false;
    }
  }
  std::printf("wave %.4f %.3f %d n=%d min_x=%.6f max_x=%.6f min_y=%.6f max_y=%.6f mono=%d pts=",
              now, double(level), int(reduced), n, double(min_x), double(max_x), double(min_y),
              double(max_y), int(mono));
  for (int i = 0; i < n; i++) {
    std::printf("%s%.5f:%.5f", i ? ";" : "", double(pts[i][0]), double(pts[i][1]));
  }
  std::printf("\n");
}

int main()
{
  std::printf("# blink=%.4f beats=%.4f quiet=%.4f max=%d frame=%.6f\n",
              AGENT_CARET_BLINK_SECONDS, double(AGENT_VOICE_WAVE_BEATS),
              double(AGENT_VOICE_WAVE_QUIET), AGENT_VOICE_WAVE_MAX_POINTS,
              AGENT_VOICE_WAVE_FRAME_SECONDS);
  const double epoch = 100.0;
  for (int i = -2; i <= 60; i++) {
    caret(epoch + i * 0.05, epoch, false);
  }
  caret(epoch + 0.8, epoch, true);
  caret(epoch + 5.0, epoch, true);

  for (int i = 0; i < 40; i++) {
    wave(3.0 + i * 0.037, 0.0f, false);
  }
  for (int i = 0; i < 40; i++) {
    wave(3.0 + i * 0.037, 1.0f, false);
  }
  wave(12345.678, 0.5f, false);
  wave(987654.321, 0.5f, false);
  wave(1.0, 0.5f, true);
  wave(7.3, 0.5f, true);
  return 0;
}
