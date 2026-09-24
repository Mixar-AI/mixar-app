/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Builds the Agent island's geometry from the artboard tokens.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string_ref.hh"
#include "BLI_vector.hh"

#include "BKE_screen.hh"

#include "BLF_api.hh"

#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"

#include "UI_interface.hh"
#include "UI_mixar.hh"

#include "agent_ui_layout.hh"
#include "agent_ui_draw.hh"
#include "BLI_string.h"
#include "agent_ui_text.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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
  const char *label;
};

const TabMetric g_tab_metrics[AGENT_TAB_COUNT] = {
    {AGENT_TAB_X_AGENT, AGENT_TAB_W_AGENT, "Agent"},
    {AGENT_TAB_X_3D, AGENT_TAB_W_3D, "3D"},
    {AGENT_TAB_X_IMAGE, AGENT_TAB_W_IMAGE, "Image"},
    {AGENT_TAB_X_VIDEO, AGENT_TAB_W_VIDEO, "Video"},
    {AGENT_TAB_X_SPLAT, AGENT_TAB_W_SPLAT, "Gaussian Splat"},
    {AGENT_TAB_X_GENERATIONS, AGENT_TAB_W_GENERATIONS, "Library"},
    {AGENT_TAB_X_QUEUE, AGENT_TAB_W_QUEUE, "Queue"},
};

}  // namespace

const char *agent_ui_tab_label(const AgentTabId tab)
{
  return g_tab_metrics[tab].label;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Build
 * \{ */

float agent_ui_composer_wrap_width_px(const int window_w, const int pad_real_w)
{
  const bool pad = pad_real_w > 0;
  const float u = float(window_w) / float(AGENT_ISLAND_W);
  const float region_w = pad ? float(pad_real_w) : float(window_w);
  const float island_w = pad ? (region_w / u) : float(AGENT_ISLAND_W);
  const float card_w = island_w - AGENT_CARD_X * 2.0f;
  return (card_w - AGENT_SEG_X * 2.0f) * u;
}

int agent_ui_composer_visual_lines(const char *text, const float wrap_width_px)
{
  if (text == nullptr || text[0] == '\0') {
    return 1;
  }

  /* Must match widget_draw_text_multiline: native widget font, wrap width
   * after the 0.4 UI-unit text pad and 4*pixelsize inset. */
  const int text_pad = int(0.4f * U.widget_unit);
  const int width = std::max(int(wrap_width_px) - text_pad - int(4.0f * U.pixelsize), 10);

  uiFontStyle fstyle = ui::style_get()->widget;
  ui::fontstyle_set(&fstyle);
  const int fontid = fstyle.uifont_id;
  const int text_len = int(strlen(text));
  blender::Vector<blender::StringRef> lines = BLF_string_wrap(
      fontid,
      blender::StringRef(text, text_len),
      width,
      BLFWrapMode(int(BLFWrapMode::Typographical) | int(BLFWrapMode::HardLimit)));
  int count = int(lines.size());
  if (text_len > 0 && text[text_len - 1] == '\n') {
    count++;
  }
  return std::clamp(std::max(1, count), 1, AGENT_INPUT_MAX_LINES);
}

float agent_ui_composer_strip_h(const int visual_lines)
{
  const int lines = std::clamp(visual_lines, 1, AGENT_INPUT_MAX_LINES);
  return float(AGENT_INPUT_H * lines);
}

float agent_ui_panel_top(const AgentTabId tab)
{
  return tab == AGENT_TAB_AGENT ? float(AGENT_PANEL_Y) : float(AGENT_CARD_Y + 12);
}

void agent_ui_layout_build(const int window_w,
                           const int window_h,
                           AgentTabId active_tab,
                           const bool /*agent_mode_active*/,
                           const bool has_transcript,
                           AgentIslandLayout *r_layout,
                           const int pad_real_w,
                           const int input_lines)
{
  *r_layout = {};
  const bool pad = pad_real_w > 0;
  r_layout->pad = pad;

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

  /* The pad lays out across its own (narrower) width with the unit above. */
  const float region_w = pad ? float(pad_real_w) : float(window_w);
  const float region_h = float(window_h);

  r_layout->scale = u;

  /* Horizontal extent in artboard units: the artboard's 1310 normally, the
   * pad window's width in island units when padded. Every width below is
   * derived from it so the pad re-flows instead of overflowing. */
  const float island_w = pad ? (region_w / u) : float(AGENT_ISLAND_W);
  const float card_w = island_w - AGENT_CARD_X * 2.0f;
  const float panel_y = agent_ui_panel_top(active_tab);
  const float panel_w = card_w - (AGENT_PANEL_X - AGENT_CARD_X) * 2.0f;
  /* Artboard y that sits at the window's top edge: the tab strip normally;
   * the pad has no strip and starts just above its card. */
  const float top_du = pad ? float(AGENT_CARD_Y - AGENT_PAD_TOP_INSET) : float(AGENT_ISLAND_TOP);

  /* A pixel of slack. The window is sized from an integer count of unscaled
   * points, so rounding can leave it a fraction under the chrome floor —
   * an exact comparison then rejects the whole island and paints nothing. */
  const float slack = 2.0f;
  /* Chrome floor: card header + one input line + chips + foot. The card
   * stretches with the window, so a compact default shorter than the
   * 521-unit artboard is valid — requiring AGENT_ISLAND_H painted the
   * island black and hid every tab/chip. Same floor as the Scribble pad. */
  const float min_h = (panel_y - top_du + AGENT_INPUT_H + AGENT_INPUT_GAP + AGENT_CHIP_H +
                       AGENT_CARD_PAD_BOTTOM) *
                      u;
  if (pad) {
    /* A pad is valid down to the narrowest width its composer row fits. */
    if (island_w < float(AGENT_PAD_MIN_W_UNITS) || region_h < min_h - slack) {
      r_layout->valid = false;
      return;
    }
  }
  else if (region_w < want_w - slack || region_h < min_h - slack) {
    r_layout->valid = false;
    return;
  }
  r_layout->valid = true;

  /* Anchor top-left, so growing the window past the island leaves the slack
   * at the right and bottom rather than shifting the design off its grid. */
  Frame f;
  f.left = 0.0f;
  /* Artboard y = AGENT_ISLAND_TOP (the tab strip) sits at the window's top
   * edge; the status-pill band above it lives in its own window now. The pad
   * puts its card top there instead (less the small inset). */
  f.top = region_h + top_du * u;
  f.u = u;

  r_layout->island = f.box(0, top_du, island_w, region_h / u);

  /* --- Status pill --- */
  r_layout->pill = f.box(AGENT_PILL_X, AGENT_PILL_Y, AGENT_PILL_W, AGENT_PILL_H);
  r_layout->pill_dot = f.disc(AGENT_PILL_DOT_CX, AGENT_PILL_DOT_CY, AGENT_PILL_DOT_R);
  r_layout->pill_label_x = f.x(AGENT_PILL_LABEL_X);

  /* --- Tab strip ---
   * The pad has none: its rects are left EMPTY (zero-size at the origin) and
   * the painter and the header controls skip the strip on `pad`; only the
   * `active` flags are kept, since the card body still switches on them. */
  r_layout->strip = pad ? rctf{} : f.box(AGENT_STRIP_X, AGENT_STRIP_Y, AGENT_STRIP_W, AGENT_STRIP_H);

  /* Spend the strip's center gap on labels before eliding them. Measurement,
   * paint, native button bounds and QA targets all use this resolved layout. */
  const float text_size = agent_ui_body_font_size();
  const float badge_size = AGENT_NEW_BADGE_FONT * agent_ui_text_unit();
  const float badge_w = std::max(float(AGENT_NEW_BADGE_W),
                                ui::mixar_text_width("NEW", badge_size) / u +
                                    2.0f * AGENT_TAB_ICON_GAP);
  TabMetric tabs[AGENT_TAB_COUNT];
  float extra = 0.0f;
  for (int i = 0; i < AGENT_TAB_COUNT; i++) {
    tabs[i] = g_tab_metrics[i];
    const float leading = i == AGENT_TAB_QUEUE ? AGENT_QUEUE_COUNT_W : AGENT_TAB_ICON;
    const float trailing = i == AGENT_TAB_SPLAT ? badge_w + AGENT_TAB_ICON_GAP : 0.0f;
    const float wanted = ui::mixar_text_width(tabs[i].label, text_size) / u + leading +
                         trailing + 3.0f * AGENT_TAB_ICON_GAP + 2.0f / u;
    tabs[i].w = std::max(tabs[i].w, wanted);
    extra += tabs[i].w - g_tab_metrics[i].w;
  }
  const float spare = AGENT_TAB_X_GENERATIONS - (AGENT_TAB_X_SPLAT + AGENT_TAB_W_SPLAT) -
                      6.0f;
  const float growth = extra > 0.0f ? std::min(1.0f, spare / extra) : 0.0f;
  for (int i = 0; i < AGENT_TAB_COUNT; i++) {
    tabs[i].w = g_tab_metrics[i].w + (tabs[i].w - g_tab_metrics[i].w) * growth;
    if (i > 0 && i <= AGENT_TAB_SPLAT) {
      const float gap = g_tab_metrics[i].x -
                        (g_tab_metrics[i - 1].x + g_tab_metrics[i - 1].w);
      tabs[i].x = tabs[i - 1].x + tabs[i - 1].w + gap;
    }
  }
  tabs[AGENT_TAB_QUEUE].x = AGENT_TAB_X_QUEUE + AGENT_TAB_W_QUEUE - tabs[AGENT_TAB_QUEUE].w;
  tabs[AGENT_TAB_GENERATIONS].x = tabs[AGENT_TAB_QUEUE].x - 6.0f -
                                tabs[AGENT_TAB_GENERATIONS].w;

  for (int i = 0; i < AGENT_TAB_COUNT; i++) {
    AgentTabLayout &tab = r_layout->tabs[i];
    const TabMetric &m = tabs[i];
    const bool active = (i == int(active_tab));
    if (pad) {
      tab = {};
      tab.active = active;
      continue;
    }

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
                               (m.x + AGENT_QUEUE_COUNT_X - AGENT_TAB_X_QUEUE +
                                AGENT_QUEUE_COUNT_W + AGENT_TAB_ICON_GAP) :
                               (m.x + AGENT_TAB_PAD_X + AGENT_TAB_ICON +
                                AGENT_TAB_ICON_GAP);
    tab.label_x = f.x(label_du);
  }

  r_layout->queue_count = pad ? rctf{} :
                                f.box(AGENT_QUEUE_COUNT_X,
                                      AGENT_QUEUE_COUNT_Y,
                                      AGENT_QUEUE_COUNT_W,
                                      AGENT_QUEUE_COUNT_H);
  r_layout->new_badge = pad ? rctf{} :
                              f.box(AGENT_NEW_BADGE_X,
                                    AGENT_NEW_BADGE_Y,
                                    badge_w,
                                    AGENT_NEW_BADGE_H);

  /* --- Card ---
   * Top pinned to the artboard's grid, foot pinned to the window's bottom, so
   * a taller window grows the conversation rather than detaching the composer
   * from the card. A shorter window (the compact empty island) must shrink
   * the same way — flooring at AGENT_CARD_H kept the chip row 448 artboard
   * units down and painted it below a 190 px window.
   * (The pad's top is its own inset, so its card runs the whole window.) */
  const float card_h = std::max(0.0f, region_h / u + top_du - AGENT_CARD_Y);
  r_layout->card = f.box(AGENT_CARD_X, AGENT_CARD_Y, card_w, card_h);
  r_layout->card_fill = f.box(AGENT_CARD_X + AGENT_CARD_BORDER,
                              AGENT_CARD_Y + AGENT_CARD_BORDER,
                              card_w - AGENT_CARD_BORDER * 2,
                              card_h - AGENT_CARD_BORDER * 2);

  r_layout->card_header = f.box(AGENT_CARD_X, AGENT_CARD_Y, card_w, AGENT_CARD_HEADER_H);

  const float hdr_cy = AGENT_CARD_Y + AGENT_HDR_BTN_CY;
  r_layout->hdr_history = f.disc(AGENT_HDR_BTN1_CX, hdr_cy, AGENT_HDR_BTN_R);
  r_layout->hdr_new_chat = f.disc(AGENT_HDR_BTN2_CX, hdr_cy, AGENT_HDR_BTN_R);
  r_layout->hdr_checkpoints = f.disc(AGENT_HDR_BTN3_CX, hdr_cy, AGENT_HDR_BTN_R);
  r_layout->hdr_rules = f.disc(AGENT_HDR_BTN4_CX, hdr_cy, AGENT_HDR_BTN_R);

  const float handwriting_cx = AGENT_CARD_X + card_w - AGENT_SEG_X - AGENT_HDR_BTN_R;
  r_layout->hdr_handwriting = f.disc(handwriting_cx, hdr_cy, AGENT_HDR_BTN_R);
  r_layout->hdr_title_cx = (r_layout->hdr_rules.xmax +
                            r_layout->hdr_handwriting.xmin) * 0.5f;
  r_layout->hdr_title_y = f.y(AGENT_CARD_Y + AGENT_CARD_HEADER_H * 0.5f);

  /* --- Inner panel, and the stack that hangs off the card's foot --- */
  const float card_bottom = AGENT_CARD_Y + card_h;
  /* The panel runs to the card BOTTOM, keeping only the same 6-unit inset it
   * has at the sides (artboard: card ends 569, panel 563). Mirroring the
   * card-top offset here instead left a 76-unit band of bare card gradient
   * under every pane — the "green strip" under the prompt box. */
  const float panel_h = card_bottom - panel_y - (AGENT_PANEL_X - AGENT_CARD_X);
  r_layout->panel = f.box(AGENT_PANEL_X, panel_y, panel_w, panel_h);

  const float chip_y = card_bottom - AGENT_CARD_PAD_BOTTOM - AGENT_CHIP_H;

  /* The input bubble shares the same horizontal bounds (AGENT_SEG_X) as the
   * button row below it, aligning them on both sides with uniform margins.
   * Once a transcript exists it collapses to a strip above the chip row and
   * the transcript region owns the panel. */
  const float input_x = AGENT_SEG_X;
  const float input_w = card_w - AGENT_SEG_X * 2.0f;
  /* After the first send the field is a strip above the chips. Grow that
   * strip with the draft (1–4 visual lines) so Shift+Enter stays visible —
   * a fixed AGENT_INPUT_H row is ~29 px at the default 678-wide island,
   * which falls under the 1.5*UI_UNIT_Y multiline gate and clips later
   * prompts to a single line. */
  const float strip_h = agent_ui_composer_strip_h(input_lines);
  const float input_y = has_transcript ? (chip_y - AGENT_INPUT_GAP - strip_h) :
                                         panel_y;
  r_layout->input = f.box(input_x,
                          input_y,
                          input_w,
                          chip_y - AGENT_INPUT_GAP - input_y);
  r_layout->transcript = f.box(AGENT_PANEL_X,
                               panel_y,
                               panel_w,
                               input_y - AGENT_TRANSCRIPT_GAP - panel_y);
  r_layout->prompt_x = f.x(AGENT_PROMPT_X);
  /* Optical centre of the first line's ink box, not its baseline — the
   * painter centres every label the same way. */
  r_layout->prompt_y = f.y(AGENT_PROMPT_Y + AGENT_PROMPT_FONT * 0.5f);

  /* --- Chip row ---
   * The mode toggle is gone (there is only Agent mode), so Upload Reference
   * takes the row's left edge where the toggle sat. Left to right: Upload
   * Reference, Scribble, Voice, Auto, Model, then the two conditional
   * Scribble chips; Send is pinned to the right inset. */
  const float scribble_x = AGENT_SEG_X + AGENT_CHIP_UPLOAD_W + AGENT_CHIP_GAP;
  r_layout->chip_upload = f.box(AGENT_SEG_X, chip_y, AGENT_CHIP_UPLOAD_W, AGENT_CHIP_H);
  r_layout->chip_scribble = f.box(scribble_x, chip_y, AGENT_CHIP_SCRIBBLE_W, AGENT_CHIP_H);
  r_layout->chip_voice = f.box(scribble_x, chip_y, AGENT_CHIP_VOICE_W, AGENT_CHIP_H);
  r_layout->chip_auto = f.box(scribble_x, chip_y, AGENT_CHIP_AUTO_W, AGENT_CHIP_H);
  r_layout->chip_model = f.box(scribble_x, chip_y, AGENT_CHIP_MODEL_W, AGENT_CHIP_H);
  r_layout->model_form = AgentModelChipForm::Full;
  r_layout->chip_reading = f.box(scribble_x, chip_y, AGENT_CHIP_READING_W, AGENT_CHIP_H);
  r_layout->chip_clear = f.box(scribble_x, chip_y, AGENT_CHIP_CLEAR_W, AGENT_CHIP_H);
  /* Generate keeps the artboard's right inset against whatever card width
   * this layout has (AGENT_BTN_GENERATE_X generalised to `card_w`). */
  r_layout->btn_generate = f.box(card_w - AGENT_SEG_X - AGENT_BTN_GENERATE_W,
                                 chip_y,
                                 AGENT_BTN_GENERATE_W,
                                 AGENT_CHIP_H);
}

/* Measure every form of every chip actually shown — Done, the drawing intent,
 * Voice's Stop/ECG or status, a long model name — and let #agent_chip_fit pick
 * the forms, so the row never runs under Send. See agent_ui_chip_fit.hh. */
void agent_ui_layout_fit_controls(AgentIslandLayout &layout, const AgentIslandState &state)
{
  const float u = layout.scale;
  const float size = AGENT_CHIP_FONT * agent_ui_text_unit();
  const float gap = AGENT_CHIP_GAP * u;

  AgentChipRowInputs in;
  in.scribble_available = state.scribble_available;
  in.scribble_armed = state.scribble_armed;
  in.mark_count = state.mark_count;
  in.mark_intent = state.mark_intent;
  in.voice_available = state.voice_available;
  in.voice_listening = state.voice_listening;
  in.voice_capturing = state.voice_capturing;
  in.voice_status = state.voice_status;
  in.model_available = state.model_available;
  in.model_label = state.model_label;
  const AgentChipMetrics metrics{AGENT_CHIP_ICON * u,
                                 AGENT_CHIP_ICON_GAP * u,
                                 AGENT_CHIP_PAD_X * u,
                                 AGENT_SWITCH_W * u,
                                 AGENT_CHIP_CLEAR_W * u,
                                 AGENT_CHIP_WAVE_W * u,
                                 size};
  AgentChipForms chips[AGENT_CHIP_SLOT_COUNT];
  agent_chip_forms(
      in, metrics, [&](const char *label) { return ui::mixar_text_width(label, size); }, chips);

  const float span = layout.btn_generate.xmin - layout.chip_upload.xmin;
  const AgentChipFit fit = agent_chip_fit(chips, span, gap);
  layout.compact_reference = fit.compact_reference;
  std::copy_n(fit.form, int(AGENT_CHIP_SLOT_COUNT), layout.chip_form);
  const int model_form = fit.form[AGENT_CHIP_SLOT_MODEL];
  layout.model_form = model_form < 3 ? AgentModelChipForm(model_form) : AgentModelChipForm::Icon;

  float x = layout.chip_upload.xmin;
  auto place = [&](rctf &rect, const float w) {
    if (w <= 0) { rect = {}; return; }
    rect.xmin = x;
    rect.xmax = x + w;
    x += w + gap;
  };
  place(layout.chip_upload, fit.width[AGENT_CHIP_SLOT_UPLOAD]);
  place(layout.chip_scribble, fit.width[AGENT_CHIP_SLOT_SCRIBBLE]);
  place(layout.chip_voice, fit.width[AGENT_CHIP_SLOT_VOICE]);
  place(layout.chip_auto, fit.width[AGENT_CHIP_SLOT_AUTO]);
  place(layout.chip_model, fit.width[AGENT_CHIP_SLOT_MODEL]);
  place(layout.chip_reading, fit.width[AGENT_CHIP_SLOT_READING]);
  place(layout.chip_clear, fit.width[AGENT_CHIP_SLOT_CLEAR]);
}

/** \} */

}  // namespace blender
