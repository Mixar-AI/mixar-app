/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Type definitions for the modular chat UI system.
 * Provides reusable structures for bubbles, buttons, images, and layout metrics.
 */

#pragma once

#include "BLI_rect.h"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name UI Element Types
 * \{ */

enum ChatUIElementType {
  CHAT_UI_BUBBLE,
  CHAT_UI_BUTTON,
  CHAT_UI_IMAGE,
  CHAT_UI_LABEL,
  CHAT_UI_DIVIDER,
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Action Button Types
 * \{ */

enum ChatActionType {
  CHAT_ACTION_NONE = -1,
  CHAT_ACTION_COPY = 0,    /* Copy message text to clipboard */
  CHAT_ACTION_RETRY = 1,   /* Retry failed message */
  CHAT_ACTION_EXPAND = 2,  /* Expand/collapse long messages */
  CHAT_ACTION_PROMPT_OPTION_BASE = 100,  /* Base for prompt options (101-109) */
  CHAT_ACTION_PROMPT_TEXT_INPUT = 200,   /* Custom text input option */
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Style Structures
 * \{ */

/**
 * Chat bubble appearance configuration.
 * Defines colors, padding, and alignment for message bubbles.
 */
struct ChatBubbleStyle {
  float corner_radius;
  float h_padding;       /* Horizontal padding inside bubble */
  float v_padding;       /* Vertical padding inside bubble */
  float bg_color[4];     /* Background color RGBA */
  float hover_color[4];  /* Hover background color RGBA (for clickable bubbles) */
  float text_color[4];   /* Text color RGBA */
  int font_size;         /* Base font size (scaled by UI_SCALE_FAC) */
  bool is_right_aligned; /* User messages align right, agent messages align left */
};



/**
 * Image display configuration.
 * Defines maximum dimensions and margins for images in bubbles.
 */
struct ChatImageStyle {
  float max_width;
  float max_height;
  float margin;
  float corner_radius;
};

/**
 * Button appearance configuration.
 * Used for action buttons (copy, retry) and interactive elements.
 */
struct ChatButtonStyle {
  float min_width;
  float height;
  float corner_radius;
  float h_padding;
  float bg_color[4];
  float hover_color[4];
  float pressed_color[4];
  float text_color[4];
  int font_size;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name State Structures
 * \{ */

/**
 * Action button state for hit testing and interaction.
 * Stored per-message for mouse event handling.
 */
struct ChatActionButton {
  ChatActionType type;
  rctf bounds;       /* Hit testing bounds in View2D coordinates */
  bool is_hovered;
  bool is_pressed;
};

/**
 * Clickable text line within a message bubble (for prompt options).
 * Stores bounds and state for option lines that can be clicked.
 */
struct ClickableTextLine {
  ChatActionType type;   /* Action when clicked (CHAT_ACTION_PROMPT_OPTION_BASE + N) */
  rctf bounds;           /* Hit testing rectangle in View2D coordinates */
  int option_index;      /* Which option (0-8) */
  bool is_hovered;       /* True when mouse is over this line */
};

/**
 * Option bubble layout for PROMPT and TODO messages.
 * Each option/item gets its own clickable bubble below the question/title bubble.
 * Calculated during Pass 1 and drawn during the draw phase.
 */
struct OptionBubbleData {
  char option_text[256]; /* Cached option/item text from metadata JSON */
  rctf bounds;           /* Bubble bounds in View2D coordinates (set during draw) */
  int option_index;      /* Which option/item (0-8) */
  bool is_hovered;       /* True when mouse is over this bubble */
  float height;          /* Calculated bubble height (text + padding) */
  bool checked;          /* For TODO items: whether the item is checked */
};

/* Maximum action buttons per message */
#define CHAT_MAX_ACTION_BUTTONS 4

/* Maximum option bubbles per prompt */
#define CHAT_MAX_OPTION_BUBBLES 50

/** \} */

/* -------------------------------------------------------------------- */
/** \name Layout Metrics
 * \{ */

/**
 * Layout metrics with DPI scaling applied.
 * All measurements are pre-multiplied by UI_SCALE_FAC.
 */
struct ChatLayoutMetrics {
  float scale_factor;           /* UI_SCALE_FAC */
  float padding;                /* Outer padding around content */
  float bubble_spacing;         /* Vertical space between bubbles */
  float label_height;           /* Height for sender labels */
  float max_bubble_width_ratio; /* Max bubble width as ratio of region width (0.85) */
  float font_size;              /* Scaled font size for message text */
  float label_font_size;        /* Scaled font size for labels */
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Default Styles
 * \{ */

/* Base values before UI_SCALE_FAC is applied */
#define CHAT_BASE_FONT_SIZE 14.0f
#define CHAT_BASE_LABEL_FONT_SIZE 11.0f
#define CHAT_BASE_PADDING 16.0f
#define CHAT_BASE_BUBBLE_SPACING 22.0f
#define CHAT_BASE_BUBBLE_H_PADDING 16.0f
#define CHAT_BASE_BUBBLE_V_PADDING 14.0f
#define CHAT_BASE_CORNER_RADIUS 12.0f
#define CHAT_BASE_LABEL_HEIGHT 24.0f
#define CHAT_BASE_IMAGE_MAX_WIDTH 240.0f
#define CHAT_BASE_IMAGE_MAX_HEIGHT 180.0f
#define CHAT_BASE_IMAGE_MARGIN 8.0f
#define CHAT_BASE_IMAGE_CORNER_RADIUS 12.0f
#define CHAT_MAX_BUBBLE_WIDTH_RATIO 0.75f

/* Default colors */
#define CHAT_USER_BG_COLOR \
  { \
    0.22f, 0.47f, 0.78f, 0.95f \
  }
#define CHAT_AGENT_BG_COLOR \
  { \
    0.25f, 0.25f, 0.25f, 0.95f \
  }
#define CHAT_TEXT_COLOR \
  { \
    1.0f, 1.0f, 1.0f, 1.0f \
  }
#define CHAT_LABEL_COLOR \
  { \
    0.7f, 0.7f, 0.7f, 1.0f \
  }
#define CHAT_ERROR_BG_COLOR \
  { \
    0.55f, 0.15f, 0.15f, 0.95f \
  }
#define CHAT_BUTTON_BG_COLOR \
  { \
    0.3f, 0.3f, 0.3f, 0.8f \
  }
#define CHAT_BUTTON_HOVER_COLOR \
  { \
    0.4f, 0.4f, 0.4f, 0.9f \
  }
#define CHAT_BUTTON_PRESSED_COLOR \
  { \
    0.2f, 0.2f, 0.2f, 1.0f \
  }

/* Munari reduction — ground vs signal, not a hue per block:
 * every settled block shares ONE quiet structural rail (ground); the single
 * accent is reserved for what is alive RIGHT NOW (the streaming/live blocks
 * and the running step), so a turn reads "working" while exactly one green
 * element is on screen and "done" the moment everything is neutral. */
#define CHAT_RAIL_NEUTRAL \
  { \
    0.30f, 0.32f, 0.35f, 0.9f \
  }
#define CHAT_ACCENT_LIVE \
  { \
    0.20f, 0.80f, 0.62f, 1.0f \
  }
/* Block aliases — all settled rails are the neutral ground. */
#define CHAT_ACCENT_PLAN CHAT_RAIL_NEUTRAL
#define CHAT_ACCENT_TOOLS CHAT_RAIL_NEUTRAL
#define CHAT_ACCENT_THINKING CHAT_RAIL_NEUTRAL

/** \} */

/* -------------------------------------------------------------------- */
/** \name Slot-Based Data Structures
 * \{ */

/**
 * Loader slot data for animated loading indicators.
 * Supports rotating text messages with spinner animation.
 */
struct LoaderSlotData {
  bool visible;
  char texts[8][256];  /* Max 8 rotating texts */
  int text_count;
  int rotate_ms;
  int current_text_index;
  int spinner_frame;  /* Animation frame for spinner character */
};

/**
 * Todo item data for step/task lists.
 * Status determines the icon displayed (checkbox states).
 */
struct TodoItemSlotData {
  char id[64];
  char text[512];
  int status;  /* 0=pending, 1=in_progress, 2=done, 3=failed */
  float height;
  rctf bounds;
  bool is_hovered;
};

/**
 * Action button data for user interaction.
 * Style determines the button color scheme.
 */
struct ActionSlotData {
  char label[256];
  char value[256];
  int style;  /* 0=primary, 1=default, 2=danger */
  float height;
  rctf bounds;
  bool is_hovered;
};

/**
 * Image gallery item data.
 * Supports both remote URLs and local file paths.
 */
struct ImageSlotData {
  char url[1024];
  char alt[256];
  char caption[512];
  char thumbnail_url[1024];
  char local_path[1024];
  float width, height;
  rctf bounds;
  bool is_hovered;
};

/**
 * Feedback star hit-test data.
 * One per star in the feedback rating row.
 */
struct FeedbackStarData {
  rctf bounds;
  int star_index; /* 1-5 */
  bool is_hovered;
};

#define FEEDBACK_STAR_COUNT 5

/* Display cap for the read-only accepted-comment copy kept in layout data.
 * The RNA property allows 2000 chars; the inline confirmation truncates. */
#define FEEDBACK_COMMENT_DISPLAY_MAX 512

/* The comment input grows with its wrapped line count (Shift+Enter inserts
 * newlines), capped like the composer (FOOTER_INPUT_MAX_LINE_COUNT). */
#define FEEDBACK_COMMENT_MAX_LINES 6

/* Submission lifecycle for the feedback row. Mirrors the Python constants in
 * space_mixie_chat/constants.py — keep in sync. */
enum FeedbackStatus {
  FEEDBACK_STATUS_IDLE = 0,
  FEEDBACK_STATUS_SENDING = 1,
  FEEDBACK_STATUS_RECEIVED = 2,
  FEEDBACK_STATUS_FAILED = 3,
};

/**
 * Step item data for the agent steps block (tool-call rows).
 * kind selects the row icon; status selects the trailing state glyph.
 */
struct StepItemSlotData {
  char id[64];
  int kind;          /* 0=read 1=write 2=command 3=search 4=tool */
  char label[256];
  char target[256];
  char detail[1024]; /* second-level body, shown when expanded */
  int status;        /* 0=pending 1=running 2=done 3=failed */
  bool expanded;     /* per-row second level open */
  float row_height;  /* header (+ detail when expanded) */
  rctf row_bounds;   /* header hit area (View2D coords) */
  bool is_hovered;
};
/* Maximum items per slot */
#define SLOT_MAX_TODO_ITEMS 50
#define SLOT_MAX_ACTION_ITEMS 10
#define SLOT_MAX_IMAGE_ITEMS 20
#define SLOT_MAX_STEP_ITEMS 50
#define SLOT_MAX_LOADER_TEXTS 8

/** Worst-case combined todo-list text: every item at full `text` length
 * plus status icon (up to 4 UTF-8 bytes), separating space and newline. */
#define SLOT_TODO_COMBINED_MAX (SLOT_MAX_TODO_ITEMS * (512 + 8))

/** \} */

/* -------------------------------------------------------------------- */
/** \name Corner Specification
 * \{ */

/* Bit flags for which corners to round */
#define CHAT_CORNER_NONE 0
#define CHAT_CORNER_TOP_LEFT (1 << 0)
#define CHAT_CORNER_TOP_RIGHT (1 << 1)
#define CHAT_CORNER_BOTTOM_LEFT (1 << 2)
#define CHAT_CORNER_BOTTOM_RIGHT (1 << 3)
#define CHAT_CORNER_ALL \
  (CHAT_CORNER_TOP_LEFT | CHAT_CORNER_TOP_RIGHT | CHAT_CORNER_BOTTOM_LEFT | \
   CHAT_CORNER_BOTTOM_RIGHT)

/** \} */
}  // namespace blender
