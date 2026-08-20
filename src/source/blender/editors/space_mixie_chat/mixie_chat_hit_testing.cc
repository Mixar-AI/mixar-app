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
#include "BLI_time.h"

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
 * \{ */

struct MessageLayoutInfo {
  rctf bubble_rect;
  rctf text_rect;
  int message_index;
  char text[8192];
  int font_size;
};

static float calc_message_attachments_height(Main *bmain,
                                             PointerRNA *msg_ptr,
                                             const ChatImageStyle *image_style)
{
  PropertyRNA *att_prop = RNA_struct_find_property(msg_ptr, "attachments");
  if (!att_prop) {
    return 0.0f;
  }

  int att_count = RNA_property_collection_length(msg_ptr, att_prop);
  if (att_count == 0) {
    return 0.0f;
  }

  float total_height = 0.0f;
  char path_buffer[1024];
  PropertyRNA *path_prop = nullptr;
  PropertyRNA *source_prop = nullptr;

  CollectionPropertyIterator att_iter{};
  RNA_property_collection_begin(msg_ptr, att_prop, &att_iter);

  if (att_iter.valid) {
    path_prop = RNA_struct_find_property(&att_iter.ptr, "image_path");
    source_prop = RNA_struct_find_property(&att_iter.ptr, "image_source");
  }

  while (att_iter.valid) {
    if (path_prop && source_prop) {
      /* image_path has no RNA maxlen, so RNA_property_string_get would copy
       * the full string unbounded; guard against overflowing the fixed stack
       * buffer (same pattern as footer_cache). */
      path_buffer[0] = '\0';
      const int path_len = RNA_property_string_length(&att_iter.ptr, path_prop);
      if (path_len > 0 && path_len < int(sizeof(path_buffer))) {
        RNA_property_string_get(&att_iter.ptr, path_prop, path_buffer);
      }
      int source = RNA_property_enum_get(&att_iter.ptr, source_prop);

      if (path_buffer[0] != '\0') {
        float img_height = chat_ui_calc_image_attachment_height(
            bmain, path_buffer, source, image_style);
        total_height += img_height;
      }
    }
    RNA_property_collection_next(&att_iter);
  }
  RNA_property_collection_end(&att_iter);

  return total_height;
}

bool mixie_chat_pos_to_text(const bContext *C,
                            ARegion *region,
                            const int mval[2],
                            int *r_message_index,
                            int *r_char_offset)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return false;
  }

  Main *bmain = CTX_data_main(C);
  View2D *v2d = &region->v2d;

  float view_x, view_y;
  ui::view2d_region_to_view(v2d, mval[0], mval[1], &view_x, &view_y);

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");
  if (!prop) {
    return false;
  }

  int msg_count = RNA_property_collection_length(&scene_ptr, prop);
  if (msg_count == 0) {
    return false;
  }

  ChatLayoutMetrics metrics = chat_ui_get_layout_metrics();
  ChatImageStyle image_style = chat_ui_get_image_style(&metrics);
  const float max_bubble_width = float(region->winx) * metrics.max_bubble_width_ratio;

  PropertyRNA *sender_prop = nullptr;
  PropertyRNA *text_prop = nullptr;

  /* First pass: calculate total height */
  float total_height = metrics.padding;

  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, prop, &iter);

  if (iter.valid) {
    sender_prop = RNA_struct_find_property(&iter.ptr, "sender");
    text_prop = RNA_struct_find_property(&iter.ptr, "content");
    if (!text_prop) {
      text_prop = RNA_struct_find_property(&iter.ptr, "text");
    }
  }

  while (iter.valid) {
    if (text_prop) {
      PointerRNA msg_ptr = iter.ptr;

      int text_len = RNA_property_string_length(&msg_ptr, text_prop);
      char *text_buffer = static_cast<char *>(MEM_new_uninitialized(text_len + 1, "chat_text"));
      RNA_property_string_get(&msg_ptr, text_prop, text_buffer);
      int sender_enum = sender_prop ? RNA_property_enum_get(&msg_ptr, sender_prop) : 0;
      bool is_user = (sender_enum == 0);
      ChatBubbleStyle style = is_user ? chat_ui_get_user_bubble_style(&metrics) :
                                        chat_ui_get_agent_bubble_style(&metrics);

      float content_width = max_bubble_width - style.h_padding * 2.0f;
      float text_width, text_height;
      chat_ui_calc_text_bounds(
          text_buffer, content_width, style.font_size, 0, &text_width, &text_height);

      float attachments_height = calc_message_attachments_height(bmain, &msg_ptr, &image_style);

      float bubble_width = text_width + style.h_padding * 2.0f + 4.0f;
      float bubble_height = text_height + attachments_height + style.v_padding * 2.0f;

      float min_width = 100.0f * metrics.scale_factor;
      if (attachments_height > 0) {
        min_width = image_style.max_width + image_style.margin * 2.0f + style.h_padding * 2.0f;
      }
      if (bubble_width < min_width) {
        bubble_width = min_width;
      }

      total_height += metrics.label_height;
      total_height += bubble_height;
      total_height += metrics.bubble_spacing;

      MEM_delete_void(static_cast<void *>(text_buffer));
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);

  /* Second pass: find message at mouse position */
  float y_pos = total_height - metrics.padding;
  int message_index = 0;

  RNA_property_collection_begin(&scene_ptr, prop, &iter);

  while (iter.valid) {
    if (sender_prop && text_prop) {
      PointerRNA msg_ptr = iter.ptr;
      int sender_enum = RNA_property_enum_get(&msg_ptr, sender_prop);
      bool is_user = (sender_enum == 0);

      int text_len = RNA_property_string_length(&msg_ptr, text_prop);
      char *text_buffer = static_cast<char *>(MEM_new_uninitialized(text_len + 1, "chat_text"));
      RNA_property_string_get(&msg_ptr, text_prop, text_buffer);

      ChatBubbleStyle style = is_user ? chat_ui_get_user_bubble_style(&metrics) :
                                        chat_ui_get_agent_bubble_style(&metrics);

      float content_width = max_bubble_width - style.h_padding * 2.0f;
      float text_width, text_height;
      chat_ui_calc_text_bounds(
          text_buffer, content_width, style.font_size, 0, &text_width, &text_height);

      float attachments_height = calc_message_attachments_height(bmain, &msg_ptr, &image_style);

      float bubble_width = text_width + style.h_padding * 2.0f + 4.0f;
      float bubble_height = text_height + attachments_height + style.v_padding * 2.0f;

      float min_width = 100.0f * metrics.scale_factor;
      if (attachments_height > 0) {
        min_width = image_style.max_width + image_style.margin * 2.0f + style.h_padding * 2.0f;
      }
      if (bubble_width < min_width) {
        bubble_width = min_width;
      }

      float bubble_x = is_user ? (float(region->winx) - bubble_width - metrics.padding) :
                                 metrics.padding;

      y_pos -= metrics.label_height;
      y_pos -= bubble_height;

      rctf bubble_rect;
      bubble_rect.xmin = bubble_x;
      bubble_rect.xmax = bubble_x + bubble_width;
      bubble_rect.ymin = y_pos;
      bubble_rect.ymax = y_pos + bubble_height;

      if (BLI_rctf_isect_pt(&bubble_rect, view_x, view_y)) {
        rctf text_rect;
        text_rect.xmin = bubble_x + style.h_padding;
        text_rect.xmax = bubble_x + style.h_padding + content_width;
        text_rect.ymin = y_pos + style.v_padding;
        text_rect.ymax = y_pos + bubble_height - style.v_padding;

        const int font_id = BLF_default();
        BLF_size(font_id, style.font_size);
        BLF_enable(font_id, BLF_WORD_WRAP);
        BLF_wordwrap(font_id, int(content_width));

        float click_x = view_x - text_rect.xmin;
        int text_len_int = text_len;
        int char_offset = text_len_int;

        for (int i = 0; i < text_len_int; i++) {
          float prefix_width = BLF_width(font_id, text_buffer, i);
          if (prefix_width >= click_x) {
            if (i > 0) {
              float prev_width = BLF_width(font_id, text_buffer, i - 1);
              if ((click_x - prev_width) < (prefix_width - click_x)) {
                char_offset = i - 1;
              }
              else {
                char_offset = i;
              }
            }
            else {
              char_offset = 0;
            }
            break;
          }
        }

        BLF_disable(font_id, BLF_WORD_WRAP);

        *r_message_index = message_index;
        *r_char_offset = char_offset;

        MEM_delete_void(static_cast<void *>(text_buffer));
        RNA_property_collection_end(&iter);
        return true;
      }

      y_pos -= metrics.bubble_spacing;
      message_index++;

      MEM_delete_void(static_cast<void *>(text_buffer));
    }
    RNA_property_collection_next(&iter);
  }

  RNA_property_collection_end(&iter);
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
