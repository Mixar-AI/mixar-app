/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Out-of-credits banner: shared state between the modal operator
 * (credits_banner.cc) and its window draw callback (credits_banner_draw.cc).
 * Layout is a pure function of the window size and the banner image's
 * aspect, so the click handler, the painter and the QA targets can never
 * disagree about where a button is.
 */

#pragma once

#include <string>

#include "BLI_rect.h"

namespace blender {

struct wmTimer;
struct wmWindow;
namespace gpu {
class Texture;
}

namespace ui::credits_banner {

/** Hit targets, in the order the modal reports them. */
enum Target {
  TARGET_NONE = -1,
  TARGET_UPGRADE = 0,
  TARGET_REFER = 1,
  TARGET_CREATOR = 2,
  TARGET_CLOSE = 3,
  TARGET_COUNT = 4,
};

/** Action names sent to `mixar.credits_banner_action` (Python owns the URLs). */
const char *target_action(Target target);
/** Visible label of a button target (QA text matching uses the same string). */
const char *target_label(Target target);

struct Layout {
  rctf card;                   /* the banner image, window pixels */
  rctf targets[TARGET_COUNT];  /* buttons + close chip */
  rctf badge;                  /* "10K+ followers" chip on the Creator button */
  float radius;                /* card corner radius */
  float button_h;
};

struct State {
  wmWindow *win = nullptr;
  void *draw_handle = nullptr;
  wmTimer *timer = nullptr;
  std::string image_path;
  gpu::Texture *texture = nullptr;
  int image_w = 1744;
  int image_h = 1168;
  bool image_failed = false;

  double opened_at = 0.0;
  double closing_at = 0.0; /* 0 while open */
  int hover = TARGET_NONE;
  int pressed = TARGET_NONE;
  float hover_mix[TARGET_COUNT] = {0.0f, 0.0f, 0.0f, 0.0f};
};

/** Seconds for the entrance and exit animations. */
constexpr double ENTER_SECONDS = 0.34;
constexpr double EXIT_SECONDS = 0.16;

/** 0 → 1 appearance factor (eased), folding in the exit animation. */
float appear_factor(const State &state, double now);

Layout layout_compute(const State &state, float appear);
Target hit_test(const Layout &layout, float x, float y);

/** Window draw callback (WM_draw_cb_activate). */
void draw(const wmWindow *win, void *customdata);
/** Free the GPU texture; call with a live GPU context (operator exit). */
void texture_free(State &state);

/** The banner currently open, if any (one per session). */
State *active();

}  // namespace ui::credits_banner
}  // namespace blender
