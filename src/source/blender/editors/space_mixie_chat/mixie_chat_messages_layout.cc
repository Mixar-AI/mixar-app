/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Layout cache builder for chat messages.
 * Calculates message dimensions and positions, storing results in a
 * per-instance cache to avoid redundant RNA reads and BLF measurements
 * every frame. Split from mixie_chat_messages.cc for modularity.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_vector.hh"

#include "BKE_main.hh"

#include "BLF_api.hh"

#include "DNA_space_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "UI_resources.hh"

#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Combined Todo Text
 * \{ */

size_t mixie_chat_build_todo_text(const TodoItemSlotData *items,
                                  const int count,
                                  const char *in_progress_icon,
                                  char *buf,
                                  const size_t buf_maxncpy)
{
  buf[0] = '\0';
  size_t offset = 0;
  for (int i = 0; i < count; i++) {
    const TodoItemSlotData &todo = items[i];
    const char *icon = (todo.status == 0) ? "\xe2\x97\x8b" : /* pending */
                       (todo.status == 1) ? in_progress_icon :
                       (todo.status == 2) ? "\xe2\x9c\x94" : /* done */
                                            "\xe2\x9c\x98";  /* failed */
    /* `_rlen` returns the bytes actually written (not the would-be length
     * like BLI_snprintf), so `offset` can never pass `buf_maxncpy` and the
     * remaining-space math below can't underflow into a huge size_t —
     * which previously overflowed the stack on long todo plans. */
    offset += BLI_snprintf_rlen(
        buf + offset, buf_maxncpy - offset, (i > 0) ? "\n%s %s" : "%s %s", icon, todo.text);
    if (offset >= buf_maxncpy - 1) {
      break; /* Buffer full: truncate, never overflow. */
    }
  }
  return offset;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Attachment Height Calculation
 * \{ */

/**
 * Calculate attachments height and build cache.
 * Stores attachment data to avoid redundant iteration during drawing.
 */
static float calculate_attachments_height(
    Main *bmain, PointerRNA *msg_ptr, const ChatImageStyle *image_style,
    blender::Vector<AttachmentLayout> *out_attachments) {
  if (!g_msg_props.attachments) {
    return 0.0f;
  }

  int att_count =
      RNA_property_collection_length(msg_ptr, g_msg_props.attachments);
  if (att_count == 0) {
    return 0.0f;
  }

  float total_height = 0.0f;
  CollectionPropertyIterator att_iter{};

  RNA_property_collection_begin(msg_ptr, g_msg_props.attachments, &att_iter);

  /* Initialize attachment property cache */
  if (att_iter.valid) {
    init_attachment_property_cache(&att_iter.ptr);
  }

  while (att_iter.valid) {
    PointerRNA att_ptr = att_iter.ptr;

    if (g_att_props.image_path && g_att_props.image_source) {
      /* Dynamically allocate path buffer based on actual string length */
      int path_len =
          RNA_property_string_length(&att_ptr, g_att_props.image_path);
      char *path_buffer =
          static_cast<char *>(MEM_mallocN(path_len + 1, "chat_img_path"));
      RNA_property_string_get(&att_ptr, g_att_props.image_path, path_buffer);
      int source = RNA_property_enum_get(&att_ptr, g_att_props.image_source);

      if (path_buffer[0] != '\0') {
        float img_height = chat_ui_calc_image_attachment_height(
            bmain, path_buffer, source, image_style);
        total_height += img_height;

        /* Cache attachment data for later drawing */
        if (out_attachments) {
          AttachmentLayout att_layout;
          strncpy(att_layout.path, path_buffer, sizeof(att_layout.path) - 1);
          att_layout.path[sizeof(att_layout.path) - 1] =
              '\0'; /* Ensure null termination */
          att_layout.source = source;
          att_layout.height = img_height;
          out_attachments->append(att_layout);
        }
      }

      /* Free dynamically allocated path buffer */
      MEM_freeN(path_buffer);
    }

    RNA_property_collection_next(&att_iter);
  }

  RNA_property_collection_end(&att_iter);

  return total_height;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Layout Cache Builder
 * \{ */

float mixie_chat_build_layout_cache(SpaceMixieChat *smixie,
                                    Main *bmain,
                                    PointerRNA *scene_ptr,
                                    PropertyRNA *prop,
                                    const ChatLayoutMetrics &metrics,
                                    const ChatImageStyle &image_style,
                                    int winx,
                                    int msg_count)
{
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  const float max_bubble_width = float(winx) * metrics.max_bubble_width_ratio;

  /* Build layout cache in two passes for proper top-to-bottom ordering.
   * Pass 1: Calculate all message heights to determine total height.
   * Pass 2: Position messages from top to bottom (newest at bottom). */

  /* Pass 1: Calculate message dimensions and total height */
  mixie_chat_clear_layout_cache(smixie); /* Clear previous frame's cache */
  float total_height = metrics.padding; /* Start with top padding */
  int message_index = 0;
  CollectionPropertyIterator iter{};

  RNA_property_collection_begin(scene_ptr, prop, &iter);

  /* Initialize property cache from first item */
  if (iter.valid) {
    init_message_property_cache(&iter.ptr);
  }

  while (iter.valid) {
    PointerRNA msg_ptr = iter.ptr;

    /* Check if this is a slot-based message first */
    MessageLayoutData layout;
    layout.attachments.clear();
    /* MessageLayoutData has no member initializers and `layout` is a reused
     * stack local, so any height that is only set conditionally below would
     * otherwise inherit the PREVIOUS message's value. thinking_height in
     * particular is never set for messages without a thinking block (e.g. user
     * messages), so it would carry over the prior agent message's value and
     * reserve a phantom empty block — the gap above the plan. Zero them up front. */
    layout.bubble_height = 0.0f;
    layout.text_height = 0.0f;
    layout.attachments_height = 0.0f;
    layout.slot_todo_height = 0.0f;
    layout.slot_actions_height = 0.0f;
    layout.slot_images_height = 0.0f;
    layout.slot_steps_height = 0.0f;
    layout.thinking_height = 0.0f;
    bool is_slot_msg = populate_slot_layout_data(&msg_ptr, &layout);

    /* For slot-based messages, we may have no text but still need to render slots */
    int text_len = g_msg_props.text ? RNA_property_string_length(&msg_ptr, g_msg_props.text) : 0;
    bool has_renderable_content = (text_len > 0) || (is_slot_msg && (layout.has_loader || layout.has_content || layout.has_ephemeral || layout.has_todo || layout.has_actions || layout.has_steps || layout.has_thinking));

    if (has_renderable_content) {
      /* Dynamically allocate text buffer based on actual string length */
      char *text_buffer = nullptr;
      if (text_len > 0) {
        text_buffer = static_cast<char *>(MEM_mallocN(text_len + 1, "chat_text"));
        RNA_property_string_get(&msg_ptr, g_msg_props.text, text_buffer);
      } else {
        /* Empty text buffer for slot-based messages with no content */
        text_buffer = static_cast<char *>(MEM_mallocN(1, "chat_text"));
        text_buffer[0] = '\0';
      }

      /* Get style based on sender */
      int sender_enum =
          g_msg_props.sender
              ? RNA_property_enum_get(&msg_ptr, g_msg_props.sender)
              : 0;
      bool is_user = (sender_enum == 0);
      ChatBubbleStyle style = is_user
                                  ? chat_ui_get_user_bubble_style(&metrics)
                                  : chat_ui_get_agent_bubble_style(&metrics);

      /* Check for error message type and apply error styling */
      int msg_type_enum = g_msg_props.message_type
                              ? RNA_property_enum_get(&msg_ptr, g_msg_props.message_type)
                              : 0;
      bool is_error = (msg_type_enum == 3); /* ERROR = 3 in Python enum */
      if (is_error) {
        float err_bg[4] = CHAT_ERROR_BG_COLOR;
        memcpy(style.bg_color, err_bg, sizeof(float) * 4);
      }

      const char *calc_text = text_buffer;

      /* Calculate content dimensions */
      float content_width = max_bubble_width - style.h_padding * 2.0f;
      float text_width, text_height;

      /* Handle slot-based messages (loader-only or with content) */
      if (is_slot_msg && text_len == 0) {
        if (layout.has_content && layout.content_text) {
          /* Check metadata for markdown segments */
          char *slot_meta_h = nullptr;
          bool slot_has_md = false;
          if (g_msg_props.metadata) {
            int meta_len = RNA_property_string_length(&msg_ptr, g_msg_props.metadata);
            if (meta_len > 0) {
              slot_meta_h = static_cast<char *>(MEM_mallocN(meta_len + 1, "slot_meta_h"));
              RNA_property_string_get(&msg_ptr, g_msg_props.metadata, slot_meta_h);
              slot_has_md = chat_ui_has_markdown_segments(slot_meta_h);
            }
          }

          if (slot_has_md) {
            text_height = chat_ui_calc_markdown_height(slot_meta_h, &style, content_width, 1.0f);
            text_width = content_width;
          } else {
            chat_ui_calc_text_bounds(layout.content_text, content_width, style.font_size, 0,
                                     &text_width, &text_height);
          }

          if (slot_meta_h) {
            MEM_freeN(slot_meta_h);
          }
        } else if (layout.has_ephemeral) {
          /* Ephemeral text - wrapped status line + fixed 4-line FIFO body.
           * Status text MUST match what chat_ui_draw_ephemeral_bubble shows. */
          float fixed_bubble_height = chat_ui_calc_ephemeral_bubble_height(
              &style,
              chat_ui_loader_status_text(&layout.loader, layout.has_loader, "Processing..."),
              content_width);
          text_height = fixed_bubble_height - style.v_padding * 2.0f;
          text_width = content_width;
        } else if (layout.has_loader) {
          /* Loader-only - spinner + loader text for sizing */
          const char *loader_text = "Loading...";
          if (layout.loader.text_count > 0 && layout.loader.current_text_index < layout.loader.text_count) {
            loader_text = layout.loader.texts[layout.loader.current_text_index];
          }
          char loader_buf[512];
          /* Wall-clock spinner (glyphs are same-advance, so any frame
           * measures identically — this just matches the draw pass). */
          snprintf(loader_buf, sizeof(loader_buf), "%s %s",
                   chat_anim_frame(CHAT_ANIM_SPINNER, chat_ui_spinner_frame()), loader_text);
          chat_ui_calc_text_bounds(loader_buf, content_width, style.font_size, 0,
                                   &text_width, &text_height);
          /* Ensure minimum height for loader bubble */
          float min_loader_height = style.font_size * 1.5f;
          if (text_height < min_loader_height) {
            text_height = min_loader_height;
          }
        } else if (layout.has_todo || layout.has_actions || layout.has_steps ||
                   layout.has_thinking) {
          /* Block-only message (todo/actions/steps/thinking) - the blocks
           * render as their own cards; no main bubble text, no copy button. */
          text_width = content_width;
          text_height = 0;
        } else {
          /* Slot message with no content or loader - handle gracefully */
          text_width = 0;
          text_height = style.font_size * 1.5f;
        }
      } else {
        /* Check for markdown segments in metadata */
        char *meta_buf_height = nullptr;
        if (g_msg_props.metadata) {
          int meta_len = RNA_property_string_length(&msg_ptr, g_msg_props.metadata);
          if (meta_len > 0) {
            meta_buf_height = static_cast<char *>(MEM_mallocN(meta_len + 1, "meta_height"));
            RNA_property_string_get(&msg_ptr, g_msg_props.metadata, meta_buf_height);
          }
        }

        if (meta_buf_height && chat_ui_has_markdown_segments(meta_buf_height)) {
          /* Use markdown height calculation */
          text_height = chat_ui_calc_markdown_height(meta_buf_height, &style, content_width, 1.0f);
          text_width = content_width;
        } else {
          chat_ui_calc_text_bounds(calc_text, content_width, style.font_size, 0,
                                   &text_width, &text_height);
        }

        if (meta_buf_height) {
          MEM_freeN(meta_buf_height);
        }
      }

      /* Calculate attachment height and cache attachment data */
      float attachments_height = calculate_attachments_height(
          bmain, &msg_ptr, &image_style, &layout.attachments);

      /* Calculate bubble dimensions */
      float bubble_width = text_width + style.h_padding * 2.0f + 4.0f * UI_SCALE_FAC;
      float bubble_height =
          text_height + attachments_height + style.v_padding * 2.0f;

      /* Block-only messages (todo/actions/steps/thinking with no text or
       * attachments) have no main bubble at all — the blocks are the
       * message. Without this, the empty bubble renders as a blank pill. */
      if (is_slot_msg && text_height <= 0.0f && attachments_height <= 0.0f &&
          !layout.has_loader &&
          (layout.has_todo || layout.has_actions || layout.has_steps ||
           layout.has_thinking))
      {
        bubble_height = 0.0f;
      }

      /* Minimum bubble width */
      float min_width = 100.0f * metrics.scale_factor;
      if (attachments_height > 0) {
        min_width = image_style.max_width + image_style.margin * 2.0f +
                    style.h_padding * 2.0f;
      }
      if (bubble_width < min_width) {
        bubble_width = min_width;
      }

      /* Position: user right-aligned, agent left-aligned */
      float bubble_x = is_user ? (float(winx) - bubble_width - metrics.padding)
                               : metrics.padding;

      /* Legacy option bubble fields - zeroed out (no longer used) */
      layout.option_bubble_count = 0;
      layout.option_bubbles_total_height = 0.0f;
      layout.is_todo_list = false;
      layout.todo_combined_text = nullptr;
      layout.todo_combined_text_height = 0.0f;
      layout.is_thinking_message = false;

      /* Calculate slot todo combined bubble height (single bubble for all items) */
      if (is_slot_msg && layout.has_todo && layout.slot_todo_count > 0) {
        /* Build combined text with status icons for all todo items */
        char combined_todo[SLOT_TODO_COMBINED_MAX];
        mixie_chat_build_todo_text(layout.slot_todo_items,
                                   layout.slot_todo_count,
                                   chat_anim_frame(CHAT_ANIM_PULSE_DOT, 0),
                                   combined_todo,
                                   sizeof(combined_todo));
        float combined_width, combined_height;
        chat_ui_calc_text_bounds(combined_todo, content_width, style.font_size, 0,
                                 &combined_width, &combined_height);
        layout.slot_todo_height = combined_height + style.v_padding * 2.0f;
      }

      /* Calculate slot action button heights */
      if (is_slot_msg && layout.has_actions && layout.slot_action_count > 0) {
        layout.slot_actions_height = 0.0f;
        for (int i = 0; i < layout.slot_action_count; i++) {
          ActionSlotData &action = layout.slot_actions[i];
          float action_text_width, action_text_height;
          chat_ui_calc_text_bounds(
              action.label, content_width, style.font_size, 0,
              &action_text_width, &action_text_height);
          action.height = action_text_height + style.v_padding * 1.5f;
          layout.slot_actions_height += action.height;
          if (i > 0) {
            layout.slot_actions_height += metrics.bubble_spacing;
          }
        }
      }

      /* Calculate steps block height */
      if (is_slot_msg && layout.has_steps && layout.slot_step_count > 0) {
        layout.slot_steps_height =
            chat_ui_calc_steps_block_height(&style, &layout, content_width);
      }

      /* Live activity line vs finalized dropdown.
       * - Live single line ONLY for a content bubble with a running loader
       *   (the "Executing/Validating/Rendering…" status under the prose).
       * - Streaming narration is displayed by the ephemeral FIFO panel (its
       *   own spinner + status header) — never as a one-line ticker here:
       *   the ticker could only show a stale, tail-truncated snapshot.
       * - Any finalized reasoning (thinking_text) renders as the "Thought
       *   for Ns" dropdown, even while a new phase streams in the FIFO. */
      bool live_line = is_slot_msg && !is_user &&
                       layout.has_content && layout.has_loader;
      if (live_line) {
        /* Status text MUST match the render pass (messages_render.cc), which
         * draws the same loader status with the same fallback. */
        layout.thinking_height = chat_ui_calc_live_thinking_height(
            &style,
            chat_ui_loader_status_text(&layout.loader, layout.has_loader, "Working\xE2\x80\xA6"),
            content_width);
      }
      else if (is_slot_msg && !is_user && layout.has_thinking) {
        layout.thinking_height = chat_ui_calc_thinking_dropdown_height(
            &style, layout.thinking_text, layout.thinking_collapsed, content_width);
      }

      /* Accumulate total height */
      total_height += metrics.label_height;
      total_height += bubble_height;
      if (layout.slot_todo_height > 0.0f) {
        total_height += metrics.bubble_spacing;
        total_height += layout.slot_todo_height;
      }
      if (layout.slot_actions_height > 0.0f) {
        total_height += metrics.bubble_spacing;
        total_height += layout.slot_actions_height;
      }
      if (layout.slot_steps_height > 0.0f) {
        total_height += metrics.bubble_spacing;
        total_height += layout.slot_steps_height;
      }
      if (layout.thinking_height > 0.0f) {
        total_height += metrics.bubble_spacing;
        total_height += layout.thinking_height;
      }
      /* Add copy action button height for messages with text */
      if (text_height > 0.0f && !layout.has_loader) {
        total_height += chat_ui_get_action_buttons_height(UI_SCALE_FAC);
      }
      total_height += metrics.bubble_spacing;

      /* Store layout data (y_pos will be set in pass 2) */
      layout.y_pos = 0; /* Temporary */
      layout.bubble_x = bubble_x;
      layout.bubble_width = bubble_width;
      layout.bubble_height = bubble_height;
      layout.content_width = content_width;
      layout.text_height = text_height;
      layout.attachments_height = attachments_height;
      layout.style = style;
      layout.message_index = message_index;
      layout.is_user = is_user;
      layout.is_error = is_error;
      layout.action_button_count = 0;

      /* Cache the copyable text: content (slot) > text (legacy).
       * This avoids any index-based RNA collection lookup at copy time. */
      layout.copy_text = nullptr;
      if (layout.content_text && layout.content_text[0] != '\0') {
        layout.copy_text = BLI_strdup(layout.content_text);
      } else if (text_len > 0) {
        layout.copy_text = BLI_strdup(text_buffer);
      }

      rt->layout_cache.append(layout);

      /* Free dynamically allocated text buffer */
      MEM_freeN(text_buffer);
      message_index++;
    }

    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);

  total_height += metrics.padding; /* Add bottom padding for symmetry */

  /* Pass 2: Position messages from top to bottom (oldest at top, newest at bottom) */
  float y_pos = total_height - metrics.padding;
  for (MessageLayoutData &layout : rt->layout_cache) {
    y_pos -= metrics.label_height;
    y_pos -= layout.bubble_height;
    layout.y_pos = y_pos;

    if (layout.slot_todo_height > 0.0f) {
      y_pos -= metrics.bubble_spacing;
      y_pos -= layout.slot_todo_height;
    }

    if (layout.slot_actions_height > 0.0f) {
      y_pos -= metrics.bubble_spacing;
      y_pos -= layout.slot_actions_height;
    }

    if (layout.slot_steps_height > 0.0f) {
      y_pos -= metrics.bubble_spacing;
      y_pos -= layout.slot_steps_height;
    }

    if (layout.thinking_height > 0.0f) {
      y_pos -= metrics.bubble_spacing;
      y_pos -= layout.thinking_height;
    }

    if (layout.text_height > 0.0f && !layout.has_loader) {
      y_pos -= chat_ui_get_action_buttons_height(UI_SCALE_FAC);
    }

    y_pos -= metrics.bubble_spacing;
  }

  /* Update cache tracking state after rebuild */
  rt->prev_had_active_stream = false;
  for (const MessageLayoutData &layout_check : rt->layout_cache) {
    if (layout_check.has_loader || layout_check.has_ephemeral) {
      rt->prev_had_active_stream = true;
      break;
    }
  }
  rt->prev_msg_count = msg_count;
  rt->prev_winx = winx;
  {
    PropertyRNA *epoch_prop =
        RNA_struct_find_property(scene_ptr, "mixie_chat_layout_epoch");
    rt->prev_layout_epoch =
        epoch_prop ? RNA_property_int_get(scene_ptr, epoch_prop) : 0;
  }
  rt->cached_total_height = total_height;

  return total_height;
}

/** \} */
