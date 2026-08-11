/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Feedback row rendering and interaction handling for chat messages.
 */

#include <algorithm>
#include <cstdio>
#include <cstdlib>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_userdef_types.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "ED_screen.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

float mixie_chat_feedback_comment_input_height(PointerRNA *msg_ptr, const float input_width)
{
  /* Every value here must match widget_draw_text_multiline() /
   * ui_multiline_visible_lines() (interface_widgets.cc): the widget renders at
   * the plain widget font (points x 1.0), computes line_height as
   * BLF_height("Wg") + 2*pixelsize, and scrolls to keep the cursor within
   * floor(rect_height / line_height) lines. Measuring with any other font or
   * per-line height makes the button taller than the widget's line grid —
   * phantom lines the cursor can't reach. */
  uiFontStyle fstyle = UI_style_get()->widget;
  UI_fontstyle_set(&fstyle);
  const int fontid = fstyle.uifont_id;
  const int line_height = std::max(int(BLF_height(fontid, "Wg", 2) + 2.0f * U.pixelsize), 1);
  const int pad = int(4.0f * U.pixelsize); /* widget top inset; mirrored at bottom */

  int line_count = 1;
  const int text_len = g_msg_props.feedback_comment ?
      RNA_property_string_length(msg_ptr, g_msg_props.feedback_comment) : 0;
  if (text_len > 0) {
    char *text = static_cast<char *>(MEM_mallocN(size_t(text_len) + 1, __func__));
    RNA_property_string_get(msg_ptr, g_msg_props.feedback_comment, text);

    const int rect_width = std::max(int(input_width) - pad, 10);
    blender::Vector<blender::StringRef> lines = BLF_string_wrap(
        fontid,
        blender::StringRef(text, text_len),
        rect_width,
        BLFWrapMode(int(BLFWrapMode::Typographical) | int(BLFWrapMode::HardLimit)));
    line_count = std::max(1, int(lines.size()));
    /* Trailing newline shows as a virtual empty line in the widget. */
    if (text[text_len - 1] == '\n') {
      line_count++;
    }
    line_count = std::min(line_count, FEEDBACK_COMMENT_MAX_LINES);

    MEM_freeN(text);
  }

  /* N full lines plus the top inset and a matching bottom margin. The margins
   * stay below one line_height, so floor(height / line_height) == N and the
   * widget's scroll window agrees with what is visible. */
  return float(line_count * line_height + pad * 2);
}

/* Diagnostics for the star row (set MIXAR_FEEDBACK_DEBUG=1 and run from a
 * terminal): logs where bounds are written at draw time and where clicks land,
 * so a draw/hit-test mismatch can be pinpointed per surface (editor/bubble). */
static bool feedback_debug_enabled()
{
  static const bool enabled = getenv("MIXAR_FEEDBACK_DEBUG") != nullptr;
  return enabled;
}

static SpaceMixieChat *get_space_mixie_chat(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  if (area && (area->spacetype == SPACE_MIXIE_CHAT ||
               area->spacetype == SPACE_AGENT_BUBBLE))
  {
    return static_cast<SpaceMixieChat *>(area->spacedata.first);
  }
  return nullptr;
}

float chat_ui_get_feedback_top_gap(const ChatLayoutMetrics &metrics)
{
  /* Breathing room so the stars read as a separate affordance, not part of
   * the response text (one modular unit reads too tight there). */
  return metrics.bubble_spacing * 2.5f;
}

void mixie_chat_render_feedback(const bContext *C,
                                ARegion *region,
                                PointerRNA *msg_ptr,
                                const ChatLayoutMetrics &metrics,
                                const MessageLayoutData &layout)
{
  if (!layout.is_slot_based || !layout.has_feedback || layout.feedback_row_height <= 0.0f) {
    return;
  }

  View2D *v2d = &region->v2d;
  MessageLayoutData &mutable_layout = const_cast<MessageLayoutData &>(layout);

  /* Position below all content + todo + slot actions + copy buttons. */
  float fb_y = layout.y_pos;
  if (layout.slot_todo_height > 0.0f) {
    fb_y -= metrics.bubble_spacing + layout.slot_todo_height;
  }
  if (layout.slot_actions_height > 0.0f) {
    fb_y -= metrics.bubble_spacing + layout.slot_actions_height;
  }
  if (layout.slot_steps_height > 0.0f) {
    fb_y -= metrics.bubble_spacing + layout.slot_steps_height;
  }
  if (layout.thinking_height > 0.0f) {
    fb_y -= metrics.bubble_spacing + layout.thinking_height;
  }
  if (layout.text_height > 0.0f && !layout.has_loader) {
    fb_y -= chat_ui_get_action_buttons_height(UI_SCALE_FAC);
  }
  fb_y -= chat_ui_get_feedback_top_gap(metrics);

  const bool has_submitted_comment = layout.feedback_submitted_comment[0] != '\0' &&
                                     layout.feedback_submitted_comment_height > 0.0f;
  /* Once feedback has been accepted by the server (rating alone or with a
   * comment), the whole feedback area renders as an inline block (left accent
   * bar + indented content), matching the steps / thinking blocks above it in
   * the transcript. */
  const bool as_block = has_submitted_comment ||
                        layout.feedback_status == FEEDBACK_STATUS_RECEIVED;
  const float block_indent = as_block ? layout.style.font_size : 0.0f;

  const float star_size = layout.style.font_size * 1.4f;
  const float star_gap = star_size * 0.3f;
  float star_x = layout.bubble_x + block_indent;

  if (as_block) {
    /* Anchor the bar to the VISUAL extents, not the row box: the star glyphs
     * sit on a baseline near the row top, so they render roughly centered on
     * fb_y and overflow above it. A bar spanning the row box therefore hangs
     * below the stars. Rating-only: center the bar on the stars. With a
     * comment: from just above the stars down to the comment text bottom. */
    const float bar_top = fb_y + star_size * 0.5f;
    const float bar_bottom = has_submitted_comment ?
        fb_y - layout.feedback_row_height - layout.feedback_submitted_comment_height :
        fb_y - star_size * 0.5f;
    /* The shared neutral rail, not a green one: feedback is a settled block,
     * and the accent hue is reserved for what is executing right now. A green
     * rail here read as "something is running" on a finished turn. */
    const float bar_color[4] = CHAT_RAIL_NEUTRAL;
    chat_ui_draw_accent_bar(
        layout.bubble_x, bar_bottom, bar_top - bar_bottom, bar_color, metrics.scale_factor);
  }

  /* Hover previews the rating being selected: hovering star N fills stars
   * 1..N, like a standard rating widget. Locked rows never get hover state
   * (the cursor callback skips them), so this only affects live selection. */
  int hovered_rating = 0;
  for (int s = 0; s < FEEDBACK_STAR_COUNT; s++) {
    if (mutable_layout.feedback_stars[s].is_hovered) {
      hovered_rating = s + 1;
    }
  }

  for (int s = 0; s < FEEDBACK_STAR_COUNT; s++) {
    /* UTF-8: filled star and empty star. */
    const bool preview = (s + 1) <= hovered_rating;
    const bool filled = preview || (hovered_rating == 0 && (s + 1) <= layout.feedback_rating);
    const char *star_char = filled ? "\xe2\x98\x85" : "\xe2\x98\x86";

    /* Quiet greys, matching the chat's body-text tones — gold pulled too much
     * attention against the dark transcript. Filled matches the message text
     * grey; the hover preview is slightly brighter; unfilled stays dimmer so
     * the selected rating still reads. */
    float star_color[4];
    if (preview) {
      star_color[0] = 0.9f;
      star_color[1] = 0.9f;
      star_color[2] = 0.9f;
      star_color[3] = 1.0f;
    }
    else if (filled) {
      star_color[0] = 0.78f;
      star_color[1] = 0.78f;
      star_color[2] = 0.78f;
      star_color[3] = 1.0f;
    }
    else {
      star_color[0] = 0.5f;
      star_color[1] = 0.5f;
      star_color[2] = 0.5f;
      star_color[3] = 0.7f;
    }

    chat_ui_draw_label(star_char,
                       star_x,
                       fb_y - layout.feedback_row_height * 0.5f + star_size * 0.3f,
                       int(star_size),
                       0,
                       star_color,
                       false);

    mutable_layout.feedback_stars[s].bounds.xmin = star_x;
    mutable_layout.feedback_stars[s].bounds.xmax = star_x + star_size;
    mutable_layout.feedback_stars[s].bounds.ymin = fb_y - layout.feedback_row_height;
    mutable_layout.feedback_stars[s].bounds.ymax = fb_y;
    star_x += star_size + star_gap;
  }

  if (feedback_debug_enabled()) {
    /* Print only when the row moves, not every redraw. */
    static float last_fb_y = -1.0f;
    static float last_x = -1.0f;
    if (fb_y != last_fb_y || layout.bubble_x != last_x) {
      last_fb_y = fb_y;
      last_x = layout.bubble_x;
      fprintf(stderr,
              "[fb-debug] draw: msg=%d star1 bounds x[%.1f..%.1f] y[%.1f..%.1f] "
              "v2d.cur x[%.1f..%.1f] y[%.1f..%.1f] region %dx%d\n",
              layout.message_index,
              double(layout.feedback_stars[0].bounds.xmin),
              double(layout.feedback_stars[0].bounds.xmax),
              double(layout.feedback_stars[0].bounds.ymin),
              double(layout.feedback_stars[0].bounds.ymax),
              double(v2d->cur.xmin),
              double(v2d->cur.xmax),
              double(v2d->cur.ymin),
              double(v2d->cur.ymax),
              region->winx,
              region->winy);
    }
  }

  /* There is no separate "Feedback" toggle link any more — the comment field
   * auto-opens right after a star is clicked (see the rating operator), so
   * users discover text feedback without hunting for a hidden click target.
   * feedback_comment_bounds stays zeroed (populate_slot_layout_data), which
   * keeps the old toggle hit-test inert. */

  /* Status / hint to the right of the stars: tells idle users what the stars
   * are for, and rated users whether their feedback reached the server. */
  const float label_x = star_x + star_gap * 2.0f;
  const char *status_text = nullptr;
  float status_color[4];
  chat_tok_ink_2(status_color);
  switch (layout.feedback_status) {
    case FEEDBACK_STATUS_SENDING:
      status_text = "Sending\xe2\x80\xa6"; /* Sending… */
      break;
    case FEEDBACK_STATUS_RECEIVED:
      status_text = "\xe2\x9c\x93 Feedback received"; /* ✓ */
      chat_tok_green(status_color);
      break;
    case FEEDBACK_STATUS_FAILED:
      status_text = "Couldn't send \xe2\x80\x94 try again"; /* — */
      chat_tok_red(status_color);
      break;
    default:
      if (layout.feedback_rating == 0) {
        /* An unprompted invitation, so it sits at the lowest tier — it must
         * not compete with the response it is asking about. */
        status_text = "Rate this response";
        chat_tok_ink_3(status_color);
      }
      break;
  }
  if (status_text) {
    chat_ui_draw_label(status_text,
                       label_x,
                       fb_y - layout.feedback_row_height * 0.5f +
                           layout.style.font_size * 0.3f,
                       layout.style.font_size - 1,
                       0,
                       status_color,
                       false);
  }

  /* Read-only copy of the accepted comment, inside the block under the stars.
   * Height was measured in the layout pass — keep params in sync with
   * mixie_chat_build_layout_cache(). */
  float submitted_h = 0.0f;
  if (has_submitted_comment) {
    submitted_h = layout.feedback_submitted_comment_height;
    const float block_top = fb_y - layout.feedback_row_height;

    rctf text_rect;
    text_rect.xmin = layout.bubble_x + block_indent;
    text_rect.xmax = layout.bubble_x + layout.content_width;
    text_rect.ymin = block_top - submitted_h;
    text_rect.ymax = block_top;
    float text_color[4];
    chat_tok_ink_2(text_color);
    chat_ui_draw_text_wrapped(layout.feedback_submitted_comment,
                              &text_rect,
                              layout.style.font_size - 1,
                              0,
                              text_color);
  }

  if (!layout.feedback_comment_expanded || layout.feedback_comment_input_height <= 0.0f) {
    return;
  }

  float input_y_top = fb_y - layout.feedback_row_height;
  if (submitted_h > 0.0f) {
    input_y_top -= submitted_h + metrics.bubble_spacing;
  }
  const float input_y_bot = input_y_top - layout.feedback_comment_input_height;

  /* uiBlock buttons use region pixel coordinates for rendering and hit testing. */
  int rx1, ry1, rx2, ry2;
  UI_view2d_view_to_region(v2d, layout.bubble_x, input_y_bot, &rx1, &ry1);
  UI_view2d_view_to_region(
      v2d, layout.bubble_x + layout.bubble_width, input_y_top, &rx2, &ry2);

  if (ry2 <= 0 || ry1 >= region->winy || rx2 <= rx1 || ry2 <= ry1) {
    return;
  }

  char block_name[64];
  BLI_snprintf(block_name, sizeof(block_name), "fb_comment_%d", layout.message_index);
  uiBlock *block = UI_block_begin(C, region, block_name, blender::ui::EmbossType::Emboss);

  uiBut *comment_but = uiDefButR(block,
                                 ButType::Text,
                                 0,
                                 "",
                                 rx1,
                                 ry1,
                                 short(rx2 - rx1),
                                 short(ry2 - ry1),
                                 msg_ptr,
                                 "feedback_comment",
                                 -1,
                                 0.0f,
                                 0.0f,
                                 nullptr);
  if (comment_but) {
    UI_but_placeholder_set(comment_but, "Add a comment (optional) \xe2\x80\x94 press Enter to send");
    UI_but_flag_enable(comment_but, UI_BUT_TEXTEDIT_UPDATE);
  }

  UI_block_end(C, block);
  UI_view2d_view_restore(C);
  UI_block_draw(C, block);
  UI_view2d_view_ortho(v2d);
}

bool mixie_chat_handle_feedback_click(bContext *C,
                                      ARegion *region,
                                      float mouse_x,
                                      float mouse_y)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  const blender::Vector<MessageLayoutData> &layout_cache = mixie_chat_get_layout_cache(smixie);

  View2D *v2d = &region->v2d;
  float view_x, view_y;
  UI_view2d_region_to_view(v2d, mouse_x, mouse_y, &view_x, &view_y);

  if (feedback_debug_enabled()) {
    int fb_layouts = 0;
    for (const MessageLayoutData &l : layout_cache) {
      if (l.has_feedback) {
        fb_layouts++;
        fprintf(stderr,
                "[fb-debug] click: region(%.1f, %.1f) -> view(%.1f, %.1f); msg=%d "
                "star1 bounds x[%.1f..%.1f] y[%.1f..%.1f]\n",
                double(mouse_x),
                double(mouse_y),
                double(view_x),
                double(view_y),
                l.message_index,
                double(l.feedback_stars[0].bounds.xmin),
                double(l.feedback_stars[0].bounds.xmax),
                double(l.feedback_stars[0].bounds.ymin),
                double(l.feedback_stars[0].bounds.ymax));
      }
    }
    if (fb_layouts == 0) {
      fprintf(stderr,
              "[fb-debug] click: region(%.1f, %.1f) -> view(%.1f, %.1f); "
              "NO layout with has_feedback (cache size %d)\n",
              double(mouse_x),
              double(mouse_y),
              double(view_x),
              double(view_y),
              int(layout_cache.size()));
    }
  }

  for (const MessageLayoutData &layout : layout_cache) {
    if (!layout.has_feedback) {
      continue;
    }

    /* Submitted feedback is locked: once a rating is in flight or accepted,
     * the stars stop being click targets. Only idle and failed (retry) states
     * accept rating clicks. */
    if (layout.feedback_status == FEEDBACK_STATUS_SENDING ||
        layout.feedback_status == FEEDBACK_STATUS_RECEIVED)
    {
      continue;
    }

    for (int i = 0; i < FEEDBACK_STAR_COUNT; i++) {
      const FeedbackStarData &star = layout.feedback_stars[i];
      const bool has_bounds = star.bounds.xmax > star.bounds.xmin;
      if (has_bounds && BLI_rctf_isect_pt(&star.bounds, view_x, view_y)) {
        wmOperatorType *ot = WM_operatortype_find("mixie_chat.set_feedback_rating", true);
        if (ot) {
          PointerRNA op_ptr;
          WM_operator_properties_create_ptr(&op_ptr, ot);
          RNA_string_set(&op_ptr, "bubble_id", layout.bubble_id);
          RNA_int_set(&op_ptr, "rating", star.star_index);
          WM_operator_name_call_ptr(
              C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
          WM_operator_properties_free(&op_ptr);
          ED_region_tag_redraw(region);
          return true;
        }
      }
    }

    const bool has_comment_bounds = layout.feedback_comment_bounds.xmax >
                                    layout.feedback_comment_bounds.xmin;
    if (has_comment_bounds &&
        BLI_rctf_isect_pt(&layout.feedback_comment_bounds, view_x, view_y))
    {
      wmOperatorType *ot = WM_operatortype_find("mixie_chat.toggle_feedback_comment", true);
      if (ot) {
        PointerRNA op_ptr;
        WM_operator_properties_create_ptr(&op_ptr, ot);
        RNA_string_set(&op_ptr, "bubble_id", layout.bubble_id);
        WM_operator_name_call_ptr(
            C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
        WM_operator_properties_free(&op_ptr);
        ED_region_tag_redraw(region);
        return true;
      }
    }
  }

  return false;
}
