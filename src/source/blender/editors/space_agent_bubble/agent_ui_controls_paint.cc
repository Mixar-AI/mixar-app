/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "agent_ui_text.hh"

#include <algorithm>

#include "BLI_string.h"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"

#include "agent_bubble_intern.hh"
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
float group_left(const rctf &rect, const char *label, float size, float leading, float trailing = 0)
{
  return BLI_rctf_cent_x(&rect) -
         (leading + ui::mixar_text_width(label, size) + trailing) * 0.5f;
}
void chip_content(const rctf &rect, AgentIcon glyph, const char *label,
                  float size, float edge, float gap, const float color[4], const float fill[4])
{
  const std::string fitted = ui::mixar_fit_text(
      label, std::max(0.0f, BLI_rctf_size_x(&rect) - edge - gap * 3.0f), size);
  const float x = group_left(rect, fitted.c_str(), size, edge + gap);
  const float cy = BLI_rctf_cent_y(&rect);
  rctf icon{x, x + edge, cy - edge * 0.5f, cy + edge * 0.5f};
  agent_ui_icon_draw(glyph, &icon, color, fill);
  label_left(fitted.c_str(), x + edge + gap, cy, size, color);
}
}  // namespace

/* -------------------------------------------------------------------- */
/** \name Tab strip
 * \{ */

/** #AGENT_ICON_COUNT means the tab carries NO mark. */
const AgentIcon g_tab_icons[AGENT_TAB_COUNT] = {
    AGENT_ICON_AGENT,
    AGENT_ICON_MESH,
    AGENT_ICON_IMAGE,
    AGENT_ICON_VIDEO,
    AGENT_ICON_SPLAT,
    AGENT_ICON_COUNT,
    AGENT_ICON_COUNT,
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

  if (!agent_bubble_island_bed_is_transparent()) {
    fill_round(&layout->strip, AGENT_STRIP_RADIUS * u, surface);
  }

  /* Resizing changes geometry; typography follows interface scale and DPI. */
  const float label_size = AGENT_TAB_FONT * agent_ui_text_unit();

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

    const bool has_count = queue && state->queue_count > 0;
    const bool has_icon = g_tab_icons[i] != AGENT_ICON_COUNT;
    const bool has_badge = i == AGENT_TAB_SPLAT && state->splat_is_new;
    const float gap = AGENT_TAB_ICON_GAP * u;
    const float leading = has_count ? BLI_rctf_size_x(&layout->queue_count) + gap :
                          has_icon ? AGENT_TAB_ICON * u + gap : 0.0f;
    const float trailing = has_badge ? BLI_rctf_size_x(&layout->new_badge) + gap : 0.0f;
    const std::string label = ui::mixar_fit_text(
        agent_ui_tab_label(AgentTabId(i)),
        std::max(0.0f, BLI_rctf_size_x(&tab.pill) - leading - trailing - gap * 2.0f),
        label_size);
    const float start = group_left(tab.pill, label.c_str(), label_size, leading, trailing);
    rctf icon = tab.icon;
    BLI_rctf_translate(&icon, start - icon.xmin, cy - BLI_rctf_cent_y(&icon));
    rctf count_rect = layout->queue_count;
    BLI_rctf_translate(&count_rect, start - count_rect.xmin, cy - BLI_rctf_cent_y(&count_rect));
    rctf badge = layout->new_badge;
    const float badge_x = start + leading + ui::mixar_text_width(label.c_str(), label_size) + gap;
    BLI_rctf_translate(&badge, badge_x - badge.xmin, cy - BLI_rctf_cent_y(&badge));

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
        fill_round(&count_rect, AGENT_QUEUE_COUNT_RADIUS * u, queue_count);
        label_centre(count,
                     BLI_rctf_cent_x(&count_rect),
                     BLI_rctf_cent_y(&count_rect),
                     AGENT_NEW_BADGE_FONT * agent_ui_text_unit(),
                     text);
      }
    }
    else if (g_tab_icons[i] != AGENT_ICON_COUNT) {
      /* Backdrop is this pill's own fill — the active pill is #183E25, the
       * rest sit directly on the strip. */
      agent_ui_icon_draw(g_tab_icons[i], &icon, label_col, pill_bg);
    }

    /* A tab with nothing in its icon slot centres its label; leaving it at
     * the icon offset would hang the word off to the right of an empty pill.
     * The Queue pill does the same once its count chip is gone. */
    const bool centred = (g_tab_icons[i] == AGENT_ICON_COUNT) &&
                         (i != AGENT_TAB_QUEUE || state->queue_count <= 0);
    if (centred) {
      label_centre(label.c_str(), BLI_rctf_cent_x(&tab.pill), cy, label_size, label_col);
    }
    else {
      label_left(label.c_str(), start + leading, cy, label_size, label_col);
    }

    if (i == AGENT_TAB_SPLAT && state->splat_is_new) {
      fill_round(&badge, AGENT_NEW_BADGE_RADIUS * u, accent);
      label_centre("NEW",
                   BLI_rctf_cent_x(&badge),
                   BLI_rctf_cent_y(&badge),
                   AGENT_NEW_BADGE_FONT * agent_ui_text_unit(),
                   strong);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Chip row
 * \{ */

void agent_ui_draw_handwriting_control(ARegion *region,
                                       const AgentIslandLayout *layout,
                                       const AgentIslandState *state)
{
  /* Paint the Rules action alongside the other header controls. Native
   * uiBlocks own its hit rectangle and tooltip, just like Checkpoints. */
  const float rules_accent[4] = AGENT_COL_ACCENT;
  const float glyph[4] = AGENT_COL_GLYPH;
  float rules_fill[4];
  agent_ui_motion_color(rules_accent, rules_accent,
                        agent_ui_motion_sample(region, AgentIslandControl::Rules,
                                               layout->hdr_rules), rules_fill);
  fill_round(&layout->hdr_rules, BLI_rctf_size_x(&layout->hdr_rules) * 0.5f, rules_fill);
  agent_ui_icon_draw(AGENT_ICON_RULES, &layout->hdr_rules, glyph, rules_fill);

  if (!state->handwriting_available) {
    return;
  }
  const float chip[4] = AGENT_COL_CHIP;
  const float accent[4] = AGENT_COL_ACCENT;
  const float text[4] = AGENT_COL_TEXT;
  float fill[4];
  agent_ui_motion_color(chip, accent,
                        agent_ui_motion_sample(region, AgentIslandControl::Handwriting,
                                               layout->hdr_handwriting, state->ink_visible),
                        fill);
  fill_round(&layout->hdr_handwriting, AGENT_CHIP_RADIUS * layout->scale, fill);
  label_centre(state->ink_visible ? "Type instead" : "Handwriting",
               BLI_rctf_cent_x(&layout->hdr_handwriting),
               BLI_rctf_cent_y(&layout->hdr_handwriting),
               AGENT_CHIP_FONT * agent_ui_text_unit(), text);
}

void agent_ui_draw_chip_row(ARegion *region,
                            const AgentIslandLayout *layout,
                            const AgentIslandState *state)
{
  const float u = layout->scale;
  const float chip[4] = AGENT_COL_CHIP;
  const float generate[4] = AGENT_COL_GENERATE;
  const float text[4] = AGENT_COL_TEXT;

  /* Keep text fixed while the measured group stays centered in live geometry. */
  const float size = AGENT_CHIP_FONT * agent_ui_text_unit();
  const float radius = AGENT_CHIP_RADIUS * u;
  const float pad = AGENT_CHIP_PAD_X * u;
  const float icon_gap = AGENT_CHIP_ICON_GAP * u;
  const float icon_edge = AGENT_CHIP_ICON * u;

  /* Composer chips belong to the Agent tab; other tabs fill the card with
   * their own content (Queue rows, later panes). */
  if (layout->tabs[AGENT_TAB_AGENT].active == false) {
    return;
  }

  /* Center the full Upload Reference label together with its picture mark. */
  float upload_fill[4];
  agent_ui_motion_color(
      chip,
      chip,
      agent_ui_motion_sample(region, AgentIslandControl::Upload, layout->chip_upload),
      upload_fill);
  fill_round(&layout->chip_upload, radius, upload_fill);
  chip_content(layout->chip_upload, AGENT_ICON_IMAGE,
               layout->compact_reference ? "Reference" : "Upload Reference",
               size, icon_edge, icon_gap, text, upload_fill);

  /* Sketch. Lit in the accent while the viewport freeze is up, and
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
    char label[32];
    if (state->mark_count > 0) {
      SNPRINTF(label, "Sketch · %d", state->mark_count);
    }
    else {
      BLI_strncpy(label, "Sketch", sizeof(label));
    }
    chip_content(layout->chip_scribble, AGENT_ICON_PEN, label,
                 size, icon_edge, icon_gap, text, scribble_fill);

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
    chip_content(layout->chip_voice, AGENT_ICON_MIC,
                 state->voice_listening ? state->voice_status : "Voice",
                 size, icon_edge, icon_gap, text, voice_fill);
  }

  /* Auto, right of Voice: an "Auto" label and a sliding ON/OFF switch. The
   * chip bed stays neutral (hover/press only) — the switch carries the state:
   * its track blends to the accent and the thumb rides `feedback.selected`,
   * so a click slides it across on the shared Zen timing instead of
   * jumping. The label brightens with it. */
  {
    const float accent[4] = AGENT_COL_ACCENT;
    const float track_off[4] = AGENT_COL_CHIP_ACTIVE;
    const float text_dim[4] = AGENT_COL_TEXT_DIM;
    const AgentIslandFeedback feedback = agent_ui_motion_sample(
        region, AgentIslandControl::Auto, layout->chip_auto, state->auto_mode);
    float auto_fill[4];
    agent_ui_motion_color(chip, chip, feedback, auto_fill);
    fill_round(&layout->chip_auto, radius, auto_fill);

    const float cy = BLI_rctf_cent_y(&layout->chip_auto);
    const float switch_w = AGENT_SWITCH_W * u;
    const float switch_h = AGENT_SWITCH_H * u;
    const float inset = AGENT_SWITCH_INSET * u;
    const rctf track{layout->chip_auto.xmax - pad - switch_w,
                     layout->chip_auto.xmax - pad,
                     cy - switch_h * 0.5f,
                     cy + switch_h * 0.5f};
    float track_fill[4];
    agent_ui_motion_color(track_off, accent, {0.0f, 0.0f, feedback.selected}, track_fill);
    fill_round(&track, switch_h * 0.5f, track_fill);
    const float thumb_d = switch_h - inset * 2.0f;
    const float thumb_x = track.xmin + inset +
                          (switch_w - thumb_d - inset * 2.0f) * feedback.selected;
    const rctf thumb{thumb_x, thumb_x + thumb_d, track.ymin + inset, track.ymax - inset};
    fill_round(&thumb, thumb_d * 0.5f, text);

    float label_col[4];
    agent_ui_motion_color(text_dim, text, {0.0f, 0.0f, feedback.selected}, label_col);
    const std::string label = ui::mixar_fit_text(
        "Auto",
        std::max(0.0f, track.xmin - icon_gap - (layout->chip_auto.xmin + pad)),
        size);
    label_left(label.c_str(), layout->chip_auto.xmin + pad, cy, size, label_col);
  }

  /* Model, right of Auto: which hosted model the agent runs on. The label is
   * the Python half's WindowManager mirror — this only reads it. An empty
   * mirror still reads "Model" so the control is discoverable before a pick
   * has been made. While a BYOK key overrides the hosted pick the chip is
   * inert, and says so by dimming its ink (the native button carries the
   * explanation as its disabled hint).
   *
   * The row is width-budgeted, so the chip may have been stepped down to
   * label-only or icon-only, or dropped entirely — see
   * agent_ui_layout_fit_controls. An empty rect means dropped. */
  if (state->model_available && BLI_rctf_size_x(&layout->chip_model) > 0.0f) {
    const float text_dim[4] = AGENT_COL_TEXT_DIM;
    const float *ink = state->model_byok_active ? text_dim : text;
    float model_fill[4];
    agent_ui_motion_color(
        chip,
        chip,
        agent_ui_motion_sample(region, AgentIslandControl::Model, layout->chip_model),
        model_fill);
    fill_round(&layout->chip_model, radius, model_fill);

    const float cy = BLI_rctf_cent_y(&layout->chip_model);
    const char *model_label = state->model_label[0] ? state->model_label : "Model";
    if (layout->model_form == AgentModelChipForm::Icon) {
      const float ccx = BLI_rctf_cent_x(&layout->chip_model);
      const rctf glyph{ccx - icon_edge * 0.5f,
                       ccx + icon_edge * 0.5f,
                       cy - icon_edge * 0.5f,
                       cy + icon_edge * 0.5f};
      agent_ui_icon_draw(AGENT_ICON_STAR, &glyph, ink, model_fill);
    }
    else {
      /* Same centred icon+label group every other chip uses; the chevron,
       * when it survives the budget, is carved off the right first. */
      rctf body = layout->chip_model;
      if (layout->model_form == AgentModelChipForm::Full) {
        body.xmax -= icon_edge * 0.7f + icon_gap;
      }
      chip_content(body, AGENT_ICON_STAR, model_label, size, icon_edge, icon_gap, ink, model_fill);
      if (layout->model_form == AgentModelChipForm::Full) {
        rctf chevron = layout->chip_model;
        chevron.xmax -= pad;
        chevron.xmin = chevron.xmax - icon_edge * 0.7f;
        chevron.ymin = cy - icon_edge * 0.35f;
        chevron.ymax = cy + icon_edge * 0.35f;
        agent_ui_icon_draw(AGENT_ICON_CHEVRON_DOWN, &chevron, ink, model_fill);
      }
    }
  }

  /* Send. */
  float generate_fill[4];
  agent_ui_motion_color(
      generate,
      generate,
      agent_ui_motion_sample(region, AgentIslandControl::Generate, layout->btn_generate),
      generate_fill);
  fill_round(&layout->btn_generate, radius, generate_fill);
  label_centre(state->stop_visible ? "Stop" : "Send",
               BLI_rctf_cent_x(&layout->btn_generate),
               BLI_rctf_cent_y(&layout->btn_generate),
               size,
               text);
}

/** \} */

}  // namespace blender
