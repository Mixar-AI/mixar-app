/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Hit testing and click handling for chat messages.
 * Position-to-text conversion, action button clicks, and prompt clicks.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_ref.hh"
#include "BLI_time.h"
#include "BLI_vector.hh"

#include "BLF_api.hh"

#include "BKE_context.hh"
#include "BKE_main.hh"

#include "DNA_scene_types.h"
#include "DNA_space_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "ED_screen.hh"

#include "UI_view2d.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Helpers
 * \{ */

static SpaceMixieChat *get_space_mixie_chat(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  /* SPACE_AGENT_BUBBLE has a layout-compatible spacedata struct
   * (see DNA_space_types.h), so this cast is valid for both — the
   * agent bubble reuses the chat hit-testing logic for selection. */
  if (area && (area->spacetype == SPACE_MIXIE_CHAT ||
               area->spacetype == SPACE_AGENT_BUBBLE))
  {
    return static_cast<SpaceMixieChat *>(area->spacedata.first);
  }
  return nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Position to Text Conversion
 *
 * Hit-testing runs on the SAME layout cache the draw pass produced —
 * re-deriving the geometry here (the original implementation) went stale
 * the moment the renderer learned steps/thinking blocks, action buttons,
 * feedback rows and markdown sizing, which put every computed bubble rect
 * at the wrong y and made text selection dead in practice.
 * \{ */

bool mixie_chat_layout_text_rect(const MessageLayoutData *layout, rctf *r_rect)
{
  if (layout->text_height <= 0.0f || layout->bubble_height <= 0.0f) {
    return false;
  }

  r_rect->xmin = layout->bubble_x + layout->style.h_padding;
  r_rect->xmax = r_rect->xmin + layout->content_width;

  if (layout->is_markdown_content) {
    /* Markdown content draws top-down from the bubble's top padding. */
    r_rect->ymax = layout->y_pos + layout->bubble_height - layout->style.v_padding;
    r_rect->ymin = r_rect->ymax - layout->text_height;
  }
  else {
    /* Plain bubbles vertically center the text (bottom-anchor it when
     * attachments fill the top) — mirror chat_ui_draw_bubble exactly. */
    const float text_area_height = layout->bubble_height - layout->attachments_height -
                                   layout->style.v_padding * 2.0f;
    const float vertical_offset = (layout->attachments_height > 0.0f) ?
                                      0.0f :
                                      (text_area_height - layout->text_height) / 2.0f;
    r_rect->ymin = layout->y_pos + layout->style.v_padding + vertical_offset;
    r_rect->ymax = r_rect->ymin + layout->text_height;
  }
  return true;
}

/**
 * Map a point inside a wrapped-text rect to a byte offset in `text`,
 * using the same BLF word-wrap the draw pass uses. `local_x` is measured
 * from the text rect's left edge, `y_from_top` down from its top edge.
 * `line_height` <= 0 derives the plain BLF line height.
 */
static int wrapped_text_byte_offset(const char *text,
                                    float wrap_width,
                                    int font_size,
                                    int font_id,
                                    float line_height,
                                    float local_x,
                                    float y_from_top,
                                    BLFWrapMode wrap_mode)
{
  BLF_size(font_id, font_size);

  const blender::Vector<blender::StringRef> lines =
      BLF_string_wrap(font_id, text, int(wrap_width), wrap_mode);
  if (lines.is_empty()) {
    return 0;
  }

  if (line_height <= 0.0f) {
    line_height = float(BLF_height_max(font_id));
  }
  int line_idx = (line_height > 0.0f) ? int(y_from_top / line_height) : 0;
  if (line_idx < 0) {
    line_idx = 0;
  }
  if (line_idx >= int(lines.size())) {
    line_idx = int(lines.size()) - 1;
  }

  const blender::StringRef line = lines[line_idx];
  const int line_start = int(line.data() - text);
  if (local_x <= 0.0f || line.is_empty()) {
    return line_start;
  }
  const size_t within = BLF_str_offset_from_cursor_position(
      font_id, line.data(), size_t(line.size()), int(local_x));
  return line_start + int(within);
}

/* Line height the draw pass used for a markdown segment: code blocks are
 * drawn with plain BLF wrap (mono line height), everything else through
 * chat_ui_rich_text (default line height * 1.15). */
static float md_seg_line_height(const MarkdownSegHit &hit)
{
  const int font_id = hit.mono ? chat_ui_mono_font() : BLF_default();
  BLF_size(font_id, hit.font_size);
  const float base = float(BLF_height_max(font_id));
  return hit.mono ? base : base * 1.15f;
}

bool mixie_chat_pos_in_message_bubble(const bContext *C, ARegion *region, const int mval[2])
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  float view_x, view_y;
  ui::view2d_region_to_view(&region->v2d, mval[0], mval[1], &view_x, &view_y);
  for (const MessageLayoutData &layout : mixie_chat_get_layout_cache(smixie)) {
    if (layout.bubble_height <= 0.0f) {
      continue;
    }
    rctf bubble_rect;
    bubble_rect.xmin = layout.bubble_x;
    bubble_rect.xmax = layout.bubble_x + layout.bubble_width;
    bubble_rect.ymin = layout.y_pos;
    bubble_rect.ymax = layout.y_pos + layout.bubble_height;
    if (BLI_rctf_isect_pt(&bubble_rect, view_x, view_y)) {
      return true;
    }
  }
  return false;
}

bool mixie_chat_pos_to_text(const bContext *C,
                            ARegion *region,
                            const int mval[2],
                            int *r_message_index,
                            int *r_seg_index,
                            int *r_char_offset)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  float view_x, view_y;
  ui::view2d_region_to_view(&region->v2d, mval[0], mval[1], &view_x, &view_y);

  /* Markdown bubbles: hit-test the RENDERED segment rects and map the click
   * against that segment's own text, font and wrap — mapping the raw
   * markdown string over the laid-out bubble put offsets nowhere near the
   * glyphs (code cards use the mono font, a narrower wrap width, and a
   * language header row). */
  for (const MarkdownSegHit &hit : rt->md_seg_hits) {
    if (!BLI_rctf_isect_pt(&hit.text_rect, view_x, view_y)) {
      continue;
    }
    const char *seg_text = mixie_chat_message_segment_text(
        C, hit.message_index, hit.seg_index, /*code_only=*/false);
    if (!seg_text || seg_text[0] == '\0') {
      continue;
    }
    float local_x = view_x - hit.text_rect.xmin;
    float y_from_top = hit.text_rect.ymax - view_y;
    if (local_x < 0.0f) {
      local_x = 0.0f;
    }
    if (y_from_top < 0.0f) {
      y_from_top = 0.0f;
    }
    const int font_id = hit.mono ? chat_ui_mono_font() : BLF_default();
    /* Code cards draw with HardLimit wrap (unbreakable tokens fold at the
     * card edge) — the mapping must wrap the same way. */
    const BLFWrapMode wrap_mode = hit.mono ? BLFWrapMode::HardLimit : BLFWrapMode::Minimal;
    *r_message_index = hit.message_index;
    *r_seg_index = hit.seg_index;
    *r_char_offset = wrapped_text_byte_offset(seg_text,
                                              BLI_rctf_size_x(&hit.text_rect),
                                              hit.font_size,
                                              font_id,
                                              md_seg_line_height(hit),
                                              local_x,
                                              y_from_top,
                                              wrap_mode);
    return true;
  }

  /* Plain-text bubbles: map against the message's copy text. */
  const blender::Vector<MessageLayoutData> &layout_cache = mixie_chat_get_layout_cache(smixie);

  for (const MessageLayoutData &layout : layout_cache) {
    /* Selection offsets index the copyable text (content > legacy text,
     * cached at layout time) — a message without it has nothing to select.
     * Markdown bubbles were handled above via their segment rects. */
    if (layout.is_markdown_content || !layout.copy_text || layout.copy_text[0] == '\0') {
      continue;
    }

    rctf bubble_rect;
    bubble_rect.xmin = layout.bubble_x;
    bubble_rect.xmax = layout.bubble_x + layout.bubble_width;
    bubble_rect.ymin = layout.y_pos;
    bubble_rect.ymax = layout.y_pos + layout.bubble_height;
    if (!BLI_rctf_isect_pt(&bubble_rect, view_x, view_y)) {
      continue;
    }

    rctf text_rect;
    if (!mixie_chat_layout_text_rect(&layout, &text_rect)) {
      continue;
    }

    float local_x = view_x - text_rect.xmin;
    float y_from_top = text_rect.ymax - view_y;
    if (local_x < 0.0f) {
      local_x = 0.0f;
    }
    if (y_from_top < 0.0f) {
      y_from_top = 0.0f;
    }

    *r_message_index = layout.message_index;
    *r_seg_index = -1;
    *r_char_offset = wrapped_text_byte_offset(layout.copy_text,
                                              BLI_rctf_size_x(&text_rect),
                                              layout.style.font_size,
                                              BLF_default(),
                                              -1.0f,
                                              local_x,
                                              y_from_top,
                                              BLFWrapMode::Minimal);
    return true;
  }

  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Click Handlers
 * \{ */

/**
 * Dispatch a slot action operator for the given action data.
 * Returns true if the operator was successfully found and called.
 */
static bool dispatch_slot_action(bContext *C,
                                  ARegion *region,
                                  const MessageLayoutData &layout,
                                  const ActionSlotData &action)
{
  wmOperatorType *ot = WM_operatortype_find("mixie_chat.select_slot_action", true);
  if (!ot) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&op_ptr, "bubble_id", layout.bubble_id);
  RNA_string_set(&op_ptr, "action_value", action.value);
  WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  ED_region_tag_redraw(region);
  return true;
}

bool mixie_chat_handle_slot_action_click(bContext *C,
                                          ARegion *region,
                                          float mouse_x,
                                          float mouse_y)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  const blender::Vector<MessageLayoutData> &layout_cache = mixie_chat_get_layout_cache(smixie);

  /* Always dispatch by actual click position — is_hovered can be stale because
   * MOUSE_MOVE (cursor callback) fires as a separate event from LEFTMOUSE. */
  View2D *v2d = &region->v2d;
  float view_x, view_y;
  ui::view2d_region_to_view(v2d, mouse_x, mouse_y, &view_x, &view_y);

  for (const MessageLayoutData &layout : layout_cache) {
    for (int i = 0; i < layout.slot_action_count; i++) {
      const ActionSlotData &action = layout.slot_actions[i];
      bool has_bounds = action.bounds.xmax > action.bounds.xmin;
      if (has_bounds && BLI_rctf_isect_pt(&action.bounds, view_x, view_y)) {
        return dispatch_slot_action(C, region, layout, action);
      }
    }
  }

  return false;
}

/* DRY helper: find + call a toggle operator with bubble_id (+ optional item_id). */
static bool dispatch_toggle(bContext *C,
                            ARegion *region,
                            const char *op_name,
                            const char *bubble_id,
                            const char *item_id)
{
  wmOperatorType *ot = WM_operatortype_find(op_name, true);
  if (!ot) {
    return false;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&op_ptr, "bubble_id", bubble_id);
  if (item_id) {
    RNA_string_set(&op_ptr, "item_id", item_id);
  }
  WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  ED_region_tag_redraw(region);
  return true;
}

/**
 * Hit-test the step rows, the steps block header, and the thinking dropdown
 * header. Dispatches the matching toggle operator. Rows are tested before the
 * header so an expanded row's own bounds win.
 */
bool mixie_chat_handle_steps_click(bContext *C,
                                   ARegion *region,
                                   float mouse_x,
                                   float mouse_y)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  const blender::Vector<MessageLayoutData> &layout_cache =
      mixie_chat_get_layout_cache(smixie);

  View2D *v2d = &region->v2d;
  float view_x, view_y;
  ui::view2d_region_to_view(v2d, mouse_x, mouse_y, &view_x, &view_y);

  for (const MessageLayoutData &layout : layout_cache) {
    if (layout.has_steps) {
      /* Expanded rows with detail toggle their own second level. */
      if (!layout.steps_collapsed) {
        for (int i = 0; i < layout.slot_step_count; i++) {
          const StepItemSlotData &step = layout.slot_steps[i];
          if (step.detail[0] == '\0') {
            continue;
          }
          if (step.row_bounds.xmax > step.row_bounds.xmin &&
              BLI_rctf_isect_pt(&step.row_bounds, view_x, view_y)) {
            return dispatch_toggle(C, region, "mixie_chat.toggle_step_row",
                                   layout.bubble_id, step.id);
          }
        }
      }
      /* Header toggles the whole block. */
      const rctf &hb = layout.steps_header_bounds;
      if (hb.xmax > hb.xmin && BLI_rctf_isect_pt(&hb, view_x, view_y)) {
        return dispatch_toggle(C, region, "mixie_chat.toggle_steps",
                               layout.bubble_id, nullptr);
      }
    }

    if (layout.has_thinking) {
      const rctf &tb = layout.thinking_header_bounds;
      if (tb.xmax > tb.xmin && BLI_rctf_isect_pt(&tb, view_x, view_y)) {
        return dispatch_toggle(C, region, "mixie_chat.toggle_thinking",
                               layout.bubble_id, nullptr);
      }
    }
  }

  return false;
}

bool mixie_chat_handle_empty_prompt_click(bContext *C, float mouse_x, float mouse_y)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  if (!rt->empty_prompts_visible) {
    return false;
  }

  for (int i = 0; i < CHAT_EMPTY_PROMPT_COUNT; i++) {
    if (BLI_rctf_isect_pt(&rt->empty_prompts[i].bounds, mouse_x, mouse_y)) {
      wmOperatorType *ot = WM_operatortype_find("mixie_chat.insert_prompt_text", true);
      if (ot) {
        PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
        RNA_string_set(&op_ptr, "text", rt->empty_prompts[i].text);
        RNA_string_set(&op_ptr, "mode", g_empty_prompt_modes[i]);
        RNA_string_set(&op_ptr, "generate_type", g_empty_prompt_generate_types[i]);
        WM_operator_name_call_ptr(
            C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
        WM_operator_properties_free(&op_ptr);
        return true;
      }
    }
  }

  return false;
}

/** \} */
}  // namespace blender
