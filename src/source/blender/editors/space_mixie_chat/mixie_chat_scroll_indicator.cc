/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Scroll-to-bottom floating indicator for the chat main region.
 * Appears when the user scrolls up from the newest messages.
 * Draws in screen-space after ui::view2d_view_restore().
 */

#include <algorithm>
#include <cmath>

#include "BLI_rect.h"
#include "BLI_time.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "UI_view2d.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Constants
 * \{ */

static const float INDICATOR_WIDTH = 36.0f;
static const float INDICATOR_HEIGHT = 36.0f;
static const float INDICATOR_BOTTOM_MARGIN = 16.0f;
static const float INDICATOR_CORNER_RADIUS = 18.0f; /* Fully circular */
static const float FADE_DURATION = 0.2;             /* seconds */
static const float BOUNCE_DURATION = 0.4;           /* seconds */
static const float BOUNCE_SCALE = 1.2f;
static const float SCROLL_THRESHOLD = 30.0f; /* pixels from bottom to consider "at bottom" */
static const float CHEVRON_SIZE = 6.0f;      /* half-size of the chevron */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Animation Helpers
 * \{ */

/** Ease-out cubic: decelerates to zero velocity. */
static float ease_out_cubic(float t)
{
  t = std::max(0.0f, std::min(1.0f, t));
  float t1 = t - 1.0f;
  return t1 * t1 * t1 + 1.0f;
}

/** Bounce-out: quick scale up then settle to 1.0. */
static float bounce_scale(float t)
{
  if (t >= 1.0f) {
    return 1.0f;
  }
  /* Overshoot then settle: sin curve that peaks at BOUNCE_SCALE */
  float peak = BOUNCE_SCALE - 1.0f;
  return 1.0f + peak * std::sin(t * M_PI) * (1.0f - t);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name State Management
 * \{ */

void mixie_chat_update_scroll_indicator(SpaceMixieChat *smixie,
                                        ARegion *region,
                                        int msg_count)
{
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  View2D *v2d = &region->v2d;

  /* Determine if user is scrolled away from bottom */
  float content_height = BLI_rctf_size_y(&v2d->tot);
  float view_height = BLI_rctf_size_y(&v2d->cur);
  bool content_fits = (content_height <= view_height);
  bool at_bottom = content_fits || (v2d->cur.ymin <= v2d->tot.ymin + SCROLL_THRESHOLD);
  bool should_show = !at_bottom && msg_count > 0;

  double now = BLI_time_now_seconds();

  if (should_show && !rt->scroll_indicator_visible) {
    /* Start fade-in */
    rt->scroll_indicator_visible = true;
    rt->scroll_indicator_fading_in = true;
    rt->scroll_indicator_fade_start = now;
  }
  else if (!should_show && rt->scroll_indicator_visible) {
    /* Start fade-out */
    rt->scroll_indicator_fading_in = false;
    rt->scroll_indicator_fade_start = now;
  }

  /* If fade-out completed, mark invisible */
  if (!rt->scroll_indicator_fading_in && rt->scroll_indicator_visible) {
    double elapsed = now - rt->scroll_indicator_fade_start;
    if (elapsed >= FADE_DURATION) {
      rt->scroll_indicator_visible = false;
    }
  }
}

void mixie_chat_trigger_scroll_bounce(SpaceMixieChat *smixie)
{
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (rt->scroll_indicator_visible) {
    rt->scroll_indicator_bounce_start = BLI_time_now_seconds();
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

void mixie_chat_draw_scroll_indicator(SpaceMixieChat *smixie, ARegion *region)
{
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (!rt->scroll_indicator_visible) {
    return;
  }

  double now = BLI_time_now_seconds();

  /* Calculate fade alpha */
  float alpha;
  {
    double elapsed = now - rt->scroll_indicator_fade_start;
    float t = float(elapsed / FADE_DURATION);
    if (rt->scroll_indicator_fading_in) {
      alpha = ease_out_cubic(t);
    }
    else {
      alpha = 1.0f - ease_out_cubic(t);
    }
    alpha = std::max(0.0f, std::min(1.0f, alpha));
  }

  if (alpha <= 0.01f) {
    return;
  }

  /* Calculate bounce scale */
  float scale = 1.0f;
  if (rt->scroll_indicator_bounce_start > 0.0) {
    double bounce_elapsed = now - rt->scroll_indicator_bounce_start;
    float bt = float(bounce_elapsed / BOUNCE_DURATION);
    if (bt < 1.0f) {
      scale = bounce_scale(bt);
    }
    else {
      rt->scroll_indicator_bounce_start = 0.0;
    }
  }

  /* Position: bottom-center of the region in screen-space */
  int winx = region->winx;
  float cx = float(winx) / 2.0f;
  float cy = INDICATOR_BOTTOM_MARGIN + INDICATOR_HEIGHT / 2.0f;

  float half_w = (INDICATOR_WIDTH / 2.0f) * scale;
  float half_h = (INDICATOR_HEIGHT / 2.0f) * scale;

  rctf pill_rect;
  pill_rect.xmin = cx - half_w;
  pill_rect.xmax = cx + half_w;
  pill_rect.ymin = cy - half_h;
  pill_rect.ymax = cy + half_h;

  /* Store bounds for hit testing (unscaled, for stable click targets) */
  rt->scroll_indicator_bounds.xmin = cx - INDICATOR_WIDTH / 2.0f;
  rt->scroll_indicator_bounds.xmax = cx + INDICATOR_WIDTH / 2.0f;
  rt->scroll_indicator_bounds.ymin = cy - INDICATOR_HEIGHT / 2.0f;
  rt->scroll_indicator_bounds.ymax = cy + INDICATOR_HEIGHT / 2.0f;

  /* Get theme colors */
  float bg_color[4], arrow_color[4];
  chat_ui_get_button_bg_color(bg_color);
  chat_ui_get_button_text_color(arrow_color);
  bg_color[3] = alpha * 0.9f;
  arrow_color[3] = alpha;

  /* Draw pill background */
  GPU_blend(GPU_BLEND_ALPHA);
  chat_ui_draw_rounded_rect(&pill_rect, INDICATOR_CORNER_RADIUS * scale, bg_color);

  /* Draw subtle border */
  float border_color[4] = {arrow_color[0], arrow_color[1], arrow_color[2], alpha * 0.2f};
  chat_ui_draw_rounded_rect_outline(&pill_rect, INDICATOR_CORNER_RADIUS * scale, border_color, 1.0f);

  /* Draw downward chevron (V shape) */
  float chevron_size = CHEVRON_SIZE * scale;
  float chevron_cx = cx;
  float chevron_cy = cy + chevron_size * 0.2f; /* Slight upward offset for visual centering */

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(arrow_color);
  GPU_line_width(2.0f * scale);

  immBegin(GPU_PRIM_LINE_STRIP, 3);
  immVertex2f(pos, chevron_cx - chevron_size, chevron_cy + chevron_size * 0.5f);
  immVertex2f(pos, chevron_cx, chevron_cy - chevron_size * 0.5f);
  immVertex2f(pos, chevron_cx + chevron_size, chevron_cy + chevron_size * 0.5f);
  immEnd();

  immUnbindProgram();
  GPU_line_width(1.0f);
  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Click Handling
 * \{ */

bool mixie_chat_handle_scroll_indicator_click(SpaceMixieChat *smixie,
                                               ARegion *region,
                                               float mouse_x,
                                               float mouse_y)
{
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (!rt->scroll_indicator_visible) {
    return false;
  }

  if (!BLI_rctf_isect_pt(&rt->scroll_indicator_bounds, mouse_x, mouse_y)) {
    return false;
  }

  /* Scroll to bottom */
  View2D *v2d = &region->v2d;
  float view_height = BLI_rctf_size_y(&v2d->cur);
  v2d->cur.ymin = v2d->tot.ymin;
  v2d->cur.ymax = v2d->cur.ymin + view_height;

  return true;
}

/** \} */
}  // namespace blender
