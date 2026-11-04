/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The Director timeline's ruler and playhead.
 *
 * Split from `view3d_director_timeline_draw.cc` for the 500-line rule once
 * the ruler grew a second tick ladder. The whole ruler works in FRAMES and
 * picks its step from the ladder the selected unit belongs to, so switching
 * the unit changes the ruler's STRUCTURE and not just the text over it.
 *
 * The shared paint primitives live in `_draw.cc` and are declared in
 * `view3d_director_timeline.hh`.
 */

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_screen_types.h"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "view3d_director_timeline.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Design tokens: a hairline major tick, dimmer minor dots, quiet labels. */
constexpr float RULER_COLOR[4] = {0.435f, 0.435f, 0.435f, 1.0f};       /* #6F6F6F */
constexpr float RULER_MINOR_COLOR[4] = {0.278f, 0.278f, 0.278f, 1.0f}; /* #474747 */
constexpr float TIME_COLOR[4] = {0.604f, 0.604f, 0.604f, 1.0f};        /* #9A9A9A */
constexpr float PLAYHEAD_COLOR[4] = {0.851f, 0.851f, 0.851f, 1.0f};    /* #D9D9D9 */
constexpr float PLAYHEAD_TEXT_COLOR[4] = {0.035f, 0.045f, 0.055f, 1.0f};
/** Grab tolerance either side of the playhead line, design px. A
 * one-pixel line is not something a pointer can catch. */
constexpr float PLAYHEAD_GRAB_PAD = 5.0f;
/** Outside the scene's frame range nothing plays and nothing renders, so the
 * dock says so in one stroke: a scrim over the WHOLE stack there — ruler,
 * ticks, strip and keyframes — the way Blender's own timeline dims
 * everything outside `sfra..efra`. Dimming each layer separately would mean
 * every future layer having to remember to do it. */
constexpr float OUT_OF_RANGE_COLOR[4] = {0.043f, 0.043f, 0.043f, 0.62f};
/** A hairline at each boundary, so the edge reads as an edge. */
constexpr float RANGE_EDGE_COLOR[4] = {1.0f, 1.0f, 1.0f, 0.10f};

/** Second steps a time ruler is allowed to land on. */
constexpr std::array<float, 15> SECOND_STEPS = {0.1f,
                                                0.2f,
                                                0.5f,
                                                1.0f,
                                                2.0f,
                                                5.0f,
                                                10.0f,
                                                15.0f,
                                                30.0f,
                                                60.0f,
                                                120.0f,
                                                300.0f,
                                                600.0f,
                                                1800.0f,
                                                3600.0f};

/**
 * Frame steps for a frame ruler zoomed in PAST one second — the only case
 * where it does not mark seconds, because no second-mark would be on screen.
 */
constexpr std::array<float, 4> SUB_SECOND_FRAME_STEPS = {1.0f, 2.0f, 5.0f, 10.0f};

/** How many seconds apart a frame ruler's marks are allowed to be. */
constexpr std::array<float, 8> SECOND_MULTIPLES = {
    1.0f, 2.0f, 5.0f, 10.0f, 15.0f, 30.0f, 60.0f, 300.0f};

/**
 * The major tick step, in FRAMES, for the unit the dock's chips select.
 *
 * A FRAME ruler marks SECONDS, in the frame numbers a director counts them
 * by: 24, 48, 72 at 24fps and 30, 60, 90 at 30fps, so the marks move when the
 * rate does. It stepped 10, 20, 30 before — tens of nothing. The ladder only
 * ever goes UP from one second (2, 5, 10, 15, 30, 60, 300 of them); it never
 * offers a smaller mark just because one would fit, which is what kept
 * putting a ten-frame step on screen at ordinary zooms.
 *
 * The single exception is being zoomed INSIDE one second, where marking
 * seconds would leave no labelled tick on screen at all. Only then does it
 * fall back to whole frames (1, 2, 5, 10).
 *
 * A DURATION ruler marks round times (tenths, halves, seconds, minutes) and
 * is free to go below a second, because seconds are what it is labelling.
 */
float major_tick_frames(const DirectorViewState &state,
                        const float pixels_per_frame,
                        const float span_frames)
{
  const float target = 86.0f * UI_SCALE_FAC;
  const float fps = std::max(state.fps, 0.001f);
  if (state.ruler_frames) {
    /* One second, in whole frames. Rounded because a mark every 23.976
     * frames would round two neighbours onto the same number. */
    const float second = std::max(1.0f, std::round(fps));
    for (const float multiple : SECOND_MULTIPLES) {
      const float step = second * multiple;
      if (step * pixels_per_frame < target) {
        continue;
      }
      if (step <= span_frames) {
        return step;
      }
      /* A whole second is wider than the view: marking seconds would leave
       * no labelled tick on screen at all. */
      break;
    }
    if (second * pixels_per_frame < target) {
      /* Zoomed out past the whole ladder. */
      return second * SECOND_MULTIPLES.back();
    }
    for (const float step : SUB_SECOND_FRAME_STEPS) {
      if (step * pixels_per_frame >= target) {
        return step;
      }
    }
    return 1.0f;
  }
  for (const float seconds : SECOND_STEPS) {
    /* Whole frames, for the same reason. */
    const float frames = std::max(1.0f, std::round(seconds * fps));
    if (frames * pixels_per_frame >= target) {
      return frames;
    }
  }
  return std::max(1.0f, std::round(SECOND_STEPS.back() * fps));
}

/**
 * Ruler label for the absolute \a frame, in the unit the dock's chips select.
 *
 * FRAMES is the frame number a director quotes to an animator — the same
 * number Blender's own timeline shows, so it is the scene's frame and never
 * an offset from anything. DURATION is elapsed time from the scene's start.
 */
void ruler_label(const DirectorViewState &state,
                 const float frame,
                 const float major_frames,
                 const float span_seconds,
                 char *out,
                 const int size)
{
  if (state.ruler_frames) {
    BLI_snprintf(out, size, "%d", int(std::round(frame)));
    return;
  }
  const float fps = std::max(state.fps, 0.001f);
  const float seconds = (frame - float(state.scene_frame_start)) / fps;
  const float major_seconds = major_frames / fps;
  /* `m:ss` once a minute or more is on screen; below that it would read
   * "0:03" where "03s" is what anyone means. */
  if (span_seconds >= 60.0f && major_seconds >= 1.0f) {
    const int total = int(std::round(seconds));
    BLI_snprintf(out, size, "%d:%02d", total / 60, std::abs(total % 60));
    return;
  }
  if (major_seconds < 1.0f) {
    BLI_snprintf(out, size, "%.1fs", seconds);
    return;
  }
  /* The design pads single digits ("01s", "02s") so the row keeps its rhythm
   * when the labels cross from one digit to two. */
  BLI_snprintf(out, size, "%02.0fs", seconds);
}

/**
 * Labels sit above the ticks and the ticks hang down to the dock's floor, so
 * the ruler reads as a scale rather than a row of centred marks.
 */
}  // namespace

void director_timeline_draw_range_scrim(const DirectorViewState &state,
                                        const DirectorTimelineRuntime &runtime,
                                        const float bottom,
                                        const float top)
{
  const float width = BLI_rctf_size_x(&runtime.viewport_bounds);
  if (width <= 0.0f || top <= bottom) {
    return;
  }
  const float span = std::max(runtime.view_span_frames, 0.001f);
  const float x0 = runtime.viewport_bounds.xmin;
  const float x1 = runtime.viewport_bounds.xmax;
  /* The dock pans and zooms, so each end is clamped to the viewport box
   * rather than drawn wherever the range happens to land. */
  const auto frame_x = [&](const int frame) {
    const float x = x0 + (float(frame) - runtime.view_start_frame) / span * width;
    return std::clamp(x, x0, x1);
  };
  const float left = frame_x(state.scene_frame_start);
  const float right = frame_x(state.scene_frame_end);

  const float line = std::max(1.0f, UI_SCALE_FAC);
  if (left > x0) {
    director_timeline_draw_rect(x0, bottom, left, top, OUT_OF_RANGE_COLOR);
    director_timeline_draw_rect(left - line, bottom, left, top, RANGE_EDGE_COLOR);
  }
  if (right < x1) {
    director_timeline_draw_rect(right, bottom, x1, top, OUT_OF_RANGE_COLOR);
    director_timeline_draw_rect(right, bottom, right + line, top, RANGE_EDGE_COLOR);
  }
}

void director_timeline_draw_ruler(const DirectorViewState &state,
                const DirectorTimelineRuntime &runtime,
                const float tick_base)
{
  const float u = UI_SCALE_FAC;
  const float width = BLI_rctf_size_x(&runtime.viewport_bounds);
  const float fps = std::max(state.fps, 0.001f);
  const float pixels_per_frame = width / std::max(runtime.view_span_frames, 0.001f);

  /* Everything below is in FRAMES: the ruler's ticks land on the unit it is
   * labelling, so switching the unit changes the structure and not just the
   * text over it. */
  const float major = major_tick_frames(state, pixels_per_frame, runtime.view_span_frames);
  const int divisions = major * pixels_per_frame >= 150.0f * u ? 10 : 5;
  float minor = major / float(divisions);
  if (state.ruler_frames) {
    /* A frame ruler may not put two ticks inside one frame — they would
     * round to the same number and read as a stutter.
     *
     * Whole frames alone are not enough. The major test below asks whether a
     * tick lands on a multiple of `major`, so a step that does not DIVIDE
     * `major` only meets one at their common multiple: at 24fps `major = 24`
     * rounds to a step of 5, and the first tick to land on a second mark
     * after frame 0 is frame 120 — the labelled ladder this ruler is built
     * around, five times too sparse. So round, then climb to the next whole
     * divisor. Climbing (never dropping) keeps the sub-frame rule intact. */
    const int major_frames = std::max(1, int(std::lround(major)));
    int step = std::clamp(int(std::lround(minor)), 1, major_frames);
    while (step < major_frames && major_frames % step != 0) {
      step++;
    }
    minor = float(step);
  }

  const float view_start = runtime.view_start_frame;
  const float view_end = view_start + runtime.view_span_frames;
  const float span_seconds = runtime.view_span_frames / fps;
  /* Each unit is anchored where its own numbers start.
   *
   * DURATION measures elapsed time from the scene's start, so it anchors
   * there. Anchored on frame zero its ticks landed a frame off their own
   * labels: on a scene starting at frame 1, the tick one second in sat at
   * frame 24 while one second in is frame 25, so the "01s" tick was really at
   * 0.96s and the playhead pill parked on it read 0.96 while the ruler under
   * it read 01s.
   *
   * FRAMES labels the absolute frame number, so it anchors on zero and its
   * marks are exact multiples of the rate — 24, 48, 72 at 24fps — which is
   * how a director counts them. */
  const float origin = state.ruler_frames ? 0.0f : float(state.scene_frame_start);
  const float first_tick = origin + std::ceil((view_start - origin) / minor) * minor;

  const float major_h = DIRECTOR_RULER_TICK_H * u;
  const float label_y = tick_base + major_h + DIRECTOR_RULER_LABEL_GAP * u;

  for (float frame = first_tick; frame <= view_end + minor * 0.25f; frame += minor) {
    /* Nothing before the scene starts: a scene beginning on frame 1 must not
     * grow a "0" tick to the left of its own first frame. */
    if (frame < float(state.scene_frame_start) - 0.5f) {
      continue;
    }
    const float t = (frame - view_start) / runtime.view_span_frames;
    const float x = runtime.viewport_bounds.xmin + t * width;
    const float major_index = std::round((frame - origin) / major);
    const bool is_major = std::abs((frame - origin) - major_index * major) < minor * 0.15f;
    if (is_major) {
      director_timeline_draw_rect(x, tick_base, x + std::max(1.0f, u), tick_base + major_h, RULER_COLOR);
      char label[32];
      ruler_label(state, frame, major, span_seconds, label, sizeof(label));
      director_timeline_draw_text(label, x - 2.0f * u, label_y, 12.0f * u, TIME_COLOR);
    }
    else {
      const float dot = std::max(2.0f, 2.0f * u);
      const float dot_y = tick_base + major_h * 0.42f;
      const rctf dot_rect = {
          x - dot * 0.5f, x + dot * 0.5f, dot_y - dot * 0.5f, dot_y + dot * 0.5f};
      director_timeline_draw_round_rect(dot_rect, dot * 0.5f, RULER_MINOR_COLOR);
    }
  }
}


bool director_timeline_playhead_grab(const DirectorTimelineRuntime &runtime,
                                     const float x,
                                     const float y)
{
  return BLI_rctf_isect_pt(&runtime.playhead_line, x, y) ||
         BLI_rctf_isect_pt(&runtime.playhead_pill, x, y);
}

void director_timeline_draw_playhead(const DirectorViewState &state,
                   DirectorTimelineRuntime *runtime,
                   const float bottom,
                   const float top)
{
  /* An off-screen playhead is not grabbable, and an empty rect has to be
   * one nothing is inside — a zeroed rctf contains the origin. */
  runtime->playhead_line = {1.0f, -1.0f, 1.0f, -1.0f};
  runtime->playhead_pill = {1.0f, -1.0f, 1.0f, -1.0f};
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  const float x = runtime->viewport_bounds.xmin +
                  (state.frame_current - runtime->view_start_frame) /
                      runtime->view_span_frames * width;
  if (x < runtime->viewport_bounds.xmin || x > runtime->viewport_bounds.xmax) {
    return;
  }
  const float pill_h = DIRECTOR_PLAYHEAD_PILL_H * UI_SCALE_FAC;
  const float pill_y = top - pill_h;
  /* The line is a handle: a hairline is not something a pointer can
   * catch, so the grab band is padded either side of it. */
  const float grab = PLAYHEAD_GRAB_PAD * UI_SCALE_FAC;
  runtime->playhead_line = {x - grab, x + grab, bottom, pill_y};
  director_timeline_draw_rect(x - 0.5f * UI_SCALE_FAC,
            bottom,
            x + 0.5f * UI_SCALE_FAC,
            pill_y + 2.0f * UI_SCALE_FAC,
            PLAYHEAD_COLOR);

  /* The pill reads in the ruler's unit. In FRAMES that is the scene's own
   * frame number — the one Blender's timeline shows — because a pill reading
   * "0.00" beside a timeline reading 1 is the same playhead disagreeing with
   * itself. */
  char label[32];
  if (state.ruler_frames) {
    BLI_snprintf(label, sizeof(label), "%d", state.frame_current);
  }
  else {
    const float seconds = (state.frame_current - state.scene_frame_start) /
                          std::max(state.fps, 0.001f);
    BLI_snprintf(label, sizeof(label), "%.2f", seconds);
  }
  const float font_size = 12.0f * UI_SCALE_FAC;
  const float pill_w = director_timeline_text_width(label, font_size) + 22.0f * UI_SCALE_FAC;
  const float center = std::clamp(x,
                                  runtime->viewport_bounds.xmin + pill_w * 0.5f,
                                  runtime->viewport_bounds.xmax - pill_w * 0.5f);
  const rctf pill = {center - pill_w * 0.5f, center + pill_w * 0.5f, pill_y, top};
  runtime->playhead_pill = pill;
  director_timeline_draw_round_rect(pill, pill_h * 0.42f, PLAYHEAD_COLOR);
  director_timeline_draw_text(label,
            center - director_timeline_text_width(label, font_size) * 0.5f,
            pill_y + (pill_h - font_size) * 0.5f,
            font_size,
            PLAYHEAD_TEXT_COLOR);
}

}  // namespace blender
