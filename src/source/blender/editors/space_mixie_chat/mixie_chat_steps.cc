/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Agent steps block: a collapsible card summarizing tool-call activity.
 * Collapsed -> chevron + summary header. Expanded -> one row per tool call
 * (kind icon + label + target), each row optionally expanding to a detail body.
 *
 * Height calculation and drawing share the same text builders and wrap
 * widths (see steps_row_text) — any divergence between the two passes shows
 * up as overlapping or clipped rows.
 *
 * Visual language (production agent style):
 * - Disclosure chevrons are tinted mono icons (ICON_TRIA_*), not font glyphs,
 *   so they stay crisp and optically centered at any UI scale.
 * - The header reads as secondary UI (slightly muted), rows as primary.
 * - Expandable rows carry a trailing disclosure chevron at the card's right
 *   edge so row text stays left-aligned regardless of expandability.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_sys_types.h"

#include "BLF_api.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_icons.hh"
#include "UI_resources.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_layout_data.hh"
#include "mixie_chat_ui_types.hh"

/* Vertical gap between consecutive rows. */
#define STEPS_ROW_GAP 6.0f
/* Vertical gap between the header and the first row (slightly larger so the
 * summary reads as a heading for the row list). */
#define STEPS_HEADER_GAP 8.0f
/* Vertical gap between a row and its expanded detail body. */
#define STEPS_DETAIL_GAP 4.0f
/* Drawn kind-icon size in px (pre-UI-scale). */
#define STEPS_ICON_SIZE 14.0f
/* Horizontal gap between the kind icon and the row text. */
#define STEPS_ICON_GAP 6.0f
/* Disclosure chevron size + gap (pre-UI-scale), shared with thinking. */
#define CHAT_CHEVRON_SIZE 12.0f
#define CHAT_CHEVRON_GAP 6.0f

/* -------------------------------------------------------------------- */
/** \name Shared chevron (also used by the thinking dropdown)
 * \{ */

float chat_ui_chevron_indent()
{
  return (CHAT_CHEVRON_SIZE + CHAT_CHEVRON_GAP) * UI_SCALE_FAC;
}

float chat_ui_wrapped_first_line_center(int font_size,
                                        const char *text,
                                        float wrap_width,
                                        float rect_ymin)
{
  const int font_id = BLF_default();
  BLF_size(font_id, font_size);
  rcti cap_bb;
  BLF_boundbox(font_id, "M", 1, &cap_bb);
  BLF_enable(font_id, BLF_WORD_WRAP);
  BLF_wordwrap(font_id, int(wrap_width));
  rcti text_bb;
  BLF_boundbox(font_id, text, strlen(text), &text_bb);
  BLF_disable(font_id, BLF_WORD_WRAP);
  const float first_baseline = rect_ymin - float(text_bb.ymin);
  return first_baseline + float(BLI_rcti_size_y(&cap_bb)) * 0.5f;
}

void chat_ui_draw_chevron(float x, float center_y, bool collapsed, const float color[4])
{
  const float icon_px = CHAT_CHEVRON_SIZE * UI_SCALE_FAC;
  const float icon_y = center_y - icon_px * 0.5f;
  const uchar mono[4] = {uchar(color[0] * 255.0f),
                         uchar(color[1] * 255.0f),
                         uchar(color[2] * 255.0f),
                         uchar(color[3] * 255.0f)};
  GPU_blend(GPU_BLEND_ALPHA);
  UI_icon_draw_ex(x,
                  icon_y,
                  collapsed ? ICON_TRIA_RIGHT : ICON_TRIA_DOWN,
                  16.0f / icon_px,
                  1.0f,
                  0.0f,
                  mono,
                  false,
                  UI_NO_ICON_OVERLAY_TEXT);
  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

/* Munari primitives as the kind system — two shapes, not five toolbox icons:
 * the agent either OBSERVED the scene or ACTED on it. */
static const char *step_kind_glyph(int kind)
{
  switch (kind) {
    case 0:            /* read */
    case 3:            /* search */
      return "\xE2\x97\x8B"; /* ○ observe */
    default:           /* write / command / tool */
      return "\xE2\x96\xA0"; /* ■ act */
  }
}

/* Row text: label + optional target. Shared by calc + draw. */
static void steps_row_text(const StepItemSlotData &step, char *buf, size_t buf_len)
{
  if (step.target[0] != '\0') {
    BLI_snprintf(buf, buf_len, "%s  %s", step.label, step.target);
  }
  else {
    BLI_strncpy(buf, step.label, buf_len);
  }
}

/* Indent from the content-area left edge to the row text (kind icon + gap). */
static float steps_text_indent()
{
  return (STEPS_ICON_SIZE + STEPS_ICON_GAP) * UI_SCALE_FAC;
}

/* Wrap width for one row's text. Every tool row is independently expandable
 * (its detail holds the created/modified object names), so each reserves space
 * for the trailing disclosure chevron. MUST match between calc + draw. */
static float steps_row_text_width(const StepItemSlotData &step, float content_width)
{
  float width = content_width - steps_text_indent();
  if (step.detail[0] != '\0') {
    width -= chat_ui_chevron_indent();
  }
  return width;
}

/* -------------------------------------------------------------------- */
/** \name Height calculation
 * \{ */

float chat_ui_calc_steps_block_height(const ChatBubbleStyle *style,
                                      const MessageLayoutData *layout,
                                      float content_width)
{
  const int font_id = BLF_default();
  BLF_size(font_id, style->font_size);
  const float line_height = float(BLF_height_max(font_id));

  /* Header: chevron + summary (wrapped, min one line) + vertical padding. */
  const char *summary = layout->steps_summary[0] ? layout->steps_summary : "Steps";
  float hw, hh;
  chat_ui_calc_text_bounds(summary,
                           content_width - chat_ui_chevron_indent(),
                           style->font_size, 0, &hw, &hh);
  float height = std::max(hh, line_height) + style->v_padding * 2.0f;

  if (layout->steps_collapsed) {
    return height;
  }

  /* Expanded: rows wrap to the icon-indented width; an expanded row adds its
   * detail (object names) height. Widths MUST match chat_ui_draw_steps_block. */
  const float detail_width = content_width - steps_text_indent();
  for (int i = 0; i < layout->slot_step_count; i++) {
    const StepItemSlotData &step = layout->slot_steps[i];
    char row_text[576];
    steps_row_text(step, row_text, sizeof(row_text));
    float rw, rh;
    chat_ui_calc_text_bounds(row_text, steps_row_text_width(step, content_width),
                             style->font_size, 0, &rw, &rh);
    const float gap = (i == 0 ? STEPS_HEADER_GAP : STEPS_ROW_GAP) * UI_SCALE_FAC;
    height += gap + std::max(rh, line_height);

    if (step.expanded && step.detail[0] != '\0') {
      float dw, dh;
      chat_ui_calc_text_bounds(step.detail, detail_width, style->font_size, 0, &dw, &dh);
      height += STEPS_DETAIL_GAP * UI_SCALE_FAC + dh;
    }
  }
  return height;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing
 * \{ */

void chat_ui_draw_steps_block(const ChatBubbleStyle *style,
                              MessageLayoutData *layout,
                              float x,
                              float y,
                              float bubble_width,
                              float content_width)
{
  /* Flat block: no filled card — the tools section reads as flat agent content
   * (only user messages are pills). A hairline divider at the top separates it
   * from the prose above without a heavy box. */
  ChatBubbleStyle card = *style;

  rctf card_rect;
  card_rect.xmin = x;
  card_rect.xmax = x + bubble_width;
  card_rect.ymin = y;
  card_rect.ymax = y + layout->slot_steps_height;

  /* Neutral structural rail — the steps list is settled process record; only
   * a RUNNING row's glyph carries the live accent. */
  const float tools_accent[4] = CHAT_ACCENT_TOOLS;
  chat_ui_draw_accent_bar(x, card_rect.ymin, layout->slot_steps_height,
                          tools_accent, UI_SCALE_FAC);

  const int font_id = BLF_default();
  BLF_size(font_id, card.font_size);
  const float line_height = float(BLF_height_max(font_id));
  const float chevron_indent = chat_ui_chevron_indent();

  /* --- Header: chevron icon + summary, muted (secondary UI, not content) --- */
  const float header_col[4] = {card.text_color[0], card.text_color[1],
                               card.text_color[2], card.text_color[3] * 0.65f};
  const char *summary = layout->steps_summary[0] ? layout->steps_summary : "Steps";
  float hw, hh;
  chat_ui_calc_text_bounds(summary, content_width - chevron_indent,
                           card.font_size, 0, &hw, &hh);
  hh = std::max(hh, line_height);

  const float header_top = card_rect.ymax - card.v_padding;
  const float header_bottom = header_top - hh;

  /* Anchor the chevron to the summary text's first-line visual center (the
   * text draw bottom-aligns its ink box, so the line-box center reads high). */
  const float header_center = chat_ui_wrapped_first_line_center(
      card.font_size, summary, content_width - chevron_indent, header_bottom);
  chat_ui_draw_chevron(x + card.h_padding, header_center, layout->steps_collapsed, header_col);

  rctf header_rect;
  header_rect.xmin = x + card.h_padding + chevron_indent;
  header_rect.xmax = x + card.h_padding + content_width;
  header_rect.ymin = header_bottom;
  header_rect.ymax = header_top;
  chat_ui_draw_text_wrapped(summary, &header_rect, card.font_size, 0, header_col);

  /* Record header hit-bounds: full card width, including the card's vertical
   * padding (the whole collapsed card is one click target). */
  layout->steps_header_bounds.xmin = x;
  layout->steps_header_bounds.xmax = x + bubble_width;
  layout->steps_header_bounds.ymin = layout->steps_collapsed ? card_rect.ymin : header_bottom;
  layout->steps_header_bounds.ymax = card_rect.ymax;

  if (layout->steps_collapsed) {
    return;
  }

  /* --- Expanded rows --- */
  const float text_indent = steps_text_indent();
  const float detail_width = content_width - text_indent;
  float cursor = header_bottom;

  for (int i = 0; i < layout->slot_step_count; i++) {
    StepItemSlotData &step = layout->slot_steps[i];

    char row_text[576];
    steps_row_text(step, row_text, sizeof(row_text));
    float rw, rh;
    chat_ui_calc_text_bounds(row_text, steps_row_text_width(step, content_width),
                             card.font_size, 0, &rw, &rh);
    rh = std::max(rh, line_height);

    const float gap = (i == 0 ? STEPS_HEADER_GAP : STEPS_ROW_GAP) * UI_SCALE_FAC;
    const float row_top = cursor - gap;
    const float row_bottom = row_top - rh;

    /* Subtle hover highlight behind the row (cursor loop sets is_hovered). */
    if (step.is_hovered) {
      float hover_col[4];
      chat_ui_get_button_hover_color(hover_col);
      rctf hover_rect;
      hover_rect.xmin = x + 4.0f * UI_SCALE_FAC;
      hover_rect.xmax = x + bubble_width - 4.0f * UI_SCALE_FAC;
      hover_rect.ymin = row_bottom - 2.0f * UI_SCALE_FAC;
      hover_rect.ymax = row_top + 2.0f * UI_SCALE_FAC;
      chat_ui_draw_rounded_rect(&hover_rect, 4.0f * UI_SCALE_FAC, hover_col);
    }

    /* Kind glyph on the row's first text line. State is the ONLY use of
     * color here: running = the single live accent, failed = a muted ✕,
     * settled = quiet gray — a finished list reads uniformly calm. */
    float glyph_col[4] = {card.text_color[0], card.text_color[1],
                          card.text_color[2], card.text_color[3] * 0.55f};
    const char *glyph = step_kind_glyph(step.kind);
    if (step.status == 1) { /* running */
      const float live[4] = CHAT_ACCENT_LIVE;
      glyph_col[0] = live[0];
      glyph_col[1] = live[1];
      glyph_col[2] = live[2];
      glyph_col[3] = live[3];
    }
    else if (step.status == 3) { /* failed */
      glyph = "\xE2\x9C\x95"; /* ✕ */
      glyph_col[0] = 0.85f;
      glyph_col[1] = 0.40f;
      glyph_col[2] = 0.35f;
      glyph_col[3] = 1.0f;
    }
    /* Deterministic optical placement, anchored to the TEXT, not the line
     * box (see chat_ui_wrapped_first_line_center): centering on the
     * geometric line center reads high and jitters row to row with
     * descender depth. Center the glyph's own ink box on the text's
     * first-line visual center — every shape (○ ■ ✕) lands identically.
     * Glyph slightly under text size so the marks read as marks. */
    const float glyph_center_y = chat_ui_wrapped_first_line_center(
        card.font_size, row_text, steps_row_text_width(step, content_width), row_bottom);

    const float glyph_size = card.font_size * 0.9f;
    BLF_size(font_id, glyph_size);
    rcti gb;
    BLF_boundbox(font_id, glyph, strlen(glyph), &gb);
    const float cell_w = STEPS_ICON_SIZE * UI_SCALE_FAC;
    const float gx = x + card.h_padding +
                     (cell_w - float(BLI_rcti_size_x(&gb))) * 0.5f - float(gb.xmin);
    const float gy = glyph_center_y - float(BLI_rcti_size_y(&gb)) * 0.5f - float(gb.ymin);
    BLF_color4fv(font_id, glyph_col);
    BLF_position(font_id, gx, gy, 0.0f);
    BLF_draw(font_id, glyph, strlen(glyph));
    BLF_size(font_id, card.font_size); /* restore for the row text below */

    rctf row_rect;
    row_rect.xmin = x + card.h_padding + text_indent;
    row_rect.xmax = row_rect.xmin + steps_row_text_width(step, content_width);
    row_rect.ymin = row_bottom;
    row_rect.ymax = row_top;
    chat_ui_draw_text_wrapped(row_text, &row_rect, card.font_size, 0, card.text_color);

    /* Trailing disclosure chevron — every row with detail (object names) is
     * independently expandable, pinned to the content's right edge and on
     * the same text-anchored center as the kind glyph. */
    if (step.detail[0] != '\0') {
      const float dim_chev[4] = {card.text_color[0], card.text_color[1],
                                 card.text_color[2], card.text_color[3] * 0.6f};
      const float chev_x = x + card.h_padding + content_width -
                           CHAT_CHEVRON_SIZE * UI_SCALE_FAC;
      chat_ui_draw_chevron(chev_x, glyph_center_y, !step.expanded, dim_chev);
    }

    /* Record per-row hit bounds (full card width, full wrapped height). */
    step.row_height = rh;
    step.row_bounds.xmin = x;
    step.row_bounds.xmax = x + bubble_width;
    step.row_bounds.ymin = row_bottom;
    step.row_bounds.ymax = row_top;

    cursor = row_bottom;

    /* Detail body (the object names, dimmed + indented) when this row is open. */
    if (step.expanded && step.detail[0] != '\0') {
      float dw, dh;
      chat_ui_calc_text_bounds(step.detail, detail_width, card.font_size, 0, &dw, &dh);
      const float detail_top = cursor - STEPS_DETAIL_GAP * UI_SCALE_FAC;
      const float detail_bottom = detail_top - dh;

      float dim[4] = {card.text_color[0], card.text_color[1],
                      card.text_color[2], card.text_color[3] * 0.6f};
      rctf detail_rect;
      detail_rect.xmin = x + card.h_padding + text_indent;
      detail_rect.xmax = detail_rect.xmin + detail_width;
      detail_rect.ymin = detail_bottom;
      detail_rect.ymax = detail_top;
      chat_ui_draw_text_wrapped(step.detail, &detail_rect, card.font_size, 0, dim);

      cursor = detail_bottom;
    }
  }
}

/** \} */
