/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Slot-based message detection and data population.
 * Reads RNA properties to populate MessageLayoutData slot fields.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"

#include "RNA_access.hh"

#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name RNA String Helpers
 * \{ */

/* Safely read an RNA string into a fixed buffer (RNA_property_string_get is
 * unbounded). Uses the fixed buffer when the string fits, else heap-allocs and
 * truncate-copies, so we never overflow `dst`. */
static void read_rna_string_bounded(PointerRNA *ptr,
                                    PropertyRNA *prop,
                                    char *dst,
                                    size_t dstsize)
{
  if (!prop) {
    return;
  }
  char *buf = RNA_property_string_get_alloc(ptr, prop, dst, int(dstsize), nullptr);
  if (buf != dst) {
    BLI_strncpy(dst, buf, dstsize);
    MEM_freeN(buf);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Slot-Based Message Detection
 * \{ */

/**
 * Check if a message is slot-based (has bubble_id set).
 * Slot-based messages use the new rendering architecture.
 */
static bool is_slot_based_message(PointerRNA *msg_ptr) {
  if (!g_msg_props.bubble_id) {
    return false;
  }
  int bubble_id_len = RNA_property_string_length(msg_ptr, g_msg_props.bubble_id);
  if (bubble_id_len > 0) {
    return true;
  }
  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Slot Data Population
 * \{ */

/**
 * Populate slot presence flags and data for a slot-based message.
 * Returns true if the message is slot-based, false otherwise.
 */
bool populate_slot_layout_data(PointerRNA *msg_ptr, MessageLayoutData *layout) {
  /* CRITICAL: Initialize all slot pointer fields to nullptr FIRST.
   * This prevents mixie_chat_clear_layout_cache() from trying to free
   * uninitialized (garbage) pointers, which causes "pointer being freed
   * was not allocated" crashes. */
  layout->content_text = nullptr;
  layout->ephemeral_text = nullptr;

  if (!is_slot_based_message(msg_ptr)) {
    layout->is_slot_based = false;
    layout->has_loader = false;
    layout->has_content = false;
    layout->has_ephemeral = false;
    layout->has_todo = false;
    layout->has_actions = false;
    layout->has_images = false;
    layout->has_feedback = false;
    layout->feedback_rating = 0;
    layout->feedback_row_height = 0.0f;
    layout->feedback_comment_hovered = false;
    layout->feedback_comment_expanded = false;
    layout->feedback_comment_input_height = 0.0f;
    layout->feedback_status = FEEDBACK_STATUS_IDLE;
    layout->feedback_submitted_comment[0] = '\0';
    layout->feedback_submitted_comment_height = 0.0f;
    layout->bubble_id[0] = '\0';
    layout->slot_action_count = 0;
    layout->slot_actions_height = 0.0f;
    layout->slot_todo_count = 0;
    layout->slot_todo_height = 0.0f;
    layout->slot_image_count = 0;
    layout->slot_images_height = 0.0f;
    layout->has_steps = false;
    layout->slot_step_count = 0;
    layout->slot_steps_height = 0.0f;
    layout->has_thinking = false;
    layout->thinking_text[0] = '\0';
    memset(&layout->steps_header_bounds, 0, sizeof(layout->steps_header_bounds));
    memset(&layout->thinking_header_bounds, 0, sizeof(layout->thinking_header_bounds));
    return false;
  }

  layout->is_slot_based = true;

  /* Check loader slot */
  layout->has_loader = g_msg_props.loader_visible &&
                       RNA_property_boolean_get(msg_ptr, g_msg_props.loader_visible);

  /* Check content slot */
  int content_len = g_msg_props.content ?
      RNA_property_string_length(msg_ptr, g_msg_props.content) : 0;
  layout->has_content = content_len > 0;

  /* Check ephemeral slot. Guard: the backend streams a raw JSON intent payload
   * into the ephemeral slot token-by-token, and the Python suppression can miss
   * it (classification is timing/shape dependent). An unsuppressed JSON
   * ephemeral renders as the fixed tall ephemeral block — a large empty gap
   * between the user message and the plan. So never treat a JSON-looking
   * ephemeral as renderable: if the text (after whitespace) starts with '{' or
   * '[', it's an intent payload, not prose. */
  int ephemeral_len = g_msg_props.ephemeral ?
      RNA_property_string_length(msg_ptr, g_msg_props.ephemeral) : 0;
  layout->has_ephemeral = ephemeral_len > 0;
  if (ephemeral_len > 0) {
    char *eph_probe = static_cast<char *>(MEM_mallocN(ephemeral_len + 1, "eph_probe"));
    RNA_property_string_get(msg_ptr, g_msg_props.ephemeral, eph_probe);
    const char *p = eph_probe;
    while (*p == ' ' || *p == '\n' || *p == '\t' || *p == '\r') {
      p++;
    }
    if (*p == '{' || *p == '[') {
      layout->has_ephemeral = false;
    }
    MEM_freeN(eph_probe);
  }

  /* Check todo items collection */
  int todo_count = g_msg_props.todo_items ?
      RNA_property_collection_length(msg_ptr, g_msg_props.todo_items) : 0;
  layout->has_todo = todo_count > 0;

  /* Check action items collection */
  int action_count = g_msg_props.action_items ?
      RNA_property_collection_length(msg_ptr, g_msg_props.action_items) : 0;
  layout->has_actions = action_count > 0;

  /* Check image items collection */
  int image_count = g_msg_props.image_items ?
      RNA_property_collection_length(msg_ptr, g_msg_props.image_items) : 0;
  layout->has_images = image_count > 0;

  /* Check steps collection */
  int step_count = g_msg_props.step_items ?
      RNA_property_collection_length(msg_ptr, g_msg_props.step_items) : 0;
  layout->has_steps = step_count > 0;

  /* Thinking block: rendered whether streaming (live pinned panel) or
   * finalized (collapsible "Thought for Ns" dropdown). */
  int thinking_len = g_msg_props.thinking_text ?
      RNA_property_string_length(msg_ptr, g_msg_props.thinking_text) : 0;
  bool thinking_active = g_msg_props.thinking_active &&
      RNA_property_boolean_get(msg_ptr, g_msg_props.thinking_active);
  layout->has_thinking = (thinking_len > 0);
  layout->thinking_active = thinking_active;

  /* Populate loader data if present */
  if (layout->has_loader) {
    layout->loader.visible = true;
    layout->loader.current_text_index = g_msg_props.loader_current_index ?
        RNA_property_int_get(msg_ptr, g_msg_props.loader_current_index) : 0;
    layout->loader.rotate_ms = g_msg_props.loader_rotate_ms ?
        RNA_property_int_get(msg_ptr, g_msg_props.loader_rotate_ms) : 2000;
    layout->loader.spinner_frame = g_msg_props.loader_spinner_index ?
        RNA_property_int_get(msg_ptr, g_msg_props.loader_spinner_index) : 0;

    /* Parse loader texts JSON */
    if (g_msg_props.loader_texts) {
      int texts_len = RNA_property_string_length(msg_ptr, g_msg_props.loader_texts);
      if (texts_len > 0) {
        char *texts_json = static_cast<char *>(MEM_mallocN(texts_len + 1, "loader_texts"));
        RNA_property_string_get(msg_ptr, g_msg_props.loader_texts, texts_json);

        /* Simple JSON array parsing - just count texts for now */
        /* Full parsing would extract individual strings */
        layout->loader.text_count = 0;
        const char *ptr = texts_json;
        while (*ptr && layout->loader.text_count < SLOT_MAX_LOADER_TEXTS) {
          if (*ptr == '"') {
            const char *start = ptr + 1;
            const char *end = strchr(start, '"');
            if (end && (end - start) < 256) {
              size_t len = end - start;
              memcpy(layout->loader.texts[layout->loader.text_count], start, len);
              layout->loader.texts[layout->loader.text_count][len] = '\0';
              layout->loader.text_count++;
              ptr = end + 1;
            } else {
              break;
            }
          } else {
            ptr++;
          }
        }
        MEM_freeN(texts_json);
      }
    }
  }

  /* Read content text if present */
  if (layout->has_content) {
    int content_len = RNA_property_string_length(msg_ptr, g_msg_props.content);
    layout->content_text = static_cast<char *>(MEM_mallocN(content_len + 1, "content_text"));
    RNA_property_string_get(msg_ptr, g_msg_props.content, layout->content_text);
  }

  /* Read ephemeral text if present */
  if (layout->has_ephemeral) {
    int ephemeral_len = RNA_property_string_length(msg_ptr, g_msg_props.ephemeral);
    layout->ephemeral_text = static_cast<char *>(MEM_mallocN(ephemeral_len + 1, "ephemeral_text"));
    RNA_property_string_get(msg_ptr, g_msg_props.ephemeral, layout->ephemeral_text);
  }

  /* Read bubble_id for click dispatch */
  layout->bubble_id[0] = '\0';
  if (g_msg_props.bubble_id) {
    int bid_len = RNA_property_string_length(msg_ptr, g_msg_props.bubble_id);
    if (bid_len > 0 && bid_len < int(sizeof(layout->bubble_id))) {
      RNA_property_string_get(msg_ptr, g_msg_props.bubble_id, layout->bubble_id);
    }
  }

  /* Read action items if present */
  layout->slot_action_count = 0;
  layout->slot_actions_height = 0.0f;
  if (layout->has_actions && g_msg_props.action_items) {
    CollectionPropertyIterator action_iter{};
    RNA_property_collection_begin(msg_ptr, g_msg_props.action_items, &action_iter);

    while (action_iter.valid && layout->slot_action_count < SLOT_MAX_ACTION_ITEMS) {
      PointerRNA action_ptr = action_iter.ptr;
      init_action_item_property_cache(&action_ptr);

      ActionSlotData &action = layout->slot_actions[layout->slot_action_count];
      action.label[0] = '\0';
      action.value[0] = '\0';
      action.style = 1; /* default */
      action.image[0] = '\0';
      action.height = 0.0f;
      action.is_hovered = false;
      memset(&action.bounds, 0, sizeof(action.bounds));

      if (g_action_props.label) {
        RNA_property_string_get(&action_ptr, g_action_props.label, action.label);
      }
      if (g_action_props.value) {
        RNA_property_string_get(&action_ptr, g_action_props.value, action.value);
      }
      if (g_action_props.style) {
        action.style = RNA_property_enum_get(&action_ptr, g_action_props.style);
      }
      if (g_action_props.image) {
        RNA_property_string_get(&action_ptr, g_action_props.image, action.image);
      }

      layout->slot_action_count++;
      RNA_property_collection_next(&action_iter);
    }

    RNA_property_collection_end(&action_iter);
  }

  /* Read todo items if present */
  layout->slot_todo_count = 0;
  layout->slot_todo_height = 0.0f;
  if (layout->has_todo && g_msg_props.todo_items) {
    CollectionPropertyIterator todo_iter{};
    RNA_property_collection_begin(msg_ptr, g_msg_props.todo_items, &todo_iter);

    while (todo_iter.valid && layout->slot_todo_count < SLOT_MAX_TODO_ITEMS) {
      PointerRNA todo_ptr = todo_iter.ptr;
      init_todo_item_property_cache(&todo_ptr);

      TodoItemSlotData &todo = layout->slot_todo_items[layout->slot_todo_count];
      todo.id[0] = '\0';
      todo.text[0] = '\0';
      todo.status = 0; /* pending */
      todo.height = 0.0f;
      todo.is_hovered = false;
      memset(&todo.bounds, 0, sizeof(todo.bounds));

      if (g_todo_props.item_id) {
        /* The Python property declares maxlen=64 to match this buffer, but
         * guard anyway (like bubble_id above) so a mismatched build cannot
         * overflow the fixed-size id and corrupt the adjacent fields. */
        const int id_len = RNA_property_string_length(&todo_ptr, g_todo_props.item_id);
        if (id_len > 0 && id_len < int(sizeof(todo.id))) {
          RNA_property_string_get(&todo_ptr, g_todo_props.item_id, todo.id);
        }
      }
      if (g_todo_props.text) {
        RNA_property_string_get(&todo_ptr, g_todo_props.text, todo.text);
      }
      if (g_todo_props.status) {
        todo.status = RNA_property_enum_get(&todo_ptr, g_todo_props.status);
      }

      layout->slot_todo_count++;
      RNA_property_collection_next(&todo_iter);
    }

    RNA_property_collection_end(&todo_iter);
  }

  /* Read step items if present */
  layout->slot_step_count = 0;
  layout->slot_steps_height = 0.0f;
  layout->steps_collapsed = true;
  layout->steps_summary[0] = '\0';
  memset(&layout->steps_header_bounds, 0, sizeof(layout->steps_header_bounds));
  if (g_msg_props.steps_collapsed) {
    layout->steps_collapsed =
        RNA_property_boolean_get(msg_ptr, g_msg_props.steps_collapsed);
  }
  read_rna_string_bounded(msg_ptr, g_msg_props.steps_summary, layout->steps_summary,
                          sizeof(layout->steps_summary));
  if (layout->has_steps && g_msg_props.step_items) {
    CollectionPropertyIterator step_iter{};
    RNA_property_collection_begin(msg_ptr, g_msg_props.step_items, &step_iter);

    while (step_iter.valid && layout->slot_step_count < SLOT_MAX_STEP_ITEMS) {
      PointerRNA step_ptr = step_iter.ptr;
      init_step_item_property_cache(&step_ptr);

      StepItemSlotData &step = layout->slot_steps[layout->slot_step_count];
      step.id[0] = '\0';
      step.kind = 4; /* tool */
      step.label[0] = '\0';
      step.target[0] = '\0';
      step.detail[0] = '\0';
      step.status = 2; /* done */
      step.expanded = false;
      step.row_height = 0.0f;
      step.is_hovered = false;
      memset(&step.row_bounds, 0, sizeof(step.row_bounds));

      read_rna_string_bounded(&step_ptr, g_step_props.item_id, step.id, sizeof(step.id));
      if (g_step_props.kind) {
        step.kind = RNA_property_enum_get(&step_ptr, g_step_props.kind);
      }
      read_rna_string_bounded(&step_ptr, g_step_props.label, step.label, sizeof(step.label));
      read_rna_string_bounded(&step_ptr, g_step_props.target, step.target, sizeof(step.target));
      read_rna_string_bounded(&step_ptr, g_step_props.detail, step.detail, sizeof(step.detail));
      if (g_step_props.status) {
        step.status = RNA_property_enum_get(&step_ptr, g_step_props.status);
      }
      if (g_step_props.expanded) {
        step.expanded = RNA_property_boolean_get(&step_ptr, g_step_props.expanded);
      }

      layout->slot_step_count++;
      RNA_property_collection_next(&step_iter);
    }

    RNA_property_collection_end(&step_iter);
  }

  /* Read finalized thinking fields */
  layout->thinking_text[0] = '\0';
  layout->thinking_collapsed = true;
  layout->thinking_duration_ms = 0;
  layout->thinking_height = 0.0f;
  memset(&layout->thinking_header_bounds, 0, sizeof(layout->thinking_header_bounds));
  if (layout->has_thinking) {
    if (g_msg_props.thinking_text) {
      /* thinking_text is a fixed 4096 buffer but the RNA string may be longer
       * (Python maxlen 65536). RNA_property_string_get_alloc uses our fixed
       * buffer when it fits, else heap-allocs; truncate-copy and free in that
       * case so we never write past thinking_text[4096]. */
      char *tbuf = RNA_property_string_get_alloc(
          msg_ptr, g_msg_props.thinking_text, layout->thinking_text,
          sizeof(layout->thinking_text), nullptr);
      if (tbuf != layout->thinking_text) {
        BLI_strncpy(layout->thinking_text, tbuf, sizeof(layout->thinking_text));
        MEM_freeN(tbuf);
      }
    }
    if (g_msg_props.thinking_collapsed) {
      layout->thinking_collapsed =
          RNA_property_boolean_get(msg_ptr, g_msg_props.thinking_collapsed);
    }
    if (g_msg_props.thinking_duration_ms) {
      layout->thinking_duration_ms =
          RNA_property_int_get(msg_ptr, g_msg_props.thinking_duration_ms);
    }
  }

  /* Read image items if present */
  layout->slot_image_count = 0;
  layout->slot_images_height = 0.0f;
  if (layout->has_images && g_msg_props.image_items) {
    CollectionPropertyIterator image_iter{};
    RNA_property_collection_begin(msg_ptr, g_msg_props.image_items, &image_iter);

    while (image_iter.valid && layout->slot_image_count < SLOT_MAX_IMAGE_ITEMS) {
      PointerRNA image_ptr = image_iter.ptr;
      init_image_item_property_cache(&image_ptr);

      ImageSlotData &img = layout->slot_images[layout->slot_image_count];
      img.url[0] = '\0';
      img.alt[0] = '\0';
      img.caption[0] = '\0';
      img.thumbnail_url[0] = '\0';
      img.local_path[0] = '\0';
      img.width = 0.0f;
      img.height = 0.0f;
      img.is_hovered = false;
      memset(&img.bounds, 0, sizeof(img.bounds));

      if (g_image_props.url) {
        RNA_property_string_get(&image_ptr, g_image_props.url, img.url);
      }
      if (g_image_props.alt) {
        RNA_property_string_get(&image_ptr, g_image_props.alt, img.alt);
      }
      if (g_image_props.caption) {
        RNA_property_string_get(&image_ptr, g_image_props.caption, img.caption);
      }
      if (g_image_props.thumbnail_url) {
        RNA_property_string_get(&image_ptr, g_image_props.thumbnail_url, img.thumbnail_url);
      }
      if (g_image_props.local_path) {
        RNA_property_string_get(&image_ptr, g_image_props.local_path, img.local_path);
      }
      if (g_image_props.width) {
        img.width = RNA_property_float_get(&image_ptr, g_image_props.width);
      }
      if (g_image_props.height) {
        img.height = RNA_property_float_get(&image_ptr, g_image_props.height);
      }

      if (img.height > 0.0f) {
        layout->slot_images_height += img.height;
      }

      layout->slot_image_count++;
      RNA_property_collection_next(&image_iter);
    }

    RNA_property_collection_end(&image_iter);
  }

  /* Read feedback state */
  layout->has_feedback = g_msg_props.feedback_visible &&
                         RNA_property_boolean_get(msg_ptr, g_msg_props.feedback_visible);
  layout->feedback_rating = (layout->has_feedback && g_msg_props.feedback_rating) ?
      RNA_property_int_get(msg_ptr, g_msg_props.feedback_rating) : 0;
  layout->feedback_row_height = 0.0f;
  layout->feedback_comment_hovered = false;
  layout->feedback_comment_expanded =
      (layout->has_feedback && g_msg_props.feedback_comment_expanded) ?
      RNA_property_boolean_get(msg_ptr, g_msg_props.feedback_comment_expanded) : false;
  layout->feedback_comment_input_height = 0.0f;
  layout->feedback_status =
      (layout->has_feedback && g_msg_props.feedback_status) ?
      RNA_property_int_get(msg_ptr, g_msg_props.feedback_status) : FEEDBACK_STATUS_IDLE;
  layout->feedback_submitted_comment[0] = '\0';
  if (layout->has_feedback) {
    read_rna_string_bounded(msg_ptr,
                            g_msg_props.feedback_submitted_comment,
                            layout->feedback_submitted_comment,
                            sizeof(layout->feedback_submitted_comment));
  }
  layout->feedback_submitted_comment_height = 0.0f;
  for (int i = 0; i < FEEDBACK_STAR_COUNT; i++) {
    layout->feedback_stars[i].star_index = i + 1;
    layout->feedback_stars[i].is_hovered = false;
    memset(&layout->feedback_stars[i].bounds, 0, sizeof(rctf));
  }
  memset(&layout->feedback_comment_bounds, 0, sizeof(rctf));

  return true;
}

/** \} */
