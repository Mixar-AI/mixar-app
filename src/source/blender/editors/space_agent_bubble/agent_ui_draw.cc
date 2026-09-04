/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Paints the Agent island.
 *
 * Shapes come from `agent_ui_layout`; colours and sizes from
 * `agent_ui_theme`. Nothing here re-derives geometry — the hit test reads the
 * same layout struct, and one definition is what keeps a click landing where
 * the pixel it targets was drawn.
 */

#include <algorithm>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"

#include "agent_ui_draw.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Shape helpers
 * \{ */

void fill_round(const rctf *rect, const float radius, const float col[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(rect, true, radius, col);
}

void outline_round(const rctf *rect, const float radius, const float col[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(rect, false, radius, col);
}

/**
 * Rounded rect filled with a two-stop ramp along an ARBITRARY axis.
 *
 * `ui::draw_roundbox_4fv_ex` can only shade vertically, and the card's ramp is
 * diagonal — it runs from the card's top-right down and to the left, past the
 * bottom edge. Shading it vertically loses the horizontal falloff entirely,
 * which is most of the effect: at the card's top edge the artboard travels
 * from #072B1B on the left to #2E5630 on the right.
 *
 * So the fill is a triangle fan with per-vertex colour, sampled at
 * t = clamp(dot(p - a, b - a) / |b - a|^2, 0, 1). The fan's edge has no
 * coverage anti-aliasing, which is why the caller draws it INSET inside the
 * card's 2-unit border — the AA'd border covers the seam.
 */
void fill_round_gradient(const rctf *rect,
                         const float radius,
                         const float c0[4],
                         const float c1[4],
                         const float a[2],
                         const float b[2])
{
  const float abx = b[0] - a[0];
  const float aby = b[1] - a[1];
  const float len_sq = abx * abx + aby * aby;
  if (len_sq <= 0.0f) {
    fill_round(rect, radius, c0);
    return;
  }

  /* Corner arcs: 8 segments each is past the point where more is visible at
   * this radius, and keeps the fan under 40 vertices. */
  constexpr int ARC = 8;
  constexpr int RIM = (ARC + 1) * 4;

  const float x0 = rect->xmin;
  const float x1 = rect->xmax;
  const float y0 = rect->ymin;
  const float y1 = rect->ymax;
  const float r = std::min(radius, std::min((x1 - x0), (y1 - y0)) * 0.5f);

  float rim[RIM][2];
  int n = 0;
  /* Corner centres walked ANTICLOCKWISE from bottom-right, each sweeping the
   * quadrant that starts at `base`. Centre order and angle order have to agree
   * — pairing a bottom-left centre with a bottom-right quadrant folds the
   * polygon in on itself and the fill stops covering the card. */
  const float cx[4] = {x1 - r, x1 - r, x0 + r, x0 + r};
  const float cy[4] = {y0 + r, y1 - r, y1 - r, y0 + r};
  for (int corner = 0; corner < 4; corner++) {
    const float base = float(M_PI) * -0.5f + float(corner) * float(M_PI) * 0.5f;
    for (int i = 0; i <= ARC; i++) {
      const float ang = base + (float(M_PI) * 0.5f) * (float(i) / float(ARC));
      rim[n][0] = cx[corner] + std::cos(ang) * r;
      rim[n][1] = cy[corner] + std::sin(ang) * r;
      n++;
    }
  }

  auto sample = [&](const float px, const float py, float out[4]) {
    float t = ((px - a[0]) * abx + (py - a[1]) * aby) / len_sq;
    t = std::clamp(t, 0.0f, 1.0f);
    for (int i = 0; i < 4; i++) {
      out[i] = c0[i] + (c1[i] - c0[i]) * t;
    }
  };

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);

  immBegin(GPU_PRIM_TRI_FAN, n + 2);
  float c[4];
  const float mid_x = (x0 + x1) * 0.5f;
  const float mid_y = (y0 + y1) * 0.5f;
  sample(mid_x, mid_y, c);
  immAttr4fv(col, c);
  immVertex2f(pos, mid_x, mid_y);
  for (int i = 0; i < n; i++) {
    sample(rim[i][0], rim[i][1], c);
    immAttr4fv(col, c);
    immVertex2f(pos, rim[i][0], rim[i][1]);
  }
  /* Close the fan back onto its first rim vertex. */
  sample(rim[0][0], rim[0][1], c);
  immAttr4fv(col, c);
  immVertex2f(pos, rim[0][0], rim[0][1]);
  immEnd();

  immUnbindProgram();
}

/**
 * The card's border, drawn as a credits meter.
 *
 * A full bright ring means a full allowance; as credits are spent the lit part
 * retreats and the spent part is drawn in a dim green, so the border reads as a
 * percentage strip running around the card rather than as decoration.
 *
 * The ring starts at the top-left corner and runs CLOCKWISE. That start point
 * is deliberate: it is the corner the eye already goes to, so the gap opens
 * where it is legible instead of behind the chip row.
 *
 * `remaining` outside [0,1] means "unknown" and draws the ring whole — an
 * empty-looking border on an account whose balance simply has not loaded yet
 * would read as a rendering bug, not as information.
 */
void draw_card_border_meter(const rctf *rect,
                            const float radius,
                            const float width,
                            const float lit[4],
                            const float spent[4],
                            const float remaining)
{
  if (remaining < 0.0f || remaining >= 1.0f) {
    fill_round(rect, radius, lit);
    return;
  }

  /* Perimeter walked as four straight runs; the corner arcs are short enough at
   * this radius that folding them into the adjacent runs is imperceptible, and
   * it keeps the meter's arithmetic to one dimension. */
  const float w = BLI_rctf_size_x(rect);
  const float h = BLI_rctf_size_y(rect);
  const float total = (w + h) * 2.0f;
  const float lit_len = total * remaining;

  fill_round(rect, radius, spent);

  /* Each run is (start distance along the perimeter, length, rect builder). */
  struct Run {
    float len;
    int axis; /* 0 = along the top, 1 = down the right, 2 = along the bottom, 3 = up the left */
  };
  const Run runs[4] = {{w, 0}, {h, 1}, {w, 2}, {h, 3}};

  float walked = 0.0f;
  for (const Run &run : runs) {
    if (walked >= lit_len) {
      break;
    }
    const float take = std::min(run.len, lit_len - walked);
    const float t = take / run.len;
    rctf seg;
    switch (run.axis) {
      case 0: /* top, left -> right */
        seg.xmin = rect->xmin;
        seg.xmax = rect->xmin + w * t;
        seg.ymin = rect->ymax - width;
        seg.ymax = rect->ymax;
        break;
      case 1: /* right, top -> bottom */
        seg.xmin = rect->xmax - width;
        seg.xmax = rect->xmax;
        seg.ymin = rect->ymax - h * t;
        seg.ymax = rect->ymax;
        break;
      case 2: /* bottom, right -> left */
        seg.xmin = rect->xmax - w * t;
        seg.xmax = rect->xmax;
        seg.ymin = rect->ymin;
        seg.ymax = rect->ymin + width;
        break;
      default: /* left, bottom -> top */
        seg.xmin = rect->xmin;
        seg.xmax = rect->xmin + width;
        seg.ymin = rect->ymin;
        seg.ymax = rect->ymin + h * t;
        break;
    }
    fill_round(&seg, width * 0.5f, lit);
    walked += take;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Text helpers
 *
 * `chat_ui_draw_label` positions by baseline. The island positions almost
 * everything by optical centre instead, so these measure first. Measuring is
 * cheap next to the alternative: the account card learned the hard way that
 * BLF clips without an ellipsis, so a label that outgrows its slot vanishes
 * mid-word with no runtime signal at all.
 * \{ */

int island_font()
{
  return BLF_default();
}

float text_width(const char *text, const float size)
{
  const int font = island_font();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

/** Draw \a text with its left edge at \a x and its ink centred on \a cy. */
void label_left(const char *text, const float x, const float cy, const float size,
                const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = island_font();
  BLF_size(font, size);
  /* Blender's widget text pass sets BLF_CLIPPING on the default font and does
   * not always leave it off. Any label drawn afterwards — the placeholder is
   * drawn after the uiBlocks on purpose — then gets clipped to that widget's
   * rect and vanishes silently, which is exactly how it presents: no error,
   * no glyphs. Clear it before every island label. */
  BLF_disable(font, BLF_CLIPPING);

  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;

  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

/** Draw \a text centred on (cx, cy). */
void label_centre(const char *text, const float cx, const float cy, const float size,
                  const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  label_left(text, cx - text_width(text, size) * 0.5f, cy, size, col);
}

/** Draw \a text with its right edge at \a x. */
void label_right(const char *text, const float x, const float cy, const float size,
                 const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  label_left(text, x - text_width(text, size), cy, size, col);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tab strip
 * \{ */

struct TabSpec {
  const char *label;
  /** #AGENT_ICON_COUNT means the tab carries NO mark. */
  AgentIcon icon;
};

/* `generations.svg` marks Agent, Gaussian Splat and My Generations only. 3D
 * and Media take the island's own cube and picture glyphs so the strip does
 * not read as two tabs that failed to load — both pills have room for the
 * 24-unit slot plus their label without widening. Queue keeps its count chip
 * in that slot and centres its label when the queue is empty. */
const TabSpec g_tabs[AGENT_TAB_COUNT] = {
    {"Agent", AGENT_ICON_AGENT},
    {"3D", AGENT_ICON_MESH},
    {"Media", AGENT_ICON_IMAGE},
    {"Gaussian Splat", AGENT_ICON_SPLAT},
    {"My Generations", AGENT_ICON_THUMB},
    {"Queue", AGENT_ICON_COUNT},
};

void draw_tab_strip(const AgentIslandLayout *layout, const AgentIslandState *state)
{
  const float u = layout->scale;
  const float surface[4] = AGENT_COL_SURFACE;
  const float outline[4] = AGENT_COL_OUTLINE;
  const float active_fill[4] = AGENT_COL_TAB_ACTIVE;
  const float queue_fill[4] = AGENT_COL_QUEUE;
  const float queue_count[4] = AGENT_COL_QUEUE_COUNT;
  const float accent[4] = AGENT_COL_ACCENT;
  const float text[4] = AGENT_COL_TEXT;
  const float strong[4] = AGENT_COL_TEXT_STRONG;
  const float text_dim[4] = AGENT_COL_TEXT_DIM;

  fill_round(&layout->strip, AGENT_STRIP_RADIUS * u, surface);

  /* Text is sized in the ISLAND unit, not AGENT_DU(): the two agree only at
   * the default window width, and the window widens freely (the bubble
   * constrains its MINIMUM size only). Sizing glyphs off UI_SCALE_FAC while
   * every rect grows with `u` left labels stranded at their original pixel
   * size inside grown pills. */
  const float label_size = AGENT_TAB_FONT * u;

  for (int i = 0; i < AGENT_TAB_COUNT; i++) {
    const AgentTabLayout &tab = layout->tabs[i];
    const float cy = BLI_rctf_cent_y(&tab.pill);

    if (i == AGENT_TAB_QUEUE) {
      /* The Queue pill is the one filled-and-outlined tab in the strip; it
       * reads as a control rather than a tab, which is what it is. */
      fill_round(&tab.pill, AGENT_TAB_RADIUS * u, queue_fill);
      outline_round(&tab.pill, AGENT_TAB_RADIUS * u, outline);
    }
    else if (tab.active) {
      fill_round(&tab.pill, (AGENT_TAB_RADIUS + 0.5f) * u, active_fill);
    }
    else {
      outline_round(&tab.pill, AGENT_TAB_RADIUS * u, outline);
    }

    /* Active tab and the Queue pill are pure white in the artboard; every
     * other tab label is #757575. */
    const float *label_col = (tab.active || i == AGENT_TAB_QUEUE) ? strong : text_dim;

    if (i == AGENT_TAB_QUEUE) {
      /* Count chip stands in for the icon slot. */
      if (state->queue_count > 0) {
        char count[8];
        if (state->queue_count > 9) {
          BLI_strncpy(count, "9+", sizeof(count));
        }
        else {
          BLI_snprintf(count, sizeof(count), "%d+", state->queue_count);
        }
        fill_round(&layout->queue_count, AGENT_QUEUE_COUNT_RADIUS * u, queue_count);
        label_centre(count,
                     BLI_rctf_cent_x(&layout->queue_count),
                     BLI_rctf_cent_y(&layout->queue_count),
                     AGENT_NEW_BADGE_FONT * u,
                     text);
      }
    }
    else if (g_tabs[i].icon != AGENT_ICON_COUNT) {
      /* Backdrop is this pill's own fill — the active pill is #183E25, the
       * rest sit directly on the strip. */
      const float *pill_bg = tab.active ? active_fill : surface;
      agent_ui_icon_draw(g_tabs[i].icon, &tab.icon, label_col, pill_bg);
    }

    /* A tab with nothing in its icon slot centres its label; leaving it at
     * the icon offset would hang the word off to the right of an empty pill.
     * The Queue pill does the same once its count chip is gone. */
    const bool centred = (g_tabs[i].icon == AGENT_ICON_COUNT) &&
                         (i != AGENT_TAB_QUEUE || state->queue_count <= 0);
    if (centred) {
      label_centre(g_tabs[i].label, BLI_rctf_cent_x(&tab.pill), cy, label_size,
                   label_col);
    }
    else {
      label_left(g_tabs[i].label, tab.label_x, cy, label_size, label_col);
    }

    if (i == AGENT_TAB_SPLAT && state->splat_is_new) {
      fill_round(&layout->new_badge, AGENT_NEW_BADGE_RADIUS * u, accent);
      label_centre("NEW",
                   BLI_rctf_cent_x(&layout->new_badge),
                   BLI_rctf_cent_y(&layout->new_badge),
                   AGENT_NEW_BADGE_FONT * u,
                   strong);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Chip row
 * \{ */

void draw_chip_row(const AgentIslandLayout *layout, const AgentIslandState *state)
{
  const float u = layout->scale;
  const float chip[4] = AGENT_COL_CHIP;
  const float generate[4] = AGENT_COL_GENERATE;
  const float text[4] = AGENT_COL_TEXT;

  /* Every metric here is in the island unit. Mixing `* u` (radius) with
   * AGENT_DU() (pad/gap/icon) drifted the icon off-centre and started the
   * label at the wrong x as soon as the window left its default width. */
  const float size = AGENT_CHIP_FONT * u;
  const float radius = AGENT_CHIP_RADIUS * u;
  const float pad = AGENT_CHIP_PAD_X * u;
  const float icon_gap = AGENT_CHIP_ICON_GAP * u;
  const float icon_edge = AGENT_CHIP_ICON * u;

  /* Composer chips belong to the Agent tab; other tabs fill the card with
   * their own content (Queue rows, later panes). */
  if (layout->tabs[AGENT_TAB_AGENT].active == false) {
    return;
  }

  /* Upload Reference. The artboard truncates this to "Upload Refe…" inside a
   * 150-unit chip; the ellipsis is the design, not an accident of the export,
   * so the chip keeps its width and the label keeps its truncation. */
  fill_round(&layout->chip_upload, radius, chip);
  {
    rctf icon = layout->chip_upload;
    icon.xmin += pad;
    icon.xmax = icon.xmin + icon_edge;
    const float cy = BLI_rctf_cent_y(&layout->chip_upload);
    icon.ymin = cy - icon_edge * 0.5f;
    icon.ymax = cy + icon_edge * 0.5f;
    agent_ui_icon_draw(AGENT_ICON_IMAGE, &icon, text, chip);
    label_left("Upload Reference", icon.xmax + icon_gap, cy, size, text);
  }

  /* Scribble. Lit in the accent while either half is up (the viewport freeze
   * or the chat ink canvas) — the same "pressed" the headers show — and
   * carrying the count of draft marks that will ride with the next message.
   * The reading chip and the clear X exist only while marks are queued: a
   * drawing silently read as nine placement targets is a mode the user could
   * neither see nor correct, so the reading is on the surface, and queued
   * marks need a way out that does not re-enter the freeze. */
  if (state->scribble_available) {
    const float accent[4] = AGENT_COL_ACCENT;
    const float *scribble_fill = state->scribble_armed ? accent : chip;
    fill_round(&layout->chip_scribble, radius, scribble_fill);
    {
      rctf icon = layout->chip_scribble;
      icon.xmin += pad;
      icon.xmax = icon.xmin + icon_edge;
      const float cy = BLI_rctf_cent_y(&layout->chip_scribble);
      icon.ymin = cy - icon_edge * 0.5f;
      icon.ymax = cy + icon_edge * 0.5f;
      agent_ui_icon_draw(AGENT_ICON_PEN, &icon, text, scribble_fill);
      char label[32];
      if (state->mark_count > 0) {
        SNPRINTF(label, "Scribble · %d", state->mark_count);
      }
      else {
        BLI_strncpy(label, "Scribble", sizeof(label));
      }
      label_left(label, icon.xmax + icon_gap, cy, size, text);
    }

    if (state->mark_count > 0) {
      fill_round(&layout->chip_reading, radius, chip);
      const float cy = BLI_rctf_cent_y(&layout->chip_reading);
      const char *reading = state->mark_intent[0] ? state->mark_intent : "Auto";
      label_left(reading, layout->chip_reading.xmin + pad, cy, size, text);
      rctf chevron = layout->chip_reading;
      chevron.xmax -= pad;
      chevron.xmin = chevron.xmax - icon_edge * 0.7f;
      chevron.ymin = cy - icon_edge * 0.35f;
      chevron.ymax = cy + icon_edge * 0.35f;
      agent_ui_icon_draw(AGENT_ICON_CHEVRON_DOWN, &chevron, text, chip);

      if (!state->scribble_armed) {
        fill_round(&layout->chip_clear, radius, chip);
        rctf cross = layout->chip_clear;
        const float ccx = BLI_rctf_cent_x(&cross);
        cross.xmin = ccx - icon_edge * 0.5f;
        cross.xmax = ccx + icon_edge * 0.5f;
        cross.ymin = cy - icon_edge * 0.5f;
        cross.ymax = cy + icon_edge * 0.5f;
        agent_ui_icon_draw(AGENT_ICON_CROSS, &cross, text, chip);
      }
    }
  }

  /* Generate. */
  fill_round(&layout->btn_generate, radius, generate);
  label_centre(state->status_busy ? "Stop" : "Generate",
               BLI_rctf_cent_x(&layout->btn_generate),
               BLI_rctf_cent_y(&layout->btn_generate),
               size,
               text);
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Island
 * \{ */

void agent_ui_draw_status_pill(const float width,
                               const float height,
                               const AgentIslandState *state)
{
  /* Sized from the WINDOW, not the region: the pill's header region comes back
   * taller than the window it lives in, and centring on the region's height
   * put the label and dot above the visible area while the corner radius blew
   * out into a huge arc. */
  const float w = width;
  const float h = height;
  if (w <= 0.0f || h <= 0.0f) {
    return;
  }

  /* ELONGATED resting pill (aspect says which window shape this is): the
   * minimised bubble's whole identity — dim last-prompt preview + the Mixar
   * logo on a green gradient chip (Frame 1533210248.svg). Hovering it
   * expands the island (mixar.bubble_hover_tick). */
  if (w > h * 4.0f) {
    const float u = h / 85.0f; /* design pill is 85 artboard units tall */

    rctf pill;
    pill.xmin = 0.0f;
    pill.xmax = w;
    pill.ymin = 0.0f;
    pill.ymax = h;
    const float grad_top[4] = {0.176f, 0.176f, 0.176f, 1.0f};    /* #2D2D2D */
    const float grad_bottom[4] = {0.075f, 0.078f, 0.075f, 1.0f}; /* #131413 */
    GPU_blend(GPU_BLEND_NONE);
    const float pill_grad_a[2] = {w * 0.985f, h};
    const float pill_grad_b[2] = {w * 0.947f, 0.0f};
    fill_round_gradient(&pill, h * 0.5f, grad_top, grad_bottom, pill_grad_a, pill_grad_b);
    GPU_blend(GPU_BLEND_ALPHA);
    /* Faint rim, brightest toward the top-right like the export's stroke. */
    const float rim[4] = {1.0f, 1.0f, 1.0f, 0.14f};
    outline_round(&pill, h * 0.5f, rim);

    /* Logo chip, right-inset 10.5 units, 85x68 rx25. */
    rctf chip;
    chip.xmax = w - 10.5f * u;
    chip.xmin = chip.xmax - 85.0f * u;
    chip.ymin = h * 0.5f - 34.0f * u;
    chip.ymax = h * 0.5f + 34.0f * u;
    const float chip_a[4] = {0.125f, 0.345f, 0.212f, 1.0f}; /* #205836 */
    const float chip_b[4] = {0.227f, 0.518f, 0.341f, 1.0f}; /* #3A8457 */
    const float chip_grad_a[2] = {chip.xmax - 7.0f * u, chip.ymax - 14.0f * u};
    const float chip_grad_b[2] = {chip.xmin + 2.0f * u, chip.ymin + 30.0f * u};
    fill_round_gradient(&chip, 25.0f * u, chip_a, chip_b, chip_grad_a, chip_grad_b);
    const float icon_edge = 45.0f * u;
    ui::icon_draw_ex(BLI_rctf_cent_x(&chip) - icon_edge * 0.5f,
                    BLI_rctf_cent_y(&chip) - icon_edge * 0.5f,
                    ICON_MIXAR_ICON,
                    /*aspect=*/16.0f / icon_edge, /* icons draw at 16/aspect px */
                    /*alpha=*/1.0f,
                    /*desaturate=*/0.0f,
                    /*mono_color=*/nullptr,
                    /*mono_border=*/false,
                    /*text_overlay=*/nullptr);

    /* Preview line: newest user prompt, dim, ellipsised into the space left
     * of the chip. */
    char preview[160];
    BLI_strncpy(preview,
                state->last_prompt[0] ? state->last_prompt : "Ask Mixie anything...",
                sizeof(preview));
    /* One line only — newlines read as garbage glyphs in BLF. */
    for (char *c = preview; *c; c++) {
      if (*c == '\n' || *c == '\r') {
        *c = ' ';
      }
    }
    const float text_size = 27.0f * u;
    const float text_x = 28.0f * u;
    const float text_max_w = chip.xmin - 16.0f * u - text_x;
    const float dim_col[4] = {0.62f, 0.62f, 0.62f, 1.0f};
    if (text_width(preview, text_size) > text_max_w) {
      size_t len = strlen(preview);
      while (len > 1) {
        preview[--len] = '\0';
        char probe[164];
        SNPRINTF(probe, "%s...", preview);
        if (text_width(probe, text_size) <= text_max_w) {
          BLI_strncpy(preview, probe, sizeof(preview));
          break;
        }
      }
    }
    label_left(preview, text_x, h * 0.5f, text_size, dim_col);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  const float surface[4] = AGENT_COL_SURFACE;
  const float accent[4] = AGENT_COL_ACCENT;
  const float dim_dot[4] = {0.076f, 0.219f, 0.132f, 1.0f};
  const float text_dim[4] = AGENT_COL_TEXT_DIM;

  /* The pill owns its whole window, so it is drawn from the region's size
   * rather than the artboard's rect — the window is sized to the artboard's
   * 135x38 and the proportions inside are kept. */
  rctf pill;
  pill.xmin = 0.0f;
  pill.xmax = w;
  pill.ymin = 0.0f;
  pill.ymax = h;

  /* The pill's own unit — its window is force-sized independently of the
   * island, so it carries neither `layout->scale` nor UI_SCALE_FAC's ratio. */
  const float pill_u = h / float(AGENT_PILL_H);
  const float dot_r = AGENT_PILL_DOT_R * pill_u;
  const float dot_cx = w * (float(AGENT_PILL_DOT_CX - AGENT_PILL_X) / float(AGENT_PILL_W));
  rctf dot;
  dot.xmin = dot_cx - dot_r;
  dot.xmax = dot_cx + dot_r;
  dot.ymin = h * 0.5f - dot_r;
  dot.ymax = h * 0.5f + dot_r;

  /* Paint the WHOLE rect opaquely before the capsule. The pill window's
   * buffers otherwise carry transparent pixels that composite as the bare
   * window backdrop — a flat grey that flashed against the capsule whenever a
   * stale buffer was presented. The OS-level corner mask still rounds the
   * window, so the corners never show this fill. */
  const float bed[4] = {0.02f, 0.02f, 0.02f, 1.0f};
  GPU_blend(GPU_BLEND_NONE);
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&pill, true, 0.0f, bed);

  GPU_blend(GPU_BLEND_ALPHA);
  fill_round(&pill, h * 0.5f, surface);
  fill_round(&dot, dot_r, state->status_busy ? accent : dim_dot);
  label_left(state->status_text,
             w * (float(AGENT_PILL_LABEL_X - AGENT_PILL_X) / float(AGENT_PILL_W)),
             h * 0.5f,
             AGENT_PILL_FONT * pill_u,
             text_dim);
  GPU_blend(GPU_BLEND_NONE);
}

void agent_ui_draw_island(const ARegion * /*region*/,
                          const AgentIslandLayout *layout,
                          const AgentIslandState *state)
{
  if (!layout->valid) {
    return;
  }

  const float u = layout->scale;

  const float surface[4] = AGENT_COL_SURFACE;
  const float border[4] = AGENT_COL_BORDER;
  const float card_top[4] = AGENT_COL_CARD_TOP;
  const float card_bottom[4] = AGENT_COL_CARD_BOTTOM;
  const float accent[4] = AGENT_COL_ACCENT;
  const float glyph[4] = AGENT_COL_GLYPH;
  const float text[4] = AGENT_COL_TEXT;
  const float strong[4] = AGENT_COL_TEXT_STRONG;
  const float text_dim[4] = AGENT_COL_TEXT_DIM;

  GPU_blend(GPU_BLEND_ALPHA);

  /* The status pill is NOT drawn here — it is its own always-on-top window
   * (see agent_ui_draw_status_pill). Drawing it in the island meant a band of
   * opaque black above the tab strip, because the bubble window composites
   * alpha as opaque. */

  /* --- Tab strip --- */
  draw_tab_strip(layout, state);

  /* --- Card --- */
  {
    /* Spent portion: the same hue at a fraction of its value, so the ring reads
     * as one strip that has been used up rather than two different borders. */
    const float border_spent[4] = {border[0] * 0.16f, border[1] * 0.16f,
                                   border[2] * 0.16f, 1.0f};
    draw_card_border_meter(&layout->card,
                           AGENT_CARD_RADIUS * u,
                           AGENT_CARD_BORDER * u,
                           border,
                           border_spent,
                           state->credits_remaining);
  }
  fill_round_gradient(&layout->card_fill,
                      AGENT_CARD_RADIUS * u,
                      card_top,
                      card_bottom,
                      layout->card_grad_a,
                      layout->card_grad_b);

  /* Card header row is tab-scoped: the chat's discs / session title / FAQs
   * belong to the Agent tab; other tabs title the card after themselves. */
  const bool agent_tab = layout->tabs[AGENT_TAB_AGENT].active;
  if (agent_tab) {
    /* Header buttons: an accent disc with a lighter glyph on top. */
    fill_round(&layout->hdr_history,
               BLI_rctf_size_x(&layout->hdr_history) * 0.5f,
               accent);
    agent_ui_icon_draw(AGENT_ICON_CLOCK, &layout->hdr_history, glyph, accent);

    fill_round(&layout->hdr_new_chat,
               BLI_rctf_size_x(&layout->hdr_new_chat) * 0.5f,
               accent);
    agent_ui_icon_draw(AGENT_ICON_PLUS, &layout->hdr_new_chat, glyph, accent);

    label_centre(state->title,
                 layout->hdr_title_cx,
                 layout->hdr_title_y,
                 AGENT_HDR_TITLE_FONT * u,
                 strong);
    label_right("FAQs",
                layout->hdr_faq.xmax,
                BLI_rctf_cent_y(&layout->hdr_faq),
                AGENT_HDR_FAQ_FONT * u,
                strong);
  }
  else {
    const char *tab_title = "";
    if (layout->tabs[AGENT_TAB_QUEUE].active) {
      tab_title = "Queue";
    }
    else if (layout->tabs[AGENT_TAB_3D].active) {
      tab_title = "3D";
    }
    else if (layout->tabs[AGENT_TAB_MEDIA].active) {
      tab_title = "Media";
    }
    else if (layout->tabs[AGENT_TAB_SPLAT].active) {
      tab_title = "Gaussian Splat";
    }
    else if (layout->tabs[AGENT_TAB_GENERATIONS].active) {
      tab_title = "My Generations";
    }
    label_centre(tab_title,
                 layout->hdr_title_cx,
                 layout->hdr_title_y,
                 AGENT_HDR_TITLE_FONT * u,
                 strong);
  }

  /* --- Inner panel --- */
  fill_round(&layout->panel, AGENT_PANEL_RADIUS * u, surface);

  /* Neither the prompt nor its placeholder is painted here — both belong to
   * the text button the bottom slab lays over the input line, which draws on
   * top of anything the painter puts in the same place. Painting one here as
   * well is what put TWO ghost texts in the card. */

  /* --- Chip row --- */
  draw_chip_row(layout, state);

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

}  // namespace blender
