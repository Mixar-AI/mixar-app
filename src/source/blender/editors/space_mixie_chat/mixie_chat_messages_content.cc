/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Message content rendering: slot-based and legacy bubble drawing.
 * Handles the branching logic for different message types (markdown,
 * ephemeral, loader, todo, plain text).
 * Split from mixie_chat_messages_render.cc for modularity.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"

#include "BKE_main.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Message Content Rendering
 * \{ */

void mixie_chat_render_message_content(const MessageLayoutData &layout,
                                        PointerRNA *msg_ptr,
                                        int text_len,
                                        const char *display_text)
{
  if (layout.is_slot_based && text_len == 0) {
    /* Get content text - read fresh from RNA property since it may have been updated */
    char *slot_content = nullptr;
    int slot_content_len = g_msg_props.content ?
        RNA_property_string_length(msg_ptr, g_msg_props.content) : 0;
    if (slot_content_len > 0) {
      slot_content = static_cast<char *>(MEM_new_uninitialized(slot_content_len + 1, "slot_content"));
      RNA_property_string_get(msg_ptr, g_msg_props.content, slot_content);
    }

    if (slot_content_len > 0) {
      /* Check metadata for markdown segments */
      char *slot_meta_d = nullptr;
      bool slot_draw_md = false;
      if (g_msg_props.metadata) {
        int meta_len = RNA_property_string_length(msg_ptr, g_msg_props.metadata);
        if (meta_len > 0) {
          slot_meta_d = static_cast<char *>(MEM_new_uninitialized(meta_len + 1, "slot_meta_d"));
          RNA_property_string_get(msg_ptr, g_msg_props.metadata, slot_meta_d);
          slot_draw_md = chat_ui_has_markdown_segments(slot_meta_d);
        }
      }

      if (slot_draw_md) {
        /* Draw bubble background */
        rctf bubble_rect;
        bubble_rect.xmin = layout.bubble_x;
        bubble_rect.xmax = layout.bubble_x + layout.bubble_width;
        bubble_rect.ymin = layout.y_pos;
        bubble_rect.ymax = layout.y_pos + layout.bubble_height;
        chat_ui_draw_rounded_rect(&bubble_rect, layout.style.corner_radius,
                                  layout.style.bg_color);

        /* Neutral structural rail for the agent's prose blocks — quiet ground;
         * the single live accent belongs to the streaming blocks only. */
        const float plan_accent[4] = CHAT_ACCENT_PLAN;
        chat_ui_draw_accent_bar(layout.bubble_x, layout.y_pos,
                                layout.bubble_height, plan_accent, UI_SCALE_FAC);

        /* Draw markdown content */
        float content_x = layout.bubble_x + layout.style.h_padding;
        float content_y = layout.y_pos + layout.bubble_height - layout.style.v_padding;
        chat_ui_draw_markdown(slot_meta_d, content_x, content_y,
                              layout.content_width, &layout.style, 1.0f);
      } else {
        /* Fallback: plain text bubble */
        chat_ui_draw_bubble(&layout.style, slot_content, layout.bubble_x,
                            layout.y_pos, layout.bubble_width,
                            layout.bubble_height, layout.content_width);
      }

      if (slot_meta_d) {
        MEM_freeN(slot_meta_d);
      }
    } else if (layout.has_ephemeral) {
      /* Ephemeral text - read fresh from RNA and draw with FIFO scrolling */
      char *fresh_ephemeral = nullptr;
      int eph_len = g_msg_props.ephemeral ?
          RNA_property_string_length(msg_ptr, g_msg_props.ephemeral) : 0;
      if (eph_len > 0) {
        fresh_ephemeral = static_cast<char *>(MEM_new_uninitialized(eph_len + 1, "eph_draw"));
        RNA_property_string_get(msg_ptr, g_msg_props.ephemeral, fresh_ephemeral);
      }
      const char *eph_text = fresh_ephemeral ? fresh_ephemeral : "";
      /* Read loader state fresh for smooth animation. The spinner phase
       * comes from the wall clock (the RNA index only ticks at 2 fps). */
      LoaderSlotData fresh_loader = layout.loader;
      fresh_loader.spinner_frame = chat_ui_spinner_frame();
      if (layout.has_loader) {
        if (g_msg_props.loader_current_index) {
          fresh_loader.current_text_index =
              RNA_property_int_get(msg_ptr, g_msg_props.loader_current_index);
        }
      }
      chat_ui_draw_ephemeral_bubble(&layout.style,
                                    eph_text,
                                    &fresh_loader,
                                    layout.has_loader,
                                    layout.bubble_x,
                                    layout.y_pos,
                                    layout.bubble_width,
                                    layout.bubble_height,
                                    layout.content_width);
      if (fresh_ephemeral) {
        MEM_freeN(fresh_ephemeral);
      }
    } else if (layout.has_loader) {
      /* Loader only - spinner + current loader text */
      int current_index = 0;
      if (g_msg_props.loader_current_index) {
        current_index = RNA_property_int_get(msg_ptr, g_msg_props.loader_current_index);
      }
      const char *loader_text;
      /* Indices come straight from RNA int properties: clamp the lower bound
       * too — a stale/negative value would read out of bounds (C's `%` keeps
       * the sign, so `negative % 4` is also negative). */
      if (layout.loader.text_count > 0 && current_index >= 0 &&
          current_index < layout.loader.text_count)
      {
        loader_text = layout.loader.texts[current_index];
      }
      else {
        loader_text = "Loading...";
      }
      /* Wall-clock spinner phase (see chat_ui_spinner_frame). */
      const int spin_idx = chat_ui_spinner_frame();
      char loader_buf[512];
      snprintf(loader_buf, sizeof(loader_buf), "%s %s",
               chat_anim_frame(CHAT_ANIM_SPINNER, spin_idx), loader_text);
      chat_ui_draw_bubble(&layout.style, loader_buf, layout.bubble_x,
                          layout.y_pos, layout.bubble_width,
                          layout.bubble_height, layout.content_width);
    } else if (layout.has_todo || layout.has_actions || layout.has_steps ||
               layout.has_thinking) {
      /* Block-only message - no main bubble, the blocks render below */
    } else if (layout.bubble_height > 0.0f) {
      /* Fallback: empty bubble */
      chat_ui_draw_bubble(&layout.style, "", layout.bubble_x,
                          layout.y_pos, layout.bubble_width,
                          layout.bubble_height, layout.content_width);
    }

    /* Free slot content if allocated */
    if (slot_content) {
      MEM_freeN(slot_content);
    }
  }
  /* Legacy text-based message rendering */
  else {
    /* Get metadata to check for markdown segments */
    char *meta_buf = nullptr;
    if (g_msg_props.metadata) {
      int meta_len = RNA_property_string_length(msg_ptr, g_msg_props.metadata);
      if (meta_len > 0) {
        meta_buf = static_cast<char *>(MEM_new_uninitialized(meta_len + 1, "meta_draw"));
        RNA_property_string_get(msg_ptr, g_msg_props.metadata, meta_buf);
      }
    }

    if (meta_buf && chat_ui_has_markdown_segments(meta_buf)) {
      /* Draw bubble background */
      rctf bubble_rect;
      bubble_rect.xmin = layout.bubble_x;
      bubble_rect.xmax = layout.bubble_x + layout.bubble_width;
      bubble_rect.ymin = layout.y_pos;
      bubble_rect.ymax = layout.y_pos + layout.bubble_height;
      chat_ui_draw_rounded_rect(&bubble_rect, layout.style.corner_radius, layout.style.bg_color);

      /* Teal left accent bar for the agent's content / Plan block (this is the
       * path agent markdown actually takes — text mirrors content, so text_len
       * is non-zero) — same neutral structural rail as every settled block. */
      if (!layout.is_user) {
        const float plan_accent[4] = CHAT_ACCENT_PLAN;
        chat_ui_draw_accent_bar(layout.bubble_x, layout.y_pos,
                                layout.bubble_height, plan_accent, UI_SCALE_FAC);
      }

      /* Draw markdown content */
      float content_x = layout.bubble_x + layout.style.h_padding;
      float content_y = layout.y_pos + layout.bubble_height - layout.style.v_padding;
      chat_ui_draw_markdown(meta_buf, content_x, content_y,
                            layout.content_width, &layout.style, 1.0f);
    } else {
      /* Draw bubble with text and attachment offset */
      chat_ui_draw_bubble(&layout.style, display_text, layout.bubble_x,
                          layout.y_pos, layout.bubble_width,
                          layout.bubble_height, layout.content_width,
                          layout.attachments_height);
    }

    if (meta_buf) {
      MEM_freeN(meta_buf);
    }
  }
}

/** \} */
}  // namespace blender
