/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Message render loop for chat UI.
 * Draws cached message layouts with visibility culling, handles hover
 * states, action buttons, text selection, and cursor updates.
 * Split from mixie_chat_messages.cc for modularity.
 */

#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_main.hh"

#include "BLF_api.hh"

#include "ED_screen.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "GPU_matrix.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Message Render Loop
 * \{ */

void mixie_chat_render_messages(const bContext *C,
                                ARegion *region,
                                SpaceMixieChat *smixie,
                                Main *bmain,
                                PointerRNA *scene_ptr,
                                PropertyRNA *prop,
                                const ChatLayoutMetrics &metrics,
                                const ChatImageStyle &image_style)
{
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  View2D *v2d = &region->v2d;

  wmWindow *win = CTX_wm_window(C);
  float action_zone_h = chat_ui_get_action_buttons_height(UI_SCALE_FAC);

  /* Compute slide-in animation state for newest message */
  float slide_x_offset = 0.0f;
  bool slide_anim_active = false;
  if (rt->slide_anim_msg_index >= 0) {
    double now = BLI_time_now_seconds();
    double elapsed = now - rt->slide_anim_start;
    const double anim_duration = 0.25;
    if (elapsed >= anim_duration) {
      rt->slide_anim_msg_index = -1;
    }
    else {
      slide_anim_active = true;
      float t = float(elapsed / anim_duration);
      /* Ease-out cubic: fast start, gentle deceleration */
      float progress = 1.0f - (1.0f - t) * (1.0f - t) * (1.0f - t);
      slide_x_offset = float(region->winx) * 0.3f * (1.0f - progress);
    }
  }

  /* Action buttons are always visible below messages (no hover-reveal). */

  /* Draw messages using cached layout (eliminates redundant calculations) */
  int message_index = 0;
  CollectionPropertyIterator iter{};

  RNA_property_collection_begin(scene_ptr, prop, &iter);

  while (iter.valid && message_index < rt->layout_cache.size()) {
    PointerRNA msg_ptr = iter.ptr;

    /* Check if we have renderable content (matches layout pass logic) */
    int text_len = g_msg_props.text ? RNA_property_string_length(&msg_ptr, g_msg_props.text) : 0;
    bool has_slot_content = false;
    if (text_len == 0) {
      int bubble_id_len = g_msg_props.bubble_id ?
          RNA_property_string_length(&msg_ptr, g_msg_props.bubble_id) : 0;
      if (bubble_id_len > 0) {
        bool loader_visible = g_msg_props.loader_visible ?
            RNA_property_boolean_get(&msg_ptr, g_msg_props.loader_visible) : false;
        int content_len = g_msg_props.content ?
            RNA_property_string_length(&msg_ptr, g_msg_props.content) : 0;
        int ephemeral_len = g_msg_props.ephemeral ?
            RNA_property_string_length(&msg_ptr, g_msg_props.ephemeral) : 0;
        int todo_count = g_msg_props.todo_items ?
            RNA_property_collection_length(&msg_ptr, g_msg_props.todo_items) : 0;
        int action_count = g_msg_props.action_items ?
            RNA_property_collection_length(&msg_ptr, g_msg_props.action_items) : 0;
        int step_count = g_msg_props.step_items ?
            RNA_property_collection_length(&msg_ptr, g_msg_props.step_items) : 0;
        int thinking_len = g_msg_props.thinking_text ?
            RNA_property_string_length(&msg_ptr, g_msg_props.thinking_text) : 0;
        bool thinking_active = g_msg_props.thinking_active ?
            RNA_property_boolean_get(&msg_ptr, g_msg_props.thinking_active) : false;
        (void)thinking_active;
        has_slot_content = loader_visible || (content_len > 0) || (ephemeral_len > 0) || (todo_count > 0) || (action_count > 0) || (step_count > 0) || (thinking_len > 0);
      }
    }
    bool has_renderable_content = (text_len > 0) || has_slot_content;

    if (has_renderable_content) {
      const MessageLayoutData &layout = rt->layout_cache[message_index];

      /* Visibility culling: skip drawing messages entirely outside viewport */
      float msg_top = layout.y_pos + layout.bubble_height + metrics.label_height;
      float msg_bottom = layout.y_pos - layout.slot_todo_height -
                         layout.slot_actions_height - layout.slot_steps_height -
                         layout.thinking_height - layout.feedback_row_height -
                         layout.feedback_submitted_comment_height -
                         layout.feedback_comment_input_height - action_zone_h;
      if (msg_top < v2d->cur.ymin || msg_bottom > v2d->cur.ymax) {
        message_index++;
        RNA_property_collection_next(&iter);
        continue;
      }

      /* Apply slide-in animation: offset the newest message horizontally */
      bool is_sliding = slide_anim_active && (message_index == rt->slide_anim_msg_index);
      if (is_sliding) {
        float x_off = layout.is_user ? slide_x_offset : -slide_x_offset;
        GPU_matrix_push();
        GPU_matrix_translate_2f(x_off, 0.0f);
      }

      /* Get text for drawing */
      char *text_buffer = nullptr;
      if (text_len > 0) {
        text_buffer = static_cast<char *>(MEM_new_uninitialized(text_len + 1, "chat_text"));
        RNA_property_string_get(&msg_ptr, g_msg_props.text, text_buffer);
      } else {
        text_buffer = static_cast<char *>(MEM_new_uninitialized(1, "chat_text"));
        text_buffer[0] = '\0';
      }

      /* Draw sender label using cached data */
      float label_y = layout.y_pos - metrics.label_height;
      const char *label = layout.is_error ? "Error" : (layout.is_user ? "You" : "Mixie");
      float label_x = layout.is_user ? (layout.bubble_x + layout.bubble_width)
                                     : layout.bubble_x;
      chat_ui_draw_sender_label(label, label_x,
                                label_y + 8.0f * metrics.scale_factor, &metrics,
                                layout.is_user);

      /* Render message content (slot-based or legacy) */
      mixie_chat_render_message_content(layout, &msg_ptr, text_len, text_buffer);

      /* Render slot todo items as single combined bubble below content */
      if (layout.is_slot_based && layout.slot_todo_count > 0) {
        /* Wall-clock pulse (~1 Hz blink for the 2-frame ● ○ dot) — the
         * animation pump supplies the redraws, the clock the phase. fmod
         * BEFORE the int cast: epoch seconds * 2 overflows int and the
         * conversion saturates to a constant (frozen dot). */
        int todo_spin_idx = int(fmod(BLI_time_now_seconds() * 2.0, 2.0));

        /* Build combined text with status icons */
        char combined_todo[SLOT_TODO_COMBINED_MAX];
        mixie_chat_build_todo_text(layout.slot_todo_items,
                                   layout.slot_todo_count,
                                   chat_anim_frame(CHAT_ANIM_PULSE_DOT, todo_spin_idx),
                                   combined_todo,
                                   sizeof(combined_todo));

        /* Draw single combined todo bubble. Todo text wraps at content_width
         * (see the layout pass), so the bubble must span the full content
         * area — bubble_width is fitted to the main text (e.g. a short
         * loader line) and can be narrower, which would let the wrapped
         * todo text overflow the bubble. Same formula as the steps card. */
        float todo_bubble_y = layout.y_pos - metrics.bubble_spacing;
        ChatBubbleStyle slot_todo_style = layout.style;
        chat_ui_get_prompt_button_color(slot_todo_style.bg_color);

        const float todo_block_width = layout.content_width +
                                       2.0f * slot_todo_style.h_padding +
                                       4.0f * UI_SCALE_FAC;
        chat_ui_draw_bubble(&slot_todo_style, combined_todo,
                            layout.bubble_x,
                            todo_bubble_y - layout.slot_todo_height,
                            todo_block_width, layout.slot_todo_height,
                            layout.content_width);
      }

      /* Render slot action buttons below content/todo bubbles */
      if (layout.is_slot_based && layout.slot_action_count > 0) {
        MessageLayoutData &mutable_layout =
            const_cast<MessageLayoutData &>(layout);
        /* Start below content and any todo items */
        float action_y = layout.y_pos - metrics.bubble_spacing;
        if (layout.slot_todo_height > 0.0f) {
          action_y -= layout.slot_todo_height + metrics.bubble_spacing;
        }

        /* Action labels wrap at content_width like the todo/steps cards, so
         * the buttons span the full content area too (bubble_width can be
         * narrower than the wrapped label). Bounds must match the draw. */
        const float action_block_width = layout.content_width +
                                         2.0f * layout.style.h_padding +
                                         4.0f * UI_SCALE_FAC;

        for (int i = 0; i < layout.slot_action_count; i++) {
          ActionSlotData &action = mutable_layout.slot_actions[i];

          /* Calculate bounds */
          action.bounds.xmin = layout.bubble_x;
          action.bounds.xmax = layout.bubble_x + action_block_width;
          action.bounds.ymin = action_y - action.height;
          action.bounds.ymax = action_y;

          /* Choose background color based on style and hover state */
          ChatBubbleStyle action_style = layout.style;
          if (action.style == 2) {
            /* Danger style - red tinted */
            float danger_color[4] = {0.8f, 0.2f, 0.2f, 0.3f};
            memcpy(action_style.bg_color, danger_color, sizeof(float) * 4);
          } else {
            chat_ui_get_prompt_button_color(action_style.bg_color);
          }

          /* Override with hover color if currently hovered */
          if (action.is_hovered) {
            if (action.style == 2) {
              float danger_hover[4] = {0.9f, 0.3f, 0.3f, 0.5f};
              memcpy(action_style.bg_color, danger_hover, sizeof(float) * 4);
            } else {
              memcpy(action_style.bg_color, layout.style.hover_color,
                     sizeof(float) * 4);
            }
          }

          /* Draw action bubble */
          chat_ui_draw_bubble(&action_style, action.label, action.bounds.xmin,
                              action.bounds.ymin, action_block_width,
                              action.height, layout.content_width);

          action_y -= action.height + metrics.bubble_spacing;
        }
      }

      /* Render steps block + finalized thinking below content/todo/actions */
      if (layout.is_slot_based && (layout.slot_steps_height > 0.0f ||
                                   layout.thinking_height > 0.0f)) {
        MessageLayoutData &ml = const_cast<MessageLayoutData &>(layout);

        /* Start below content, then todo, then actions. */
        float stack_y = layout.y_pos - metrics.bubble_spacing;
        if (layout.slot_todo_height > 0.0f) {
          stack_y -= layout.slot_todo_height + metrics.bubble_spacing;
        }
        if (layout.slot_actions_height > 0.0f) {
          stack_y -= layout.slot_actions_height + metrics.bubble_spacing;
        }

        /* Steps/thinking text wraps at content_width (see the calc
         * functions), so the card must span the full content area —
         * bubble_width is fitted to the main text and can be narrower,
         * which would let the wrapped text overflow the card. The trailing
         * 4*scale matches the text-bubble width formula in the layout pass
         * so card and bubble right edges align. */
        const float block_width =
            ml.content_width + 2.0f * ml.style.h_padding + 4.0f * UI_SCALE_FAC;

        if (ml.slot_steps_height > 0.0f) {
          chat_ui_draw_steps_block(&ml.style, &ml,
                                   ml.bubble_x,
                                   stack_y - ml.slot_steps_height,
                                   block_width,
                                   ml.content_width);
          stack_y -= ml.slot_steps_height + metrics.bubble_spacing;
        }

        if (ml.thinking_height > 0.0f) {
          ChatBubbleStyle think_style = ml.style;
          /* Wall-clock spinner: smooth at whatever rate the animation pump
           * delivers frames (the RNA index only ticked at 2 fps). */
          const int spin = chat_ui_spinner_frame();
          if (ml.has_content && ml.has_loader) {
            /* Working under the Plan: show the live loader status
             * ("Executing bpy script…", "Validating scene…", …). Same text +
             * fallback as the layout pass, so the wrapped height matches. */
            const char *status = chat_ui_loader_status_text(
                &ml.loader, ml.has_loader, "Working\xE2\x80\xA6");
            chat_ui_draw_live_thinking(&think_style, status, spin,
                                       ml.bubble_x,
                                       stack_y - ml.thinking_height,
                                       block_width, ml.thinking_height,
                                       ml.content_width);
          }
          else {
            chat_ui_draw_thinking_dropdown(&think_style, ml.thinking_text,
                                           ml.thinking_collapsed,
                                           ml.thinking_duration_ms,
                                           ml.bubble_x,
                                           stack_y - ml.thinking_height,
                                           block_width, ml.thinking_height,
                                           ml.content_width,
                                           &ml.thinking_header_bounds);
          }
          stack_y -= ml.thinking_height + metrics.bubble_spacing;
        }
      }

      /* Draw action buttons (copy, etc.) below every message — always visible. */
      if (layout.text_height > 0.0f && !layout.has_loader) {
        MessageLayoutData &mutable_layout =
            const_cast<MessageLayoutData &>(layout);

        /* Position buttons below all content (bubble + todo + slot actions) */
        float action_btn_y = layout.y_pos;
        if (layout.slot_todo_height > 0.0f) {
          action_btn_y -= metrics.bubble_spacing + layout.slot_todo_height;
        }
        if (layout.slot_actions_height > 0.0f) {
          action_btn_y -= metrics.bubble_spacing + layout.slot_actions_height;
        }
        if (layout.slot_steps_height > 0.0f) {
          action_btn_y -= metrics.bubble_spacing + layout.slot_steps_height;
        }
        if (layout.thinking_height > 0.0f) {
          action_btn_y -= metrics.bubble_spacing + layout.thinking_height;
        }

        /* Check copy feedback state (show checkmark for 1.5s after copy) */
        bool show_copied = false;
        if (rt->copy_feedback_msg_index == layout.message_index) {
          double elapsed = BLI_time_now_seconds() - rt->copy_feedback_time;
          if (elapsed < 1.5) {
            show_copied = true;
            ED_region_tag_redraw(region);
          } else {
            rt->copy_feedback_msg_index = -1;
          }
        }

        chat_ui_draw_action_buttons(layout.bubble_x,
                                     action_btn_y,
                                     layout.bubble_width,
                                     layout.bubble_height,
                                     false, /* show_retry */
                                     UI_SCALE_FAC,
                                     mutable_layout.action_buttons,
                                     &mutable_layout.action_button_count,
                                     layout.is_user,
                                     show_copied,
                                     1.0f);
      }

      mixie_chat_render_feedback(C, region, &msg_ptr, metrics, layout);

      /* Draw text selection highlight if this message is selected */
      if (smixie && smixie->sel_message_index == message_index &&
          smixie->sel_start != smixie->sel_end) {
        rctf text_rect;
        text_rect.xmin = layout.bubble_x + layout.style.h_padding;
        text_rect.xmax =
            layout.bubble_x + layout.style.h_padding + layout.content_width;
        text_rect.ymin = layout.y_pos + layout.style.v_padding;
        text_rect.ymax =
            layout.y_pos + layout.bubble_height - layout.style.v_padding;
        chat_ui_draw_text_selection(&text_rect, text_buffer, smixie->sel_start,
                                    smixie->sel_end, layout.style.font_size);
      }

      /* Draw attachments using cached data */
      if (layout.attachments_height > 0 && !layout.attachments.is_empty()) {
        float att_y =
            layout.y_pos + layout.bubble_height - layout.style.v_padding;

        for (const AttachmentLayout &att : layout.attachments) {
          chat_ui_draw_image_attachment(bmain, att.path, att.source,
                                        layout.bubble_x, att_y,
                                        layout.bubble_width, &image_style);
          att_y -= att.height;
        }
      }

      /* End slide-in animation transform */
      if (is_sliding) {
        GPU_matrix_pop();
      }

      MEM_freeN(text_buffer);
      message_index++;
    }

    RNA_property_collection_next(&iter);
  }

  RNA_property_collection_end(&iter);

  /* Update cursor based on slot action, action button, and feedback hover states */
  bool any_button_hovered = false;
  for (const MessageLayoutData &layout : rt->layout_cache) {
    for (int i = 0; i < layout.slot_action_count; i++) {
      if (layout.slot_actions[i].is_hovered) {
        any_button_hovered = true;
        break;
      }
    }
    if (!any_button_hovered) {
      for (int i = 0; i < layout.action_button_count; i++) {
        if (layout.action_buttons[i].is_hovered) {
          any_button_hovered = true;
          break;
        }
      }
    }
    /* Feedback stars intentionally keep the default cursor — the fill
     * preview is their hover affordance (see mixie_chat_main_region_cursor). */
    if (any_button_hovered) {
      break;
    }
  }

  if (win) {
    /* The Agent Bubble never shows the hand cursor (see
     * mixie_chat_main_region_cursor) — hover highlights still draw. */
    ScrArea *cursor_area = CTX_wm_area(C);
    const bool suppress_hand = (cursor_area &&
                                cursor_area->spacetype == SPACE_AGENT_BUBBLE);
    WM_cursor_set(win,
                  (any_button_hovered && !suppress_hand) ? WM_CURSOR_HAND :
                                                           WM_CURSOR_DEFAULT);
  }

  /* Request redraw while slide-in animation is active */
  if (slide_anim_active) {
    ED_region_tag_redraw(region);
  }
}

/** \} */
}  // namespace blender
