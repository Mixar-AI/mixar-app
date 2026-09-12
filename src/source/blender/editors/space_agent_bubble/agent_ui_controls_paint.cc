/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>

#include "BLI_string.h"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"

#include "agent_ui_draw.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_motion.hh"
#include "agent_ui_theme.hh"

namespace blender {
namespace {
void fill_round(const rctf *rect, const float radius, const float color[4])
{
  ui::mixar_fill_round(*rect, radius, color);
}
void outline_round(const rctf *rect, const float radius, const float color[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(rect, false, radius, color);
}
void label_left(const char *text, float x, float cy, float size, const float color[4])
{
  ui::mixar_label_left(text, x, cy, size, color);
}
void label_centre(const char *text, float x, float cy, float size, const float color[4])
{
  ui::mixar_label_center(text, x, cy, {size}, color);
}
}  // namespace

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

void agent_ui_draw_tab_strip(ARegion *region,
                             const AgentIslandLayout *layout,
                             const AgentIslandState *state)
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

    const AgentIslandFeedback feedback = agent_ui_motion_sample(
        region, AgentIslandControl(i), tab.pill, tab.active);
    float pill_bg[4], label_col[4], tab_outline[4];
    const bool queue = i == AGENT_TAB_QUEUE;
    agent_ui_motion_color(queue ? queue_fill : surface, active_fill, feedback, pill_bg);
    agent_ui_motion_color(
        queue ? strong : text_dim, strong, {0.0f, 0.0f, feedback.selected}, label_col);
    std::copy_n(outline, 4, tab_outline);
    tab_outline[3] *= 1.0f - feedback.selected;
    fill_round(&tab.pill, AGENT_TAB_RADIUS * u, pill_bg);
    outline_round(&tab.pill, AGENT_TAB_RADIUS * u, tab_outline);

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
      agent_ui_icon_draw(g_tabs[i].icon, &tab.icon, label_col, pill_bg);
    }

    /* A tab with nothing in its icon slot centres its label; leaving it at
     * the icon offset would hang the word off to the right of an empty pill.
     * The Queue pill does the same once its count chip is gone. */
    const bool centred = (g_tabs[i].icon == AGENT_ICON_COUNT) &&
                         (i != AGENT_TAB_QUEUE || state->queue_count <= 0);
    if (centred) {
      label_centre(g_tabs[i].label, BLI_rctf_cent_x(&tab.pill), cy, label_size, label_col);
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

void agent_ui_draw_chip_row(ARegion *region,
                            const AgentIslandLayout *layout,
                            const AgentIslandState *state)
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
  float upload_fill[4];
  agent_ui_motion_color(
      chip,
      chip,
      agent_ui_motion_sample(region, AgentIslandControl::Upload, layout->chip_upload),
      upload_fill);
  fill_round(&layout->chip_upload, radius, upload_fill);
  {
    rctf icon = layout->chip_upload;
    icon.xmin += pad;
    icon.xmax = icon.xmin + icon_edge;
    const float cy = BLI_rctf_cent_y(&layout->chip_upload);
    icon.ymin = cy - icon_edge * 0.5f;
    icon.ymax = cy + icon_edge * 0.5f;
    agent_ui_icon_draw(AGENT_ICON_IMAGE, &icon, text, upload_fill);
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
    float scribble_fill[4];
    agent_ui_motion_color(
        chip,
        accent,
        agent_ui_motion_sample(
            region, AgentIslandControl::Scribble, layout->chip_scribble, state->scribble_armed),
        scribble_fill);
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
      float reading_fill[4];
      agent_ui_motion_color(
          chip,
          chip,
          agent_ui_motion_sample(region, AgentIslandControl::Reading, layout->chip_reading),
          reading_fill);
      fill_round(&layout->chip_reading, radius, reading_fill);
      const float cy = BLI_rctf_cent_y(&layout->chip_reading);
      const char *reading = state->mark_intent[0] ? state->mark_intent : "Auto";
      label_left(reading, layout->chip_reading.xmin + pad, cy, size, text);
      rctf chevron = layout->chip_reading;
      chevron.xmax -= pad;
      chevron.xmin = chevron.xmax - icon_edge * 0.7f;
      chevron.ymin = cy - icon_edge * 0.35f;
      chevron.ymax = cy + icon_edge * 0.35f;
      agent_ui_icon_draw(AGENT_ICON_CHEVRON_DOWN, &chevron, text, reading_fill);

      if (!state->scribble_armed) {
        float clear_fill[4];
        agent_ui_motion_color(
            chip,
            chip,
            agent_ui_motion_sample(region, AgentIslandControl::Clear, layout->chip_clear),
            clear_fill);
        fill_round(&layout->chip_clear, radius, clear_fill);
        rctf cross = layout->chip_clear;
        const float ccx = BLI_rctf_cent_x(&cross);
        cross.xmin = ccx - icon_edge * 0.5f;
        cross.xmax = ccx + icon_edge * 0.5f;
        cross.ymin = cy - icon_edge * 0.5f;
        cross.ymax = cy + icon_edge * 0.5f;
        agent_ui_icon_draw(AGENT_ICON_CROSS, &cross, text, clear_fill);
      }
    }
  }

  /* Voice, right of Scribble: lit in the accent while a dictation session is
   * up. Only drawn when the toggle exists (see AgentIslandState). */
  if (state->voice_available) {
    const float accent[4] = AGENT_COL_ACCENT;
    float voice_fill[4];
    agent_ui_motion_color(
        chip,
        accent,
        agent_ui_motion_sample(
            region, AgentIslandControl::Voice, layout->chip_voice, state->voice_listening),
        voice_fill);
    fill_round(&layout->chip_voice, radius, voice_fill);
    rctf icon = layout->chip_voice;
    icon.xmin += pad;
    icon.xmax = icon.xmin + icon_edge;
    const float cy = BLI_rctf_cent_y(&layout->chip_voice);
    icon.ymin = cy - icon_edge * 0.5f;
    icon.ymax = cy + icon_edge * 0.5f;
    agent_ui_icon_draw(AGENT_ICON_MIC, &icon, text, voice_fill);
    label_left(
        state->voice_listening ? "Listening" : "Voice", icon.xmax + icon_gap, cy, size, text);
  }

  /* Generate. */
  float generate_fill[4];
  agent_ui_motion_color(
      generate,
      generate,
      agent_ui_motion_sample(region, AgentIslandControl::Generate, layout->btn_generate),
      generate_fill);
  fill_round(&layout->btn_generate, radius, generate_fill);
  label_centre(state->status_busy ? "Stop" : "Generate",
               BLI_rctf_cent_x(&layout->btn_generate),
               BLI_rctf_cent_y(&layout->btn_generate),
               size,
               text);
}

/** \} */

}  // namespace blender
