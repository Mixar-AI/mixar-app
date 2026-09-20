/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * High-level widget components for chat UI.
 * Provides bubbles, sender labels and action button handling.
 */

#include "BLI_rect.h"

#include "mixie_chat_ui_types.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Chat Bubble Widget
 * \{ */

float chat_ui_calc_bubble_height(const ChatBubbleStyle *style,
                                 const char *text,
                                 float max_width,
                                 float attachments_height)
{
  float text_width, text_height;
  float content_width = max_width - style->h_padding * 2.0f;

  chat_ui_calc_text_bounds(text, content_width, style->font_size, 0, &text_width, &text_height);

  return text_height + attachments_height + style->v_padding * 2.0f;
}

float chat_ui_draw_bubble(const ChatBubbleStyle *style,
                          const char *text,
                          float x,
                          float y,
                          float bubble_width,
                          float bubble_height,
                          float content_width,
                          float attachments_height,
                          const bool glass)
{
  /* Draw background. `glass` is the caller's word for "this bed is the user's
   * own card". The same helper also paints the agent's (transparent) prose and
   * the todo / action containers, which hand it a colour on purpose — a glass
   * bed would drop that colour for the CHAT row's tint. */
  rctf bubble_rect;
  bubble_rect.xmin = x;
  bubble_rect.xmax = x + bubble_width;
  bubble_rect.ymin = y;
  bubble_rect.ymax = y + bubble_height;

  if (glass) {
    chat_ui_draw_glass_pane(&bubble_rect, style->corner_radius, style->bg_color[3]);
  }
  else {
    chat_ui_draw_rounded_rect(&bubble_rect, style->corner_radius, style->bg_color);
  }

  /* Draw text inside bubble using the SAME content_width used for measurement
   * to ensure consistent text wrapping. This is critical - the wrap width during
   * drawing must match the wrap width used in chat_ui_calc_text_bounds(). */

  /* Only draw text if provided (allows drawing bubble background only) */
  if (text && text[0] != '\0') {
    /* Calculate actual text height to vertically center it */
    float text_width, text_height;
    chat_ui_calc_text_bounds(text, content_width, style->font_size, 0, &text_width, &text_height);

    /* When there are attachments, text should be at the bottom of the bubble.
     * When no attachments, center the text vertically */
    float text_area_height = bubble_height - attachments_height - (style->v_padding * 2.0f);
    float vertical_offset = 0.0f;
    
    if (attachments_height > 0) {
      /* With attachments: position text at the bottom of bubble */
      vertical_offset = 0.0f;  /* No offset - text starts right after bottom padding */
    } else {
      /* No attachments: center text vertically in bubble */
      vertical_offset = (text_area_height - text_height) / 2.0f;
    }

    rctf text_rect;
    text_rect.xmin = x + style->h_padding;
    text_rect.xmax = x + style->h_padding + content_width;  /* Use content_width, not bubble_width */
    text_rect.ymin = y + style->v_padding + vertical_offset;
    text_rect.ymax = text_rect.ymin + text_height;

    chat_ui_draw_text_wrapped(text, &text_rect, style->font_size, 0, style->text_color);
  }

  return bubble_height;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Action Buttons Widget
 * \{ */

/* Action button labels - compact icon + short text */
static const char *ACTION_LABEL_COPY = "\xe2\xa7\x89";    /* ⧉ (two joined squares - copy icon) */
static const char *ACTION_LABEL_COPIED = "\xe2\x9c\x94";  /* ✔ (checkmark - copied feedback) */
static const char *ACTION_LABEL_RETRY = "\xe2\x86\xbb";   /* ↻ (retry icon) */

/**
 * Draw a single compact action button and store its bounds for hit testing.
 * Returns the width of the drawn button.
 */
static float draw_compact_action_button(float btn_x,
                                         float btn_y,
                                         float btn_height,
                                         float btn_padding,
                                         float btn_radius,
                                         int font_size,
                                         const float *bg_color,
                                         const float *hover_color,
                                         const float *text_color,
                                         const char *label,
                                         ChatActionType type,
                                         bool is_hovered,
                                         ChatActionButton *out_buttons,
                                         int *button_count,
                                         float alpha)
{
  float text_width, text_height;
  chat_ui_calc_text_bounds(label, 200.0f, font_size, 0, &text_width, &text_height);
  float btn_width = text_width + btn_padding * 2.0f;

  rctf btn_rect;
  btn_rect.xmin = btn_x;
  btn_rect.xmax = btn_x + btn_width;
  btn_rect.ymin = btn_y;
  btn_rect.ymax = btn_y + btn_height;

  /* Draw button background with alpha (use hover color if hovered) */
  const float *base_bg = (is_hovered && hover_color) ? hover_color : bg_color;
  float draw_bg[4] = {base_bg[0], base_bg[1], base_bg[2], base_bg[3] * alpha};
  chat_ui_draw_rounded_rect(&btn_rect, btn_radius, draw_bg);

  /* Draw icon/label centered with alpha */
  float draw_text[4] = {text_color[0], text_color[1], text_color[2], text_color[3] * alpha};
  rctf text_rect;
  text_rect.xmin = btn_x + btn_padding;
  text_rect.xmax = btn_rect.xmax - btn_padding;
  text_rect.ymin = btn_y + (btn_height - text_height) / 2.0f;
  text_rect.ymax = text_rect.ymin + text_height;
  chat_ui_draw_text_wrapped(label, &text_rect, font_size, 0, draw_text);

  /* Store button info for hit testing */
  if (out_buttons && *button_count < CHAT_MAX_ACTION_BUTTONS) {
    /* Preserve existing hover state */
    bool prev_hovered = out_buttons[*button_count].is_hovered;
    out_buttons[*button_count].type = type;
    out_buttons[*button_count].bounds = btn_rect;
    out_buttons[*button_count].is_hovered = prev_hovered;
    out_buttons[*button_count].is_pressed = false;
    (*button_count)++;
  }

  return btn_width;
}

void chat_ui_draw_action_buttons(float bubble_x,
                                 float bubble_y,
                                 float bubble_width,
                                 float /*bubble_height*/,
                                 bool show_retry,
                                 float scale_factor,
                                 ChatActionButton *out_buttons,
                                 int *out_button_count,
                                 bool align_right,
                                 bool show_copied,
                                 float alpha)
{
  /* Compact sizing - smaller than theme defaults for icon-only buttons */
  float btn_height = 18.0f * scale_factor;
  float btn_padding = 5.0f * scale_factor;
  float btn_spacing = chat_ui_get_action_button_spacing() * scale_factor;
  float btn_radius = chat_ui_get_action_button_corner_radius() * scale_factor;
  int font_size = int(11 * scale_factor);

  /* Choose copy label based on feedback state */
  const char *copy_label = show_copied ? ACTION_LABEL_COPIED : ACTION_LABEL_COPY;

  /* Pre-calculate total buttons width for right alignment */
  float total_btns_width = 0.0f;
  if (align_right) {
    float tw, th;
    chat_ui_calc_text_bounds(copy_label, 200.0f, font_size, 0, &tw, &th);
    total_btns_width = tw + btn_padding * 2.0f;
    if (show_retry) {
      chat_ui_calc_text_bounds(ACTION_LABEL_RETRY, 200.0f, font_size, 0, &tw, &th);
      total_btns_width += btn_spacing + tw + btn_padding * 2.0f;
    }
  }

  /* Position buttons below the bubble */
  float btn_y = bubble_y - btn_height - btn_spacing;
  float btn_x = align_right ? (bubble_x + bubble_width - total_btns_width) : bubble_x;

  int button_count = 0;

  /* Get button colors from theme */
  float btn_bg[4];
  float btn_hover[4];
  float btn_text[4];
  chat_ui_get_button_bg_color(btn_bg);
  chat_ui_get_button_hover_color(btn_hover);
  chat_ui_get_button_text_color(btn_text);

  /* For copied feedback, use a green-tinted text color */
  float copied_text[4];
  if (show_copied) {
    copied_text[0] = 0.3f;
    copied_text[1] = 0.8f;
    copied_text[2] = 0.4f;
    copied_text[3] = 1.0f;
  }

  /* Check existing hover states before overwriting */
  bool copy_hovered = out_buttons ? out_buttons[0].is_hovered : false;
  bool retry_hovered = out_buttons ? out_buttons[1].is_hovered : false;

  /* Copy button (or "copied" feedback) */
  float copy_width = draw_compact_action_button(
      btn_x, btn_y, btn_height, btn_padding, btn_radius, font_size,
      btn_bg, btn_hover, show_copied ? copied_text : btn_text,
      copy_label, CHAT_ACTION_COPY, copy_hovered,
      out_buttons, &button_count, alpha);
  btn_x += copy_width + btn_spacing;

  /* Retry button (only for failed messages) */
  if (show_retry) {
    draw_compact_action_button(
        btn_x, btn_y, btn_height, btn_padding, btn_radius, font_size,
        btn_bg, btn_hover, btn_text,
        ACTION_LABEL_RETRY, CHAT_ACTION_RETRY, retry_hovered,
        out_buttons, &button_count, alpha);
  }

  if (out_button_count) {
    *out_button_count = button_count;
  }
}

int chat_ui_handle_action_click(float mouse_x,
                                float mouse_y,
                                const ChatActionButton *buttons,
                                int button_count)
{
  if (!buttons || button_count <= 0) {
    return CHAT_ACTION_NONE;
  }

  for (int i = 0; i < button_count; i++) {
    if (BLI_rctf_isect_pt(&buttons[i].bounds, mouse_x, mouse_y)) {
      return buttons[i].type;
    }
  }

  return CHAT_ACTION_NONE;
}

float chat_ui_get_action_buttons_height(float scale_factor)
{
  /* Match compact button sizing: 18px height + spacing */
  return (18.0f + chat_ui_get_action_button_spacing()) * scale_factor;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Sender Label Widget
 * \{ */

void chat_ui_draw_sender_label(const char *label,
                               float x,
                               float y,
                               const ChatLayoutMetrics *metrics,
                               bool is_user)
{
  /* Get label color from theme */
  float label_color[4];
  chat_ui_get_label_color(label_color);

  chat_ui_draw_label(label, x, y, metrics->label_font_size, 0, label_color, is_user);
}

/** \} */
}  // namespace blender
