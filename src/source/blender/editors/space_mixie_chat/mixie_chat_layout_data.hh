/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Data types for message layout, property caching, and per-instance runtime state.
 * Split from mixie_chat_intern.hh for modularity.
 */

#pragma once

#include "BLI_rect.h"
#include "BLI_vector.hh"

#include "mixie_chat_ui_types.hh"

struct PointerRNA;
struct PropertyRNA;
struct SpaceMixieChat;

/* -------------------------------------------------------------------- */
/** \name Property Cache (mixie_chat_props.cc)
 * \{ */

struct ChatMessageProps {
  /* Legacy properties */
  PropertyRNA *sender;
  PropertyRNA *text;
  PropertyRNA *attachments;
  PropertyRNA *message_type;
  PropertyRNA *metadata;

  /* Slot-based properties */
  PropertyRNA *bubble_id;
  PropertyRNA *loader_visible;
  PropertyRNA *loader_texts;
  PropertyRNA *loader_rotate_ms;
  PropertyRNA *loader_current_index;
  PropertyRNA *loader_spinner_index;
  PropertyRNA *content;
  PropertyRNA *ephemeral;
  PropertyRNA *todo_items;
  PropertyRNA *action_items;
  PropertyRNA *image_items;

  /* Feedback properties */
  PropertyRNA *feedback_visible;
  PropertyRNA *feedback_rating;
  PropertyRNA *feedback_comment_expanded;
  PropertyRNA *feedback_status;
  PropertyRNA *feedback_submitted_comment;
  PropertyRNA *feedback_comment;

  /* Steps slot */
  PropertyRNA *step_items;
  PropertyRNA *steps_summary;
  PropertyRNA *steps_collapsed;

  /* Thinking dropdown (finalized) */
  PropertyRNA *thinking_text;
  PropertyRNA *thinking_active;
  PropertyRNA *thinking_duration_ms;
  PropertyRNA *thinking_collapsed;

  bool initialized;
};

struct ChatAttachmentProps {
  PropertyRNA *image_path;
  PropertyRNA *image_source;
  PropertyRNA *display_name;
  bool initialized;
};

/* Slot collection item properties */
struct ChatTodoItemProps {
  PropertyRNA *item_id;
  PropertyRNA *text;
  PropertyRNA *status;
  bool initialized;
};

struct ChatActionItemProps {
  PropertyRNA *label;
  PropertyRNA *value;
  PropertyRNA *style;
  bool initialized;
};

struct ChatImageItemProps {
  PropertyRNA *url;
  PropertyRNA *alt;
  PropertyRNA *caption;
  PropertyRNA *thumbnail_url;
  PropertyRNA *local_path;
  PropertyRNA *width;
  PropertyRNA *height;
  bool initialized;
};

struct ChatStepItemProps {
  PropertyRNA *item_id;
  PropertyRNA *kind;
  PropertyRNA *label;
  PropertyRNA *target;
  PropertyRNA *detail;
  PropertyRNA *status;
  PropertyRNA *expanded;
  bool initialized;
};

extern ChatMessageProps g_msg_props;
extern ChatAttachmentProps g_att_props;
extern ChatTodoItemProps g_todo_props;
extern ChatActionItemProps g_action_props;
extern ChatImageItemProps g_image_props;
extern ChatStepItemProps g_step_props;

void init_message_property_cache(PointerRNA *msg_ptr);
void init_todo_item_property_cache(PointerRNA *item_ptr);
void init_action_item_property_cache(PointerRNA *item_ptr);
void init_image_item_property_cache(PointerRNA *item_ptr);
void init_attachment_property_cache(PointerRNA *att_ptr);
void init_step_item_property_cache(PointerRNA *item_ptr);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Slot Data Population (mixie_chat_slots.cc)
 * \{ */

struct MessageLayoutData;

/**
 * Populate slot presence flags and data for a slot-based message.
 * Returns true if the message is slot-based, false otherwise.
 */
bool populate_slot_layout_data(PointerRNA *msg_ptr, MessageLayoutData *layout);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Performance: Layout Cache
 * \{ */

/**
 * Cached layout data for a single attachment.
 * Stores path, dimensions, and loaded image to avoid redundant image loading.
 */
struct AttachmentLayout {
  char path[1024];  /* Image path */
  int source;       /* Image source type */
  float height;     /* Calculated height for this attachment */
};

/**
 * Cached layout data for a single message.
 * Stores all calculated dimensions to avoid redundant calculations.
 *
 * Supports both legacy message_type rendering and slot-based rendering.
 * When slot fields are populated (has_* flags), they take precedence.
 */
struct MessageLayoutData {
  float y_pos;
  float bubble_x;
  float bubble_width;
  float bubble_height;
  float content_width;
  float text_height;
  float attachments_height;
  ChatBubbleStyle style;
  int message_index;
  bool is_user;
  bool is_error;  /* True if message_type == ERROR */
  blender::Vector<AttachmentLayout> attachments;  /* Cached attachment data */

  /* Action buttons (Copy/Retry) - shown on hover */
  ChatActionButton action_buttons[3];
  int action_button_count;

  /* Legacy fields (kept for layout cache compatibility, zeroed) */
  OptionBubbleData option_bubbles[CHAT_MAX_OPTION_BUBBLES];
  int option_bubble_count;
  float option_bubbles_total_height;
  bool is_todo_list;
  char *todo_combined_text;
  float todo_combined_text_height;
  bool is_thinking_message;

  /* -------------------------------------------------------------------------
   * Slot-based rendering fields (new architecture)
   * When these are populated, they take precedence over legacy fields.
   * ------------------------------------------------------------------------- */

  /* Slot presence flags - determined by checking RNA property values */
  bool has_loader;     /* loader_visible is true */
  bool has_content;    /* content property has text */
  bool has_ephemeral;  /* ephemeral property has text */
  bool has_todo;       /* todo_items collection has items */
  bool has_actions;    /* action_items collection has items */
  bool has_images;     /* image_items collection has items */
  bool is_slot_based;  /* True if bubble_id is set (slot-based message) */

  /* Loader slot data */
  LoaderSlotData loader;

  /* Cached text for clipboard copy (allocated, freed by clear_layout_cache) */
  char *copy_text;

  /* Content slot (allocated, caller frees) */
  char *content_text;
  float content_text_height;

  /* Ephemeral slot (allocated, caller frees, FIFO limited) */
  char *ephemeral_text;
  float ephemeral_height;

  /* Todo items from slot (slot-based alternative to option_bubbles) */
  TodoItemSlotData slot_todo_items[SLOT_MAX_TODO_ITEMS];
  int slot_todo_count;
  float slot_todo_height;

  /* Bubble ID for slot action click dispatch */
  char bubble_id[128];

  /* Action items from slot */
  ActionSlotData slot_actions[SLOT_MAX_ACTION_ITEMS];
  int slot_action_count;
  float slot_actions_height;

  /* Image items from slot */
  ImageSlotData slot_images[SLOT_MAX_IMAGE_ITEMS];
  int slot_image_count;
  float slot_images_height;

  /* Feedback row (post-response rating) */
  bool has_feedback;       /* feedback_visible is true */
  int feedback_rating;     /* 0=unrated, 1-5 */
  float feedback_row_height;
  FeedbackStarData feedback_stars[FEEDBACK_STAR_COUNT];
  rctf feedback_comment_bounds;
  bool feedback_comment_hovered;
  bool feedback_comment_expanded;  /* inline comment field visible */
  float feedback_comment_input_height;  /* extra height for input row */
  int feedback_status; /* 0=idle, 1=sending, 2=received, 3=failed */
  char feedback_submitted_comment[FEEDBACK_COMMENT_DISPLAY_MAX]; /* accepted comment */
  float feedback_submitted_comment_height; /* wrapped read-only comment block */

  /* Steps block slot */
  bool has_steps;
  StepItemSlotData slot_steps[SLOT_MAX_STEP_ITEMS];
  int slot_step_count;
  float slot_steps_height;
  bool steps_collapsed;
  char steps_summary[256];
  rctf steps_header_bounds;  /* block header hit area */

  /* Thinking block. When thinking_active, it renders as a LIVE pinned panel
   * (spinner + streaming FIFO text); when finalized it collapses to the
   * "Thought for Ns" dropdown. */
  bool has_thinking;
  bool thinking_active;
  char thinking_text[4096];  /* fixed buffer; long reasoning is truncated */
  bool thinking_collapsed;
  int thinking_duration_ms;
  float thinking_height;
  rctf thinking_header_bounds;  /* dropdown header hit area */
};

/* Get the layout cache for button hit testing (from SpaceMixieChat runtime) */
const blender::Vector<MessageLayoutData> &mixie_chat_get_layout_cache(
    struct SpaceMixieChat *smixie);

/**
 * Clear layout cache and free memory for a specific space instance.
 * Call when space is destroyed to prevent leaks.
 */
void mixie_chat_clear_layout_cache(struct SpaceMixieChat *smixie);

/**
 * Reset property caches to prevent stale pointers.
 * Call when space is destroyed.
 */
void mixie_chat_clear_property_caches();

/** \} */

/* -------------------------------------------------------------------- */
/** \name Empty Chat Prompt Bubbles
 * \{ */

#define CHAT_EMPTY_PROMPT_COUNT 4

/**
 * Structure to store empty state prompt bubble data.
 * Used for hit testing and hover state tracking.
 */
struct EmptyPromptBubble {
  const char *text;
  rctf bounds;
  bool is_hovered;
};

/**
 * Chat modes for each empty prompt (ASK, GENERATE, AGENT).
 * Used to automatically switch chat mode when a prompt is clicked.
 */
extern const char *g_empty_prompt_modes[CHAT_EMPTY_PROMPT_COUNT];

/**
 * Generate sub-types for each empty prompt (IMAGE_GEN, IMAGE_TO_3D, etc.).
 * Only applies when mode is GENERATE. Empty string means no generate type.
 */
extern const char *g_empty_prompt_generate_types[CHAT_EMPTY_PROMPT_COUNT];

/** \} */

/* -------------------------------------------------------------------- */
/** \name Per-Instance Runtime State
 * \{ */

/**
 * Per-instance runtime data for MixieChat space.
 * Stored in SpaceMixieChat->runtime, NOT saved to files.
 * Each chat panel gets its own independent copy.
 */
struct MixieChatRuntime {
  /** Cached message layout data for hit testing and drawing. */
  blender::Vector<MessageLayoutData> layout_cache;

  /** Previous content height for auto-scroll detection. */
  float prev_total_height;

  /** Previous window Y size for resize detection. */
  int prev_winy;

  /** Layout cache invalidation: previous message count. */
  int prev_msg_count = 0;

  /** Layout cache invalidation: previous region width. */
  int prev_winx = 0;

  /** Layout cache invalidation: previous scene layout epoch. */
  int prev_layout_epoch = -1;

  /** Layout cache invalidation: whether streaming was active last frame. */
  bool prev_had_active_stream = false;

  /** Cached total height from last layout rebuild. */
  float cached_total_height = 0.0f;

  /** Empty state prompt bubbles (hover/bounds per instance). */
  EmptyPromptBubble empty_prompts[CHAT_EMPTY_PROMPT_COUNT];

  /** Whether empty prompts are currently visible for this instance. */
  bool empty_prompts_visible;

  /** Empty state entrance animation: start timestamp (0 = not started). */
  double empty_anim_start = 0.0;

  /** Whether to restart animation next time empty state appears. */
  bool empty_anim_reset = true;

  /** Message slide-in animation: timestamp when newest message appeared. */
  double slide_anim_start = 0.0;

  /** Message slide-in: index of the message being animated (-1 = none). */
  int slide_anim_msg_index = -1;

  /** Copy feedback: message index that was last copied (-1 = none). */
  int copy_feedback_msg_index = -1;

  /** Copy feedback: timestamp when copy was triggered. */
  double copy_feedback_time = 0.0;

  /** Scroll-to-bottom indicator: bounds in screen-space for click testing. */
  rctf scroll_indicator_bounds = {0, 0, 0, 0};

  /** Scroll-to-bottom indicator: whether it's currently visible. */
  bool scroll_indicator_visible = false;

  /** Scroll-to-bottom indicator: fade animation start time. */
  double scroll_indicator_fade_start = 0.0;

  /** Scroll-to-bottom indicator: whether fading in (true) or out (false). */
  bool scroll_indicator_fading_in = false;

  /** Scroll-to-bottom indicator: bounce animation start time (new msg while scrolled up). */
  double scroll_indicator_bounce_start = 0.0;
};

/**
 * Get or create runtime for a SpaceMixieChat instance.
 * Allocates MixieChatRuntime on first call.
 */
MixieChatRuntime *mixie_chat_ensure_runtime(struct SpaceMixieChat *smixie);

/**
 * Free runtime data for a SpaceMixieChat instance.
 */
void mixie_chat_free_runtime(struct SpaceMixieChat *smixie);

/** \} */
