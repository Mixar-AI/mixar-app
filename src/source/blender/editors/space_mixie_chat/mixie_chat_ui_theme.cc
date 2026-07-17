/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Theme accessors, color getters, and style builders for chat UI.
 * Reads ThemeSpace values with hardcoded fallbacks.
 */

#include "BLF_api.hh"

#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

#include "UI_interface.hh"

#include "mixie_chat_ui_types.hh"

/* -------------------------------------------------------------------- */
/** \name Theme Helpers
 * \{ */

static const ThemeSpace *chat_ui_get_theme_space()
{
  bTheme *btheme = static_cast<bTheme *>(U.themes.first);
  if (btheme) {
    return &btheme->space_mixie_chat;
  }
  return nullptr;
}

static void theme_color_to_float(const uchar color[4], float out[4])
{
  out[0] = float(color[0]) / 255.0f;
  out[1] = float(color[1]) / 255.0f;
  out[2] = float(color[2]) / 255.0f;
  out[3] = float(color[3]) / 255.0f;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Theme Size/Spacing Getters
 * \{ */

float chat_ui_get_font_size()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_font_size : CHAT_BASE_FONT_SIZE;
}

float chat_ui_get_label_font_size()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_label_font_size : CHAT_BASE_LABEL_FONT_SIZE;
}

float chat_ui_get_padding()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_padding : CHAT_BASE_PADDING;
}

float chat_ui_get_bubble_spacing()
{
  /* Flat layout: one modular unit between blocks of a turn — a consistent,
   * tight rhythm so the turn reads as a single composed unit. Forced over
   * the theme. */
  return 8.0f;
}

float chat_ui_get_bubble_h_padding()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_bubble_h_padding : CHAT_BASE_BUBBLE_H_PADDING;
}

float chat_ui_get_bubble_v_padding()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_bubble_v_padding : CHAT_BASE_BUBBLE_V_PADDING;
}

float chat_ui_get_corner_radius()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_corner_radius : CHAT_BASE_CORNER_RADIUS;
}

float chat_ui_get_label_height()
{
  /* Flat layout: the sender label sits closer to its message. Forced tighter
   * than the bubble-era default to remove the large header gap. */
  return 13.0f;
}

float chat_ui_get_image_max_width()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_image_max_width : CHAT_BASE_IMAGE_MAX_WIDTH;
}

float chat_ui_get_image_max_height()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_image_max_height : CHAT_BASE_IMAGE_MAX_HEIGHT;
}

float chat_ui_get_image_margin()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_image_margin : CHAT_BASE_IMAGE_MARGIN;
}

float chat_ui_get_image_corner_radius()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_image_corner_radius : CHAT_BASE_IMAGE_CORNER_RADIUS;
}

float chat_ui_get_action_button_height()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_action_button_height : 24.0f;
}

float chat_ui_get_action_button_padding()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_action_button_padding : 8.0f;
}

float chat_ui_get_action_button_spacing()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_action_button_spacing : 6.0f;
}

float chat_ui_get_action_button_corner_radius()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_action_button_corner_radius : 4.0f;
}

float chat_ui_get_footer_general_padding()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_footer_general_padding : 6.0f;
}

float chat_ui_get_main_footer_gap()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_main_footer_gap : 4.0f;
}

float chat_ui_get_send_button_size()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_send_button_size : 40.0f;
}

float chat_ui_get_attach_button_size()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_attach_button_size : 40.0f;
}

float chat_ui_get_footer_button_row_height()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_footer_button_row_height : 44.0f;
}

float chat_ui_get_thumbnail_border_radius()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_thumbnail_border_radius : 8.0f;
}

float chat_ui_get_thumbnail_padding()
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  return ts ? ts->chat_thumbnail_padding : 4.0f;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Layout Metrics & Style Builders
 * \{ */

ChatLayoutMetrics chat_ui_get_layout_metrics()
{
  ChatLayoutMetrics m;
  m.scale_factor = UI_SCALE_FAC;
  m.padding = chat_ui_get_padding() * m.scale_factor;
  m.bubble_spacing = chat_ui_get_bubble_spacing() * m.scale_factor;
  m.label_height = chat_ui_get_label_height() * m.scale_factor;
  m.max_bubble_width_ratio = CHAT_MAX_BUBBLE_WIDTH_RATIO;
  m.font_size = int(chat_ui_get_font_size() * m.scale_factor);
  m.label_font_size = int(chat_ui_get_label_font_size() * m.scale_factor);
  return m;
}

ChatBubbleStyle chat_ui_get_user_bubble_style(const ChatLayoutMetrics *metrics)
{
  ChatBubbleStyle style;
  style.corner_radius = chat_ui_get_corner_radius() * metrics->scale_factor;
  style.h_padding = chat_ui_get_bubble_h_padding() * metrics->scale_factor;
  style.v_padding = chat_ui_get_bubble_v_padding() * metrics->scale_factor;
  style.font_size = metrics->font_size;
  style.is_right_aligned = true;

  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_user_bubble, style.bg_color);
    theme_color_to_float(ts->chat_user_text, style.text_color);
    theme_color_to_float(ts->chat_bubble_hover, style.hover_color);
  }
  else {
    style.bg_color[0] = 0.22f;
    style.bg_color[1] = 0.47f;
    style.bg_color[2] = 0.78f;
    style.bg_color[3] = 0.95f;
    style.text_color[0] = 1.0f;
    style.text_color[1] = 1.0f;
    style.text_color[2] = 1.0f;
    style.text_color[3] = 1.0f;
    style.hover_color[0] = 0.3f;
    style.hover_color[1] = 0.85f;
    style.hover_color[2] = 0.95f;
    style.hover_color[3] = 0.95f;
  }

  /* Flat minimal palette — a clean dark pill for the user message, overriding
   * the theme so the product look is consistent across themes. */
  style.bg_color[0] = 0.165f;
  style.bg_color[1] = 0.175f;
  style.bg_color[2] = 0.200f;
  style.bg_color[3] = 1.0f;
  style.text_color[0] = 0.96f;
  style.text_color[1] = 0.96f;
  style.text_color[2] = 0.97f;
  style.text_color[3] = 1.0f;

  return style;
}

ChatBubbleStyle chat_ui_get_agent_bubble_style(const ChatLayoutMetrics *metrics)
{
  ChatBubbleStyle style;
  style.corner_radius = chat_ui_get_corner_radius() * metrics->scale_factor;
  style.h_padding = chat_ui_get_bubble_h_padding() * metrics->scale_factor;
  style.v_padding = chat_ui_get_bubble_v_padding() * metrics->scale_factor;
  style.font_size = metrics->font_size;
  style.is_right_aligned = false;

  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_agent_bubble, style.bg_color);
    theme_color_to_float(ts->chat_agent_text, style.text_color);
    theme_color_to_float(ts->chat_bubble_hover, style.hover_color);
  }
  else {
    style.bg_color[0] = 0.25f;
    style.bg_color[1] = 0.25f;
    style.bg_color[2] = 0.25f;
    style.bg_color[3] = 0.95f;
    style.text_color[0] = 1.0f;
    style.text_color[1] = 1.0f;
    style.text_color[2] = 1.0f;
    style.text_color[3] = 1.0f;
    style.hover_color[0] = 0.3f;
    style.hover_color[1] = 0.85f;
    style.hover_color[2] = 0.95f;
    style.hover_color[3] = 0.95f;
  }

  /* Flat minimal palette — agent prose flows directly on the editor background
   * with NO card (fully transparent fill), the way Cowork / Perplexity read.
   * Special blocks (steps / thinking / todo) still get a subtle container via
   * chat_ui_get_prompt_button_color. */
  style.bg_color[0] = 0.0f;
  style.bg_color[1] = 0.0f;
  style.bg_color[2] = 0.0f;
  style.bg_color[3] = 0.0f;
  style.text_color[0] = 0.90f;
  style.text_color[1] = 0.91f;
  style.text_color[2] = 0.93f;
  style.text_color[3] = 1.0f;

  return style;
}

ChatImageStyle chat_ui_get_image_style(const ChatLayoutMetrics *metrics)
{
  ChatImageStyle style;
  style.max_width = chat_ui_get_image_max_width() * metrics->scale_factor;
  style.max_height = chat_ui_get_image_max_height() * metrics->scale_factor;
  style.margin = chat_ui_get_image_margin() * metrics->scale_factor;
  style.corner_radius = chat_ui_get_image_corner_radius() * metrics->scale_factor;
  return style;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Theme Color Getters
 * \{ */

void chat_ui_get_button_bg_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_button_bg, out_color);
  }
  else {
    out_color[0] = 0.3f; out_color[1] = 0.3f; out_color[2] = 0.3f; out_color[3] = 0.6f;
  }
}

void chat_ui_get_button_text_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_button_text, out_color);
  }
  else {
    out_color[0] = 0.8f; out_color[1] = 0.8f; out_color[2] = 0.8f; out_color[3] = 1.0f;
  }
}

void chat_ui_get_label_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_label_color, out_color);
  }
  else {
    out_color[0] = 0.7f; out_color[1] = 0.7f; out_color[2] = 0.7f; out_color[3] = 1.0f;
  }
}

void chat_ui_get_prompt_button_color(float out_color[4])
{
  /* Flat minimal palette — special blocks (steps / thinking / todo / plan) sit
   * in a subtle container just a touch above the editor background, instead of
   * a heavy filled card. Forced over the theme for a consistent product look. */
  out_color[0] = 0.125f;
  out_color[1] = 0.135f;
  out_color[2] = 0.155f;
  out_color[3] = 1.0f;
}

void chat_ui_get_placeholder_text_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_placeholder_text, out_color);
  }
  else {
    out_color[0] = 0.5f; out_color[1] = 0.5f; out_color[2] = 0.5f; out_color[3] = 1.0f;
  }
}

void chat_ui_get_thumbnail_border_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_thumbnail_border, out_color);
  }
  else {
    out_color[0] = 0.4f; out_color[1] = 0.4f; out_color[2] = 0.4f; out_color[3] = 1.0f;
  }
}

void chat_ui_get_button_hover_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_button_hover, out_color);
  }
  else {
    out_color[0] = 0.4f; out_color[1] = 0.55f; out_color[2] = 0.7f; out_color[3] = 1.0f;
  }
}

void chat_ui_get_history_row_hover_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  /* Zero alpha means "unset" (prefs saved before the field existed load it
   * as zero, and the Python bootstrap seed may not have run yet) — fall
   * back to the default subtle white wash rather than an invisible hover. */
  if (ts && ts->chat_history_row_hover[3] != 0) {
    theme_color_to_float(ts->chat_history_row_hover, out_color);
  }
  else {
    out_color[0] = 1.0f; out_color[1] = 1.0f; out_color[2] = 1.0f; out_color[3] = 0.07f;
  }
}

void chat_ui_get_toggle_on_color(float out_color[4])
{
  const ThemeSpace *ts = chat_ui_get_theme_space();
  if (ts) {
    theme_color_to_float(ts->chat_plan_toggle_on, out_color);
  }
  else {
    out_color[0] = 0.25f; out_color[1] = 0.35f; out_color[2] = 0.50f; out_color[3] = 1.0f;
  }
}

void chat_ui_get_toggle_off_color(float out_color[4])
{
  chat_ui_get_button_bg_color(out_color);
}

void chat_ui_get_toggle_knob_color(float out_color[4])
{
  chat_ui_get_button_text_color(out_color);
}

void chat_ui_get_toggle_label_color(float out_color[4])
{
  chat_ui_get_button_text_color(out_color);
}

/** \} */
