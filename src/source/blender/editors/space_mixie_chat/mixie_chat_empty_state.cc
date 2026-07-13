/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Empty state drawing for chat UI.
 * Renders animated prompt bubbles when the chat has no messages,
 * with staggered fade-in and slide-up entrance animation.
 * Split from mixie_chat_messages.cc for modularity.
 */

#include <cstring>

#include "BLI_rect.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "BLF_api.hh"

#include "ED_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Empty Chat Prompt Data
 * \{ */

/**
 * Prompt texts shown when chat is empty.
 */
static const char *g_empty_prompt_texts[CHAT_EMPTY_PROMPT_COUNT] = {
    "Tell me about the features in Mixar",
    "Generate a futuristic sci-fi character concept",
    "Place and pack islands across 2 UDIMs",
    "Generate a 3D model of the image selected in moodboard",
};

/**
 * Chat modes for each empty prompt.
 * Used to automatically switch chat mode when a prompt is clicked.
 */
const char *g_empty_prompt_modes[CHAT_EMPTY_PROMPT_COUNT] = {
    "AGENT",    /* "Tell me about the features in Mixar" */
    "GENERATE", /* "Generate a futuristic sci-fi character concept" */
    "AGENT",    /* "Place and pack islands across 2 UDIMs" */
    "GENERATE", /* "Generate a 3D model of the image selected in moodboard" */
};

/**
 * Generate sub-types for each empty prompt (only applies when mode is GENERATE).
 * Values are generation-catalog service keys (the catalog-driven
 * mixie_chat_generate_type identifiers). Empty string means no generate
 * type should be set.
 */
const char *g_empty_prompt_generate_types[CHAT_EMPTY_PROMPT_COUNT] = {
    "",          /* "Tell me about..." - not GENERATE mode */
    "image_gen", /* "Generate a futuristic sci-fi character concept" */
    "",          /* "Place and pack islands..." - not GENERATE mode */
    "model_3d",  /* "Generate a 3D model..." */
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Empty State Drawing
 * \{ */

void mixie_chat_draw_empty_state(const bContext *C,
                                  ARegion *region,
                                  SpaceMixieChat *smixie,
                                  const ChatLayoutMetrics &metrics,
                                  int winx,
                                  int winy)
{
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  ScrArea *area = CTX_wm_area(C);

  wmWindow *prompt_win = CTX_wm_window(C);
  float prompt_mouse_x = -1000.0f;
  float prompt_mouse_y = -1000.0f;
  if (prompt_win) {
    prompt_mouse_x = float(prompt_win->eventstate->xy[0] - region->winrct.xmin);
    prompt_mouse_y = float(prompt_win->eventstate->xy[1] - region->winrct.ymin);
  }

  /* Get theme colors */
  float outline_color[4];
  float hover_color[4];
  float text_color[4];
  chat_ui_get_placeholder_text_color(outline_color);
  chat_ui_get_button_hover_color(hover_color);
  text_color[0] = outline_color[0];
  text_color[1] = outline_color[1];
  text_color[2] = outline_color[2];
  text_color[3] = 1.0f;

  /* Layout parameters */
  const float bubble_padding_h = 20.0f * metrics.scale_factor;
  const float bubble_padding_v = 12.0f * metrics.scale_factor;
  const float bubble_spacing = 12.0f * metrics.scale_factor;
  const float corner_radius = chat_ui_get_corner_radius() * metrics.scale_factor;
  const float line_width = 1.5f;
  const float max_bubble_width = float(winx) * 0.7f;

  const int font_id = BLF_default();
  BLF_size(font_id, metrics.font_size);

  float bubble_heights[CHAT_EMPTY_PROMPT_COUNT];
  float bubble_widths[CHAT_EMPTY_PROMPT_COUNT];
  float total_prompt_height = 0.0f;
  float max_bubble_width_found = 0.0f;

  /* First pass: calculate individual dimensions and find max width */
  for (int i = 0; i < CHAT_EMPTY_PROMPT_COUNT; i++) {
    float text_width, text_height;
    float content_width = max_bubble_width - bubble_padding_h * 2.0f;
    chat_ui_calc_text_bounds(g_empty_prompt_texts[i], content_width, metrics.font_size, 0,
                             &text_width, &text_height);
    bubble_heights[i] = text_height + bubble_padding_v * 2.0f;
    bubble_widths[i] = text_width + bubble_padding_h * 2.0f + 4.0f;

    if (bubble_widths[i] > max_bubble_width) {
      bubble_widths[i] = max_bubble_width;
    }

    if (bubble_widths[i] > max_bubble_width_found) {
      max_bubble_width_found = bubble_widths[i];
    }

    total_prompt_height += bubble_heights[i];
    if (i < CHAT_EMPTY_PROMPT_COUNT - 1) {
      total_prompt_height += bubble_spacing;
    }
  }

  float uniform_bubble_width = max_bubble_width_found;

  /* Heading text */
  const char *heading_text = "Hey friend! How can I help today?";
  const float heading_spacing = 24.0f * metrics.scale_factor;
  int heading_font_size = int(float(metrics.font_size) * 1.2f);

  float heading_width, heading_height;
  chat_ui_calc_text_bounds(heading_text, float(winx), heading_font_size, 0,
                           &heading_width, &heading_height);

  float total_height_with_heading = heading_height + heading_spacing + total_prompt_height;

  /* Skip the whole empty state when it can't be shown without
   * clipping. The agent bubble window can be very short (and the
   * mixie chat editor can be dragged tiny too) — a half-clipped
   * heading or partially-cut bubbles look broken, so render
   * nothing instead. The empty state is purely decorative; the
   * composer footer is always visible regardless.
   *
   * Clear the cached bubble bounds so cursor/click handlers in
   * mixie_chat_main_region.cc and mixie_chat_hit_testing.cc don't
   * fire on stale rectangles from a previous (larger) layout. */
  if (total_height_with_heading > float(winy)) {
    rt->empty_prompts_visible = false;
    for (int i = 0; i < CHAT_EMPTY_PROMPT_COUNT; i++) {
      rt->empty_prompts[i].bounds.xmin = 0.0f;
      rt->empty_prompts[i].bounds.xmax = 0.0f;
      rt->empty_prompts[i].bounds.ymin = 0.0f;
      rt->empty_prompts[i].bounds.ymax = 0.0f;
      rt->empty_prompts[i].is_hovered = false;
    }
    return;
  }

  rt->empty_prompts_visible = true;
  float start_y = (float(winy) + total_height_with_heading) / 2.0f;

  /* Staggered fade-in + slide-up animation.
   * Heading is element 0, bubbles are elements 1..4.
   * Each element animates over `elem_dur` seconds with `stagger` delay. */
  double anim_now = BLI_time_now_seconds();
  if (rt->empty_anim_reset) {
    rt->empty_anim_start = anim_now;
    rt->empty_anim_reset = false;
  }
  double anim_elapsed = anim_now - rt->empty_anim_start;
  const double elem_dur = 0.25;
  const double stagger = 0.08;
  const float slide_px = 12.0f * metrics.scale_factor;

  /* Ease-out cubic: fast start, gentle deceleration */
  auto ease_progress = [&](int elem_idx) -> float {
    double t = (anim_elapsed - stagger * elem_idx) / elem_dur;
    if (t < 0.0) return 0.0f;
    if (t > 1.0) return 1.0f;
    float f = float(t);
    return 1.0f - (1.0f - f) * (1.0f - f) * (1.0f - f);
  };

  /* Draw heading (animation element 0) */
  float h_prog = ease_progress(0);
  float h_yoff = slide_px * (1.0f - h_prog);
  float heading_x = (float(winx) - heading_width) / 2.0f;
  float heading_y = start_y - heading_height;
  float anim_heading_col[4] = {text_color[0], text_color[1], text_color[2], h_prog};
  BLF_size(font_id, heading_font_size);
  BLF_color4fv(font_id, anim_heading_col);
  BLF_position(font_id, heading_x, heading_y - h_yoff, 0.0f);
  BLF_draw(font_id, heading_text, strlen(heading_text));

  BLF_size(font_id, metrics.font_size);
  start_y = heading_y - heading_spacing;

  /* Draw each prompt bubble (animation elements 1..4) */
  for (int i = 0; i < CHAT_EMPTY_PROMPT_COUNT; i++) {
    float bubble_x = (float(winx) - uniform_bubble_width) / 2.0f;
    float bubble_y = start_y - bubble_heights[i];

    /* Store logical bounds for hit testing */
    rt->empty_prompts[i].text = g_empty_prompt_texts[i];
    rt->empty_prompts[i].bounds.xmin = bubble_x;
    rt->empty_prompts[i].bounds.xmax = bubble_x + uniform_bubble_width;
    rt->empty_prompts[i].bounds.ymin = bubble_y;
    rt->empty_prompts[i].bounds.ymax = start_y;

    bool is_hovered = BLI_rctf_isect_pt(&rt->empty_prompts[i].bounds,
                                          prompt_mouse_x, prompt_mouse_y);
    rt->empty_prompts[i].is_hovered = is_hovered;

    /* Compute animation for this bubble */
    float b_prog = ease_progress(i + 1);
    float b_yoff = slide_px * (1.0f - b_prog);

    /* Animated outline color */
    float *base_color = is_hovered ? hover_color : outline_color;
    float anim_outline[4] = {base_color[0], base_color[1], base_color[2],
                              base_color[3] * b_prog};

    rctf draw_bounds;
    draw_bounds.xmin = bubble_x;
    draw_bounds.xmax = bubble_x + uniform_bubble_width;
    draw_bounds.ymin = bubble_y - b_yoff;
    draw_bounds.ymax = start_y - b_yoff;
    chat_ui_draw_rounded_rect_outline(&draw_bounds, corner_radius, anim_outline, line_width);

    /* Animated text color */
    float *base_text = is_hovered ? hover_color : text_color;
    float anim_text_col[4] = {base_text[0], base_text[1], base_text[2],
                               base_text[3] * b_prog};

    rctf text_rect;
    text_rect.xmin = bubble_x + bubble_padding_h;
    text_rect.xmax = bubble_x + uniform_bubble_width - bubble_padding_h;
    text_rect.ymin = bubble_y + bubble_padding_v - b_yoff;
    text_rect.ymax = start_y - bubble_padding_v - b_yoff;
    chat_ui_draw_text_wrapped(g_empty_prompt_texts[i], &text_rect, metrics.font_size, 0,
                              anim_text_col);

    start_y = bubble_y - bubble_spacing;
  }

  /* Tag redraw while animation is still playing */
  double total_anim_time = stagger * CHAT_EMPTY_PROMPT_COUNT + elem_dur;
  if (anim_elapsed < total_anim_time && area) {
    ED_area_tag_redraw(area);
  }

  /* Set cursor to hand when hovering over any bubble */
  bool any_hovered = false;
  for (int i = 0; i < CHAT_EMPTY_PROMPT_COUNT; i++) {
    if (rt->empty_prompts[i].is_hovered) {
      any_hovered = true;
      break;
    }
  }
  if (prompt_win) {
    WM_cursor_set(prompt_win, any_hovered ? WM_CURSOR_HAND : WM_CURSOR_DEFAULT);
  }
}

/** \} */
