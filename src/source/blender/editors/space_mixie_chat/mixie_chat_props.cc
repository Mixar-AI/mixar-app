/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * RNA property cache for chat message properties.
 * Caches PropertyRNA pointers to avoid repeated lookups during drawing.
 */

#include "RNA_access.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Property Cache Globals
 * \{ */

ChatMessageProps g_msg_props = {};
ChatAttachmentProps g_att_props = {};
ChatTodoItemProps g_todo_props = {};
ChatActionItemProps g_action_props = {};
ChatImageItemProps g_image_props = {};
ChatStepItemProps g_step_props = {};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Property Cache Initialization
 * \{ */

void init_message_property_cache(PointerRNA *msg_ptr) {
  if (g_msg_props.initialized) {
    return;
  }

  /* Legacy properties */
  g_msg_props.sender = RNA_struct_find_property(msg_ptr, "sender");
  g_msg_props.text = RNA_struct_find_property(msg_ptr, "text");
  g_msg_props.attachments = RNA_struct_find_property(msg_ptr, "attachments");
  g_msg_props.message_type = RNA_struct_find_property(msg_ptr, "message_type");
  g_msg_props.metadata = RNA_struct_find_property(msg_ptr, "metadata");

  /* Slot-based properties */
  g_msg_props.bubble_id = RNA_struct_find_property(msg_ptr, "bubble_id");
  g_msg_props.loader_visible = RNA_struct_find_property(msg_ptr, "loader_visible");
  g_msg_props.loader_texts = RNA_struct_find_property(msg_ptr, "loader_texts");
  g_msg_props.loader_rotate_ms = RNA_struct_find_property(msg_ptr, "loader_rotate_ms");
  g_msg_props.loader_current_index = RNA_struct_find_property(msg_ptr, "loader_current_index");
  g_msg_props.loader_spinner_index = RNA_struct_find_property(msg_ptr, "loader_spinner_index");
  g_msg_props.content = RNA_struct_find_property(msg_ptr, "content");
  g_msg_props.ephemeral = RNA_struct_find_property(msg_ptr, "ephemeral");
  g_msg_props.todo_items = RNA_struct_find_property(msg_ptr, "todo_items");
  g_msg_props.action_items = RNA_struct_find_property(msg_ptr, "action_items");
  g_msg_props.image_items = RNA_struct_find_property(msg_ptr, "image_items");

  /* Feedback properties */
  g_msg_props.feedback_visible = RNA_struct_find_property(msg_ptr, "feedback_visible");
  g_msg_props.feedback_rating = RNA_struct_find_property(msg_ptr, "feedback_rating");
  g_msg_props.feedback_comment_expanded = RNA_struct_find_property(
      msg_ptr, "feedback_comment_expanded");
  g_msg_props.feedback_status = RNA_struct_find_property(msg_ptr, "feedback_status");
  g_msg_props.feedback_submitted_comment = RNA_struct_find_property(
      msg_ptr, "feedback_submitted_comment");
  g_msg_props.feedback_comment = RNA_struct_find_property(msg_ptr, "feedback_comment");

  g_msg_props.step_items = RNA_struct_find_property(msg_ptr, "step_items");
  g_msg_props.steps_summary = RNA_struct_find_property(msg_ptr, "steps_summary");
  g_msg_props.steps_collapsed = RNA_struct_find_property(msg_ptr, "steps_collapsed");
  g_msg_props.thinking_text = RNA_struct_find_property(msg_ptr, "thinking_text");
  g_msg_props.thinking_active = RNA_struct_find_property(msg_ptr, "thinking_active");
  g_msg_props.thinking_duration_ms =
      RNA_struct_find_property(msg_ptr, "thinking_duration_ms");
  g_msg_props.thinking_collapsed =
      RNA_struct_find_property(msg_ptr, "thinking_collapsed");

  g_msg_props.initialized = true;

}

void init_todo_item_property_cache(PointerRNA *item_ptr) {
  if (g_todo_props.initialized) {
    return;
  }
  g_todo_props.item_id = RNA_struct_find_property(item_ptr, "item_id");
  g_todo_props.text = RNA_struct_find_property(item_ptr, "text");
  g_todo_props.status = RNA_struct_find_property(item_ptr, "status");
  g_todo_props.initialized = true;
}

void init_step_item_property_cache(PointerRNA *item_ptr) {
  if (g_step_props.initialized) {
    return;
  }
  g_step_props.item_id = RNA_struct_find_property(item_ptr, "item_id");
  g_step_props.kind = RNA_struct_find_property(item_ptr, "kind");
  g_step_props.label = RNA_struct_find_property(item_ptr, "label");
  g_step_props.target = RNA_struct_find_property(item_ptr, "target");
  g_step_props.detail = RNA_struct_find_property(item_ptr, "detail");
  g_step_props.status = RNA_struct_find_property(item_ptr, "status");
  g_step_props.expanded = RNA_struct_find_property(item_ptr, "expanded");
  g_step_props.initialized = true;
}

void init_action_item_property_cache(PointerRNA *item_ptr) {
  if (g_action_props.initialized) {
    return;
  }
  g_action_props.label = RNA_struct_find_property(item_ptr, "label");
  g_action_props.value = RNA_struct_find_property(item_ptr, "value");
  g_action_props.style = RNA_struct_find_property(item_ptr, "style");
  /* Optional (asset-picker thumbnails) — null with an older scripts overlay. */
  g_action_props.image = RNA_struct_find_property(item_ptr, "image");
  g_action_props.initialized = true;
}

void init_image_item_property_cache(PointerRNA *item_ptr) {
  if (g_image_props.initialized) {
    return;
  }
  g_image_props.url = RNA_struct_find_property(item_ptr, "url");
  g_image_props.alt = RNA_struct_find_property(item_ptr, "alt");
  g_image_props.caption = RNA_struct_find_property(item_ptr, "caption");
  g_image_props.thumbnail_url = RNA_struct_find_property(item_ptr, "thumbnail_url");
  g_image_props.local_path = RNA_struct_find_property(item_ptr, "local_path");
  g_image_props.width = RNA_struct_find_property(item_ptr, "width");
  g_image_props.height = RNA_struct_find_property(item_ptr, "height");
  g_image_props.initialized = true;
}

void init_attachment_property_cache(PointerRNA *att_ptr) {
  if (g_att_props.initialized) {
    return;
  }

  g_att_props.image_path = RNA_struct_find_property(att_ptr, "image_path");
  g_att_props.image_source = RNA_struct_find_property(att_ptr, "image_source");
  g_att_props.display_name = RNA_struct_find_property(att_ptr, "display_name");
  g_att_props.initialized = true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Property Cache Reset
 * \{ */

void mixie_chat_clear_property_caches() {
  /* Reset message props */
  g_msg_props = {};

  /* Reset attachment props */
  g_att_props = {};

  /* Reset slot item props */
  g_todo_props = {};
  g_action_props = {};
  g_image_props = {};
  g_step_props = {};
}

/** \} */
}  // namespace blender
