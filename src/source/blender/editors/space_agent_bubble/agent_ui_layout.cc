/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Builds the Agent island's geometry from the artboard tokens.
 */

#include "BLI_rect.h"

#include "BKE_screen.hh"

#include "DNA_screen_types.h"

#include "UI_interface.hh"

#include "agent_ui_layout.hh"
#include "agent_ui_theme.hh"

/* -------------------------------------------------------------------- */
/** \name Artboard -> region coordinates
 * \{ */

namespace {

/**
 * The single y-flip.
 *
 * `top` is the region-space y of the island's top edge; artboard y grows
 * downward from there, region y grows upward from the region's bottom.
 */
struct Frame {
  float left;
  float top;
  float u; /* One artboard unit in device pixels. */

  float x(float du) const
  {
    return left + du * u;
  }
  float y(float du) const
  {
    return top - du * u;
  }
  /** Artboard box (x, y, w, h) with y measured downward. */
  rctf box(float bx, float by, float bw, float bh) const
  {
    rctf r;
    r.xmin = x(bx);
    r.xmax = x(bx + bw);
    /* ymin is the LOWER edge, which is the artboard's bottom: by + bh. */
    r.ymin = y(by + bh);
    r.ymax = y(by);
    return r;
  }
  rctf disc(float cx, float cy, float r) const
  {
    return box(cx - r, cy - r, r * 2.0f, r * 2.0f);
  }
};

/** Left x of each tab pill and its width, in artboard units. */
struct TabMetric {
  float x;
  float w;
};

const TabMetric g_tab_metrics[AGENT_TAB_COUNT] = {
    {AGENT_TAB_X_AGENT, AGENT_TAB_W_AGENT},
    {AGENT_TAB_X_3D, AGENT_TAB_W_3D},
    {AGENT_TAB_X_MEDIA, AGENT_TAB_W_MEDIA},
    {AGENT_TAB_X_SPLAT, AGENT_TAB_W_SPLAT},
    {AGENT_TAB_X_GENERATIONS, AGENT_TAB_W_GENERATIONS},
    {AGENT_TAB_X_QUEUE, AGENT_TAB_W_QUEUE},
};

}  // namespace

/** \} */

/* -------------------------------------------------------------------- */
/** \name Build
 * \{ */

void agent_ui_layout_build(const int window_w,
                           const int window_h,
                           AgentTabId active_tab,
                           const bool /*agent_mode_active*/,
                           const bool has_transcript,
                           AgentIslandLayout *r_layout)
{
  *r_layout = {};

  /* Scale is derived from the WINDOW, not from UI_SCALE_FAC.
   *
   * The window is sized to the island by construction, so one artboard unit is
   * simply its width over the island's. That is self-calibrating and immune to
   * the unit mismatch that broke this before: region winrct is in PHYSICAL
   * pixels (3496 wide) while AGENT_DU() yields Blender-scaled pixels (half
   * that), so a layout built with AGENT_DU produced a field nearly three times
   * its region's height — its text drew far outside the region and vanished.
   * Everything here is drawn and hit-tested in winrct space, so the layout has
   * to be in winrct space too. */
  const float u = float(window_w) / float(AGENT_ISLAND_W);
  const float want_w = AGENT_ISLAND_W * u;
  const float want_h = AGENT_ISLAND_H * u;

  const float region_w = float(window_w);
  const float region_h = float(window_h);

  r_layout->scale = u;

  /* The bubble window is sized to the island, so this only bites during the
   * transient frames of a resize — and while it does, drawing nothing beats
   * drawing a card with its chip row overlapping its own header. */
  /* A pixel of slack. The window is sized from an integer count of unscaled
   * points, so rounding can leave it a fraction under the island's exact
   * scaled height — and an exact comparison then rejects the whole island and
   * paints nothing, which reads as a dead black window. */
  const float slack = 2.0f;
  if (region_w < want_w - slack || region_h < want_h - slack) {
    r_layout->valid = false;
    return;
  }
  r_layout->valid = true;

  /* Anchor top-left, so growing the window past the island leaves the slack
   * at the right and bottom rather than shifting the design off its grid. */
  Frame f;
  f.left = 0.0f;
  /* Artboard y = AGENT_ISLAND_TOP (the tab strip) sits at the window's top
   * edge; the status-pill band above it lives in its own window now. */
  f.top = region_h + AGENT_ISLAND_TOP * u;
  f.u = u;

  r_layout->island = f.box(0, AGENT_ISLAND_TOP, AGENT_ISLAND_W, AGENT_ISLAND_H);

  /* --- Status pill --- */
  r_layout->pill = f.box(AGENT_PILL_X, AGENT_PILL_Y, AGENT_PILL_W, AGENT_PILL_H);
  r_layout->pill_dot = f.disc(AGENT_PILL_DOT_CX, AGENT_PILL_DOT_CY, AGENT_PILL_DOT_R);
  r_layout->pill_label_x = f.x(AGENT_PILL_LABEL_X);

  /* --- Tab strip --- */
  r_layout->strip = f.box(AGENT_STRIP_X, AGENT_STRIP_Y, AGENT_STRIP_W, AGENT_STRIP_H);

  for (int i = 0; i < AGENT_TAB_COUNT; i++) {
    AgentTabLayout &tab = r_layout->tabs[i];
    const TabMetric &m = g_tab_metrics[i];
    const bool active = (i == int(active_tab));

    /* The artboard draws the filled pill one unit taller and one unit higher
     * than the outlined ones. Reproduce it rather than normalising: at this
     * size the extra unit is what keeps the fill from reading as inset. */
    const float dy = active ? AGENT_TAB_ACTIVE_DY : 0.0f;
    const float dh = active ? AGENT_TAB_ACTIVE_DH : 0.0f;

    tab.active = active;
    tab.pill = f.box(m.x, AGENT_TAB_Y + dy, m.w, AGENT_TAB_H + dh);
    tab.icon = f.box(m.x + AGENT_TAB_PAD_X, AGENT_TAB_ICON_Y, AGENT_TAB_ICON, AGENT_TAB_ICON);

    /* The Queue pill has a count chip where the others have an icon, and it is
     * wider than one; its label starts clear of that instead. */
    const float label_du = (i == AGENT_TAB_QUEUE) ?
                               (AGENT_QUEUE_COUNT_X + AGENT_QUEUE_COUNT_W +
                                AGENT_TAB_ICON_GAP) :
                               (m.x + AGENT_TAB_PAD_X + AGENT_TAB_ICON +
                                AGENT_TAB_ICON_GAP);
    tab.label_x = f.x(label_du);
  }

  r_layout->queue_count = f.box(
      AGENT_QUEUE_COUNT_X, AGENT_QUEUE_COUNT_Y, AGENT_QUEUE_COUNT_W, AGENT_QUEUE_COUNT_H);
  r_layout->new_badge = f.box(
      AGENT_NEW_BADGE_X, AGENT_NEW_BADGE_Y, AGENT_NEW_BADGE_W, AGENT_NEW_BADGE_H);

  /* --- Card ---
   * Top pinned to the artboard's grid, foot pinned to the window's bottom, so
   * a taller window grows the conversation rather than detaching the composer
   * from the card. At the compact height this is identical to the artboard. */
  const float card_h = std::max(float(AGENT_CARD_H),
                                region_h / u + AGENT_ISLAND_TOP - AGENT_CARD_Y);
  r_layout->card = f.box(AGENT_CARD_X, AGENT_CARD_Y, AGENT_CARD_W, card_h);
  r_layout->card_fill = f.box(AGENT_CARD_X + AGENT_CARD_BORDER,
                              AGENT_CARD_Y + AGENT_CARD_BORDER,
                              AGENT_CARD_W - AGENT_CARD_BORDER * 2,
                              card_h - AGENT_CARD_BORDER * 2);
  r_layout->card_grad_a[0] = f.x(AGENT_CARD_X + AGENT_CARD_GRAD_X0);
  r_layout->card_grad_a[1] = f.y(AGENT_CARD_Y + AGENT_CARD_GRAD_Y0);
  r_layout->card_grad_b[0] = f.x(AGENT_CARD_X + AGENT_CARD_GRAD_X1);
  r_layout->card_grad_b[1] = f.y(AGENT_CARD_Y + AGENT_CARD_GRAD_Y1);

  r_layout->card_header = f.box(
      AGENT_CARD_X, AGENT_CARD_Y, AGENT_CARD_W, AGENT_CARD_HEADER_H);

  const float hdr_cy = AGENT_CARD_Y + AGENT_HDR_BTN_CY;
  r_layout->hdr_history = f.disc(AGENT_HDR_BTN1_CX, hdr_cy, AGENT_HDR_BTN_R);
  r_layout->hdr_new_chat = f.disc(AGENT_HDR_BTN2_CX, hdr_cy, AGENT_HDR_BTN_R);

  /* "FAQs" is right-aligned against the card's inner edge; the hit rect is
   * grown to the header's full height so a near-miss above or below the
   * 15-unit ink box still lands. */
  const float faq_right = AGENT_CARD_X + AGENT_CARD_W - AGENT_HDR_FAQ_INSET;
  r_layout->hdr_faq = f.box(faq_right - 60, AGENT_CARD_Y + 20, 60, 34);

  r_layout->hdr_title_cx = f.x(AGENT_CARD_X + AGENT_CARD_W * 0.5f);
  r_layout->hdr_title_y = f.y(AGENT_CARD_Y + AGENT_CARD_HEADER_H * 0.5f);

  /* --- Inner panel, and the stack that hangs off the card's foot --- */
  const float card_bottom = AGENT_CARD_Y + card_h;
  /* The panel runs to the card BOTTOM, keeping only the same 6-unit inset it
   * has at the sides (artboard: card ends 569, panel 563). Mirroring the
   * card-top offset here instead left a 76-unit band of bare card gradient
   * under every pane — the "green strip" under the prompt box. */
  const float panel_h = card_bottom - AGENT_PANEL_Y - (AGENT_PANEL_X - AGENT_CARD_X);
  r_layout->panel = f.box(AGENT_PANEL_X, AGENT_PANEL_Y, AGENT_PANEL_W, panel_h);

  const float chip_y = card_bottom - AGENT_CARD_PAD_BOTTOM - AGENT_CHIP_H;

  /* The input is not a box inside the panel — with no conversation it IS the
   * panel (the artboard's one big field with the ghost text at its top-left).
   * Once a transcript exists it collapses to a strip above the chip row and
   * the transcript region owns the panel. */
  const float input_y = has_transcript ? (chip_y - AGENT_INPUT_GAP - AGENT_INPUT_H)
                                       : AGENT_PANEL_Y;
  r_layout->input = f.box(AGENT_PANEL_X,
                          input_y,
                          AGENT_PANEL_W,
                          chip_y - AGENT_INPUT_GAP - input_y);
  r_layout->transcript = f.box(AGENT_PANEL_X,
                               AGENT_PANEL_Y,
                               AGENT_PANEL_W,
                               input_y - AGENT_TRANSCRIPT_GAP - AGENT_PANEL_Y);
  r_layout->prompt_x = f.x(AGENT_PROMPT_X);
  /* Optical centre of the first line's ink box, not its baseline — the
   * painter centres every label the same way. */
  r_layout->prompt_y = f.y(AGENT_PROMPT_Y + AGENT_PROMPT_FONT * 0.5f);

  /* --- Chip row ---
   * The mode toggle is gone (there is only Agent mode), so Upload Reference
   * takes the row's left edge where the toggle sat. */
  r_layout->chip_upload = f.box(
      AGENT_SEG_X, chip_y, AGENT_CHIP_UPLOAD_W, AGENT_CHIP_H);
  r_layout->btn_generate = f.box(
      AGENT_BTN_GENERATE_X, chip_y, AGENT_BTN_GENERATE_W, AGENT_CHIP_H);
}

/** \} */

