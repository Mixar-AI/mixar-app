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
#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

float mixie_chat_feedback_comment_input_height(PointerRNA *msg_ptr, const float input_width)
{
  /* Every value here must match widget_draw_text_multiline() /
   * ui_multiline_visible_lines() (interface_widgets.cc): the widget renders at
   * the plain widget font (points x 1.0), computes line_height as
   * BLF_height("Wg") + 2*pixelsize, and scrolls to keep the cursor within
   * floor(rect_height / line_height) lines. Measuring with any other font or
   * per-line height makes the button taller than the widget's line grid —
   * phantom lines the cursor can't reach. */
  uiFontStyle fstyle = ui::style_get()->widget;
  ui::fontstyle_set(&fstyle);
  const int fontid = fstyle.uifont_id;
  const int line_height = std::max(int(BLF_height(fontid, "Wg", 2) + 2.0f * U.pixelsize), 1);
  const int pad = int(4.0f * U.pixelsize); /* widget top inset; mirrored at bottom */

  int line_count = 1;
  const int text_len = g_msg_props.feedback_comment ?
      RNA_property_string_length(msg_ptr, g_msg_props.feedback_comment) : 0;
  if (text_len > 0) {
    char *text = static_cast<char *>(MEM_new_uninitialized(size_t(text_len) + 1, __func__));
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

    MEM_delete_void(static_cast<void *>(text));
  }

  /* N full lines plus the top inset and a matching bottom margin. The margins
   * stay below one line_height, so floor(height / line_height) == N and the
   * widget's scroll window agrees with what is visible. */
  return float(line_count * line_height + pad * 2);
}

static SpaceMixieChat *get_space_mixie_chat(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  if (area && area->spacetype == SPACE_AGENT_BUBBLE) {
    return static_cast<SpaceMixieChat *>(area->spacedata.first);
  }
  return nullptr;
}

/* Font-independent outline: the downvote mirrors the same thumb vertically. */
static void draw_thumb(const rctf &rect, const bool up, const float color[4])
{
  const float points[][2] = {{2, 2}, {5, 2}, {5, 9}, {2, 9}, {2, 2},
                           {5, 2}, {12, 2}, {14, 8}, {13, 10}, {9, 10},
                           {10, 14}, {8, 15}, {5, 9}};
  const float unit = (rect.ymax - rect.ymin) / 22.0f;
  const float x = rect.xmin + 3 * unit;
  const float y = rect.ymin + 3 * unit;
  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  const uint pos = GPU_vertformat_attr_add(
      immVertexFormat(), "pos", blender::gpu::VertAttrType::SFLOAT_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", 1.3f * UI_SCALE_FAC);
  immUniform1i("lineSmooth", 1);
  immUniformColor4fv(color);
  immBegin(GPU_PRIM_LINE_STRIP, 13);
  for (const auto &point : points) {
    immVertex3f(pos, x + point[0] * unit, y + (up ? point[1] : 17 - point[1]) * unit, 0);
  }
  immEnd();
  immUnbindProgram();
}

void mixie_chat_render_feedback(const bContext *C,
                                ARegion *region,
                                PointerRNA *msg_ptr,
                                const ChatLayoutMetrics &metrics,
                                const MessageLayoutData &layout)
{
  if (!layout.is_slot_based || !layout.has_feedback || layout.action_button_count == 0) {
    return;
  }
  MessageLayoutData &mutable_layout = const_cast<MessageLayoutData &>(layout);
  const rctf &copy = layout.action_buttons[0].bounds;
  const float height = copy.ymax - copy.ymin;
  const float gap = 5.0f * UI_SCALE_FAC;
  float x = copy.xmax + gap;
  const bool sending = layout.feedback_status == FEEDBACK_STATUS_SENDING;
  float text_color[4];
  chat_ui_get_button_text_color(text_color);
  for (int i = 0; i < FEEDBACK_VOTE_COUNT; i++) {
    FeedbackVoteData &vote = mutable_layout.feedback_votes[i];
    vote.bounds = {x, x + height, copy.ymin, copy.ymax};
    const bool selected = layout.feedback_rating == vote.rating;
    float bg[4];
    if (selected || vote.is_hovered) {
      chat_ui_get_button_hover_color(bg);
    }
    else {
      chat_ui_get_button_bg_color(bg);
    }
    if (selected) {
      bg[0] += 0.08f;
      bg[1] += 0.08f;
      bg[2] += 0.08f;
    }
    chat_ui_draw_rounded_rect(&vote.bounds, 4 * UI_SCALE_FAC, bg);
    float color[4] = {text_color[0], text_color[1], text_color[2], sending ? 0.4f : 1.0f};
    if (selected) {
      color[0] = color[1] = color[2] = 0.95f;
    }
    draw_thumb(vote.bounds, vote.rating == 5, color);
    x += height + gap;
  }
  mutable_layout.feedback_comment_bounds = {};
  if (layout.feedback_rating > 0) {
    const char *label = layout.feedback_comment_expanded ? "Close" : "Comment";
    float width, text_h;
    chat_ui_calc_text_bounds(label, 200, layout.style.font_size - 1, 0, &width, &text_h);
    rctf &bounds = mutable_layout.feedback_comment_bounds;
    bounds = {x, x + width + 10 * UI_SCALE_FAC, copy.ymin, copy.ymax};
    float bg[4];
    if (layout.feedback_comment_hovered) chat_ui_get_button_hover_color(bg);
    else chat_ui_get_button_bg_color(bg);
    chat_ui_draw_rounded_rect(&bounds, 4 * UI_SCALE_FAC, bg);
    text_color[3] = sending ? 0.4f : 0.85f;
    chat_ui_draw_label(label, x + 5 * UI_SCALE_FAC,
                       copy.ymin + (height - text_h) / 2,
                       layout.style.font_size - 1, 0, text_color, false);
  }

  float top = copy.ymin - metrics.bubble_spacing;
  if (layout.feedback_row_height > 0) {
    const bool failed = layout.feedback_status == FEEDBACK_STATUS_FAILED;
    const char *status = failed ? "Couldn't send. Please try again." : "Sending feedback...";
    float color[4] = {failed ? 0.9f : 0.6f, 0.55f, 0.5f, 1.0f};
    chat_ui_draw_label(status, layout.bubble_x, top - layout.style.font_size,
                       layout.style.font_size - 1, 0, color, false);
    top -= layout.feedback_row_height;
  }
  if (layout.feedback_submitted_comment_height > 0) {
    rctf rect = {layout.bubble_x + layout.style.font_size,
                layout.bubble_x + layout.content_width,
                top - layout.feedback_submitted_comment_height, top};
    float color[4] = {0.65f, 0.65f, 0.65f, 0.95f};
    chat_ui_draw_text_wrapped(layout.feedback_submitted_comment, &rect,
                              layout.style.font_size - 1, 0, color);
    chat_ui_draw_accent_bar(layout.bubble_x, rect.ymin, rect.ymax - rect.ymin,
                           color, metrics.scale_factor);
    top = rect.ymin - metrics.bubble_spacing;
  }
  if (!layout.feedback_comment_expanded || layout.feedback_comment_input_height <= 0) return;

  const float actions_h = 28.0f * UI_SCALE_FAC;
  View2D *v2d = &region->v2d;
  int rx1, ry1, rx2, ry2;
  ui::view2d_view_to_region(v2d, layout.bubble_x,
      top - layout.feedback_comment_input_height + actions_h, &rx1, &ry1);
  ui::view2d_view_to_region(v2d, layout.bubble_x + layout.bubble_width, top, &rx2, &ry2);
  if (ry2 <= 0 || ry1 >= region->winy || rx2 <= rx1 || ry2 <= ry1) return;
  char name[64];
  BLI_snprintf(name, sizeof(name), "fb_comment_%d", layout.message_index);
  ui::Block *block = ui::block_begin(C, region, name, ui::EmbossType::Emboss);
  ui::Button *input = ui::uiDefButR(block, ui::ButtonType::Text, "", rx1, ry1,
      short(rx2 - rx1), short(ry2 - ry1), msg_ptr, "feedback_comment", -1, 0, 0, nullptr);
  ui::button_placeholder_set(input, "Add a comment (optional)");
  ui::button_flag_enable(input, ui::BUT_TEXTEDIT_UPDATE);
  if (sending) ui::button_flag_enable(input, ui::BUT_DISABLED);
  const int button_h = int(20 * UI_SCALE_FAC);
  const char *ops[] = {"MIXIE_CHAT_OT_submit_feedback_comment", "MIXIE_CHAT_OT_cancel_feedback_comment"};
  const char *labels[] = {"Save", "Cancel"};
  for (int i = 0; i < 2; i++) {
    ui::Button *button = ui::uiDefButO(block, ui::ButtonType::But, ops[i],
        wm::OpCallContext::ExecDefault, labels[i], rx1 + i * int(66 * UI_SCALE_FAC),
        ry1 - button_h - int(4 * UI_SCALE_FAC), int(60 * UI_SCALE_FAC), button_h, std::nullopt);
    RNA_string_set(ui::button_operator_ptr_ensure(button), "bubble_id", layout.bubble_id);
    if (sending) ui::button_flag_enable(button, ui::BUT_DISABLED);
  }
  ui::block_end(C, block);
  ui::view2d_view_restore(C);
  ui::block_draw(C, block);
  ui::view2d_view_ortho(v2d);
}

bool mixie_chat_handle_feedback_click(bContext *C, ARegion *region, float mouse_x, float mouse_y)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) return false;
  float x, y;
  ui::view2d_region_to_view(&region->v2d, mouse_x, mouse_y, &x, &y);
  for (const MessageLayoutData &layout : mixie_chat_get_layout_cache(smixie)) {
    if (!layout.has_feedback || layout.feedback_status == FEEDBACK_STATUS_SENDING) continue;
    const char *op = nullptr;
    int rating = 0;
    for (const FeedbackVoteData &vote : layout.feedback_votes) {
      if (vote.bounds.xmax > vote.bounds.xmin && BLI_rctf_isect_pt(&vote.bounds, x, y)) {
        op = "mixie_chat.set_feedback_rating";
        rating = vote.rating;
      }
    }
    if (layout.feedback_comment_bounds.xmax > layout.feedback_comment_bounds.xmin &&
        BLI_rctf_isect_pt(&layout.feedback_comment_bounds, x, y)) {
      op = "mixie_chat.toggle_feedback_comment";
    }
    if (!op) continue;
    wmOperatorType *ot = WM_operatortype_find(op, true);
    if (!ot) continue;
    PointerRNA props = WM_operator_properties_create_ptr(ot);
    RNA_string_set(&props, "bubble_id", layout.bubble_id);
    if (rating) RNA_int_set(&props, "rating", rating);
    mixie_chat_call_operator_and_redraw(C, region, ot, &props);
    WM_operator_properties_free(&props);
    return true;
  }
  return false;
}
}  // namespace blender
