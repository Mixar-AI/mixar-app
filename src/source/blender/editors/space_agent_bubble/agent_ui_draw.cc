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

#include "agent_ui_text.hh"
#include "UI_mixar.hh"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"

#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "ED_mixar_glass.hh"

#include "agent_bubble_intern.hh"
#include "agent_ui_draw.hh"
#include "agent_ui_draw_primitives.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_motion.hh"
#include "agent_ui_pill_cat.hh"
#include "agent_ui_pill_draft.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {


/* -------------------------------------------------------------------- */
/** \name Island
 * \{ */

void agent_ui_draw_status_pill(ARegion *region, const float width,
                               const float height,
                               const AgentIslandState *state)
{
  agent_ui_pill_draft_clear();
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
   * minimised bubble's whole identity — dim last-prompt preview + Mixie the
   * cat on a green gradient chip (Frame 1533210248.svg, mascot in
   * agent_ui_pill_cat.cc). When working (busy, delegated workers or active queue jobs), it
   * shows an animated activity dot and a fixed-width activity field on the
   * status label. Clicking it expands the
   * island; dragging it moves it (the pill gesture in
   * agent_bubble/ui/operators/bubble_header_drag_op.py). */
  if (w > h * 4.0f) {
    const float u = h / 85.0f; /* design pill is 85 artboard units tall */
    const bool is_working = mixie_cat_is_working(state->cat_activity) &&
                            (state->status_busy || state->status_active || state->queue_count > 0);
    const double now = BLI_time_now_seconds();
    const float pulse = is_working ?
                            (0.5f + 0.5f * float(std::sin(now * 3.2))) :
                            0.0f;

    rctf pill;
    pill.xmin = 0.0f;
    pill.xmax = w;
    pill.ymin = 0.0f;
    pill.ymax = h;
    /* Native frost owns the bed; both paths share the rounded light and rim. */
    if (agent_bubble_pill_bed_is_transparent()) {
      const float wash[4] = AGENT_COL_GLASS_WASH;
      agent_bubble_replace_frost_wash(&pill, wash);
      glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f, false, false, false);
    }
    else {
      glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f);
    }
    GPU_blend(GPU_BLEND_ALPHA);

    /* No extra rim here: the PILL row's own rim IS this stroke (white at
     * 0.14, the export's top-right-brightest edge), drawn by the glass pane
     * above. A second working outline used to stack a green highlight on
     * the capsule; working state now lives on the logo chip and the
     * activity dot. */

    /* Pill behind the logo, right-inset 10.5 units, 85x68. */
    rctf chip;
    chip.xmax = w - 10.5f * u;
    chip.xmin = chip.xmax - 85.0f * u;
    chip.ymin = h * 0.5f - 34.0f * u;
    chip.ymax = h * 0.5f + 34.0f * u;
    const float chip_a[4] = {
        0.125f + (is_working ? 0.05f * pulse : 0.0f),
        0.345f + (is_working ? 0.25f * pulse : 0.0f),
        0.212f + (is_working ? 0.15f * pulse : 0.0f),
        1.0f};
    const float chip_b[4] = {
        0.227f + (is_working ? 0.05f * pulse : 0.0f),
        0.518f + (is_working ? 0.35f * pulse : 0.0f),
        0.341f + (is_working ? 0.20f * pulse : 0.0f),
        1.0f};
    /* Pill behind the logo: right-inset 10.5 units, 85x68. Corner radius matches
     * the minimized bubble capsule (half-height pill radius, concentric with the
     * outer pill). */
    const float chip_r = (chip.ymax - chip.ymin) * 0.5f;
    const float chip_grad_a[2] = {chip.xmax - 7.0f * u, chip.ymax - 14.0f * u};
    const float chip_grad_b[2] = {chip.xmin + 2.0f * u, chip.ymin + 30.0f * u};
    fill_round_gradient(&chip, chip_r, chip_a, chip_b, chip_grad_a, chip_grad_b);

    const MixieCatPose cat_pose = agent_ui_cat_motion_sample(
        region, state->cat_activity, now, state->cat_scene,
        std::min(BLI_rctf_size_x(&chip), BLI_rctf_size_y(&chip)) - 2.0f,
        state->cat_catch);
    agent_ui_draw_pill_cat(&chip, cat_pose, state->cat_activity);

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
    const float text_size = agent_ui_body_font_size();
    const float text_x = 28.0f * u;

    if (state->scribble_armed) {
      /* Sketch: the pill is where typing over the viewport lands — the draft,
       * a blinking caret and a Voice button (the window is also a little
       * larger while armed; see pill_rest_size in space_agent_bubble.cc). */
      agent_ui_draw_pill_draft(*state, text_x, chip.xmin - 12.0f * u, h, text_size, u);
    }
    else if (is_working) {
      /* Pulsing indicator dot on the left. */
      const float dot_cx = text_x + 5.0f * u;
      const float dot_cy = h * 0.5f;
      const float dot_r = 4.5f * u;

      /* Ripple ring around the dot. */
      const float rip_r = dot_r + 3.5f * u * pulse;
      rctf ripple;
      ripple.xmin = dot_cx - rip_r;
      ripple.xmax = dot_cx + rip_r;
      ripple.ymin = dot_cy - rip_r;
      ripple.ymax = dot_cy + rip_r;
      float rip_col[4];
      ui::mixar_theme_color_f(ui::MixarThemeSlot::AgentBorder, rip_col);
      rip_col[3] = (1.0f - pulse) * 0.45f;
      fill_round(&ripple, rip_r, rip_col);

      /* Solid active dot. */
      rctf dot;
      dot.xmin = dot_cx - dot_r;
      dot.xmax = dot_cx + dot_r;
      dot.ymin = dot_cy - dot_r;
      dot.ymax = dot_cy + dot_r;
      float dot_col[4];
      ui::mixar_theme_color_f(ui::MixarThemeSlot::AgentBorder, dot_col);
      dot_col[3] = 0.95f;
      fill_round(&dot, dot_r, dot_col);

      /* Trailing dots animation: 0, 1, 2, 3 dots on a 1.6s cycle. */
      const int dot_count = int(fmod(now * 2.5, 4.0));
      /* Fixed 3-slot activity field. U+00B7 and U+0020 both advance 400/2000 em
       * in Manrope (BLF_default), and BLF measures the sum of advances, so the
       * field's width never changes and the preview after it cannot shift. A
       * '.' is 440 and WOULD shift it; U+2007/U+2008 are not in Manrope at all. */
      char dots[3 * 2 + 1];
      char *d = dots;
      for (int i = 0; i < 3; i++) {
        if (i < dot_count) {
          *d++ = '\xc2';
          *d++ = '\xb7';
        }
        else {
          *d++ = ' ';
        }
      }
      *d = '\0';

      const char *base_status = mixie_cat_activity_name(state->cat_activity);
      char label[160];
      if (state->last_prompt[0] != '\0') {
        SNPRINTF(label, "%s%s · %s", base_status, dots, preview);
      }
      else {
        SNPRINTF(label, "%s%s", base_status, dots);
      }

      const float label_x = dot_cx + dot_r + 10.0f * u;
      const float text_max_w = chip.xmin - 16.0f * u - label_x;
      if (text_width(label, text_size) > text_max_w) {
        size_t len = strlen(label);
        while (len > 1) {
          label[--len] = '\0';
          char probe[164];
          SNPRINTF(probe, "%s...", label);
          if (text_width(probe, text_size) <= text_max_w) {
            BLI_strncpy(label, probe, sizeof(label));
            break;
          }
        }
      }
      const float work_col[4] = {0.95f, 0.96f, 0.98f, 1.0f};
      label_left(label, label_x, h * 0.5f, text_size, work_col);
    }
    else {
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
    }

    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  agent_ui_pill_cat_clear();

  MIXAR_THEME_LOAD(accent, AgentAccent);
  const float dim_dot[4] = {0.076f, 0.219f, 0.132f, 1.0f};
  MIXAR_THEME_LOAD(text_dim, TextSecondary);

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

  /* Paint the WHOLE rect before the capsule. The pill window's buffers
   * otherwise carry leftover pixels that flash the bare backdrop. Frost
   * replaces a premultiplied wash; the shared shader adds its finishing layers. */
  if (agent_bubble_pill_bed_is_transparent()) {
    const float wash[4] = AGENT_COL_GLASS_WASH;
    agent_bubble_replace_frost_wash(&pill, wash);
    glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f, false, false, false);
  }
  else {
    const float bed[4] = {0.02f, 0.02f, 0.02f, 1.0f};
    GPU_blend(GPU_BLEND_NONE);
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv(&pill, true, 0.0f, bed);
    GPU_blend(GPU_BLEND_ALPHA);
    glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f);
  }
  GPU_blend(GPU_BLEND_ALPHA);
  fill_round(&dot, dot_r, (state->status_busy || state->status_active) ? accent : dim_dot);
  const float text_x = w * (float(AGENT_PILL_LABEL_X - AGENT_PILL_X) / float(AGENT_PILL_W));
  const float text_size = agent_ui_body_font_size();
  const std::string status_label = ui::mixar_fit_text(
      state->status_text, std::max(0.0f, w - text_x - 12.0f * pill_u), text_size);
  label_left(status_label.c_str(), text_x, h * 0.5f, text_size, text_dim);
  GPU_blend(GPU_BLEND_NONE);
}

void agent_ui_draw_island(ARegion *region,
                          const AgentIslandLayout *layout,
                          const AgentIslandState *state)
{
  agent_ui_motion_begin(region);
  if (!layout->valid) {
    agent_ui_motion_end(region);
    return;
  }

  const float u = layout->scale;

  MIXAR_THEME_LOAD(surface, Canvas);
  const ui::MixarGlassTokens glass = ui::mixar_glass_tokens(ui::MIXAR_GLASS_PILL);
  const float *border = glass.rim;
  MIXAR_THEME_LOAD(accent, AgentAccent);
  MIXAR_THEME_LOAD(glyph, Glyph);
  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(strong, TextStrong);
  MIXAR_THEME_LOAD(text_dim, TextSecondary);

  GPU_blend(GPU_BLEND_ALPHA);

  /* The status pill is NOT drawn here — it is its own always-on-top window
   * (see agent_ui_draw_status_pill). Drawing it in the island meant a band of
   * opaque black above the tab strip, because the bubble window composites
   * alpha as opaque. */

  /* --- Tab strip --- (none on the Scribble pad; its rects are empty) */
  if (!layout->pad) {
    agent_ui_draw_tab_strip(region, layout, state);
  }

  /* --- Card --- */
  {
    /* Preserve the credit indication in the pill's quiet white rim. Lower the
     * spent alpha rather than putting an opaque dark ring over native frost. */
    const float border_spent[4] = {border[0], border[1], border[2], border[3] * 0.25f};
    draw_card_border_meter(&layout->card,
                           AGENT_CARD_RADIUS * u,
                           glass.rim_width,
                           border,
                           border_spent,
                           state->credits_remaining);
  }
  /* Expanding changes the shape, not the material. The credit meter already
   * draws PILL's rim, so keep only its sheen here to avoid a doubled edge. */
  glass_fill_round(&layout->card_fill,
                   ui::MIXAR_GLASS_PILL,
                   (AGENT_CARD_RADIUS - AGENT_CARD_BORDER) * u,
                   /*shadow=*/false,
                   /*specular=*/false,
                   /*tint=*/!agent_bubble_island_bed_is_transparent(),
                   /*rim=*/false);

  /* Session actions stay available without repeating the active tab title. */
  const bool agent_tab = layout->tabs[AGENT_TAB_AGENT].active;
  if (agent_tab) {
    /* Header buttons: an accent disc with a lighter glyph on top. */
    float history_fill[4], new_chat_fill[4], checkpoints_fill[4];
    agent_ui_motion_color(accent, accent,
                          agent_ui_motion_sample(region, AgentIslandControl::History, layout->hdr_history),
                          history_fill);
    agent_ui_motion_color(accent, accent,
                          agent_ui_motion_sample(region, AgentIslandControl::NewChat, layout->hdr_new_chat),
                          new_chat_fill);
    agent_ui_motion_color(accent, accent,
                          agent_ui_motion_sample(region, AgentIslandControl::Checkpoints, layout->hdr_checkpoints),
                          checkpoints_fill);
    fill_round(&layout->hdr_history,
               BLI_rctf_size_x(&layout->hdr_history) * 0.5f,
               history_fill);
    agent_ui_header_icon_draw(AGENT_ICON_CLOCK, &layout->hdr_history, glyph, history_fill);

    fill_round(&layout->hdr_new_chat,
               BLI_rctf_size_x(&layout->hdr_new_chat) * 0.5f,
               new_chat_fill);
    agent_ui_header_icon_draw(AGENT_ICON_PLUS, &layout->hdr_new_chat, glyph, new_chat_fill);

    /* Turn checkpoints: same disc, a counter-clockwise arrow glyph. Runs
     * mixie_chat.show_checkpoints (space_mixie_chat/ui/operators/
     * checkpoint_ops.py), the native card — the island has no Python header
     * to host a button. */
    fill_round(&layout->hdr_checkpoints,
               BLI_rctf_size_x(&layout->hdr_checkpoints) * 0.5f,
               checkpoints_fill);
    agent_ui_header_icon_draw(AGENT_ICON_RESTORE, &layout->hdr_checkpoints, glyph, checkpoints_fill);

    agent_ui_draw_handwriting_control(region, layout, state);

    if (state->ink_visible) {
      /* Handwriting text output window over the new chat topbar */
      const float left_limit = layout->hdr_rules.xmax + 16.0f * u;
      const float right_limit = layout->hdr_handwriting.xmin - 16.0f * u;
      const float max_w = right_limit - left_limit;
      const float cx = layout->hdr_title_cx;
      const float cy = layout->hdr_title_y;
      const float win_h = 42.0f * u;

      char disp[512];
      BLI_strncpy(disp,
                  state->input_text[0] ? state->input_text : "Write your prompt here...",
                  sizeof(disp));
      for (char *c = disp; *c; c++) {
        if (*c == '\n' || *c == '\r') {
          *c = ' ';
        }
      }

      const float font_size = 18.0f * agent_ui_text_unit();
      const float text_w = text_width(disp, font_size);
      const float pad_x = 18.0f * u;
      const float win_w = std::min(text_w + pad_x * 2.0f, std::max(0.0f, max_w));

      rctf text_win;
      text_win.xmin = cx - win_w * 0.5f;
      text_win.xmax = cx + win_w * 0.5f;
      text_win.ymin = cy - win_h * 0.5f;
      text_win.ymax = cy + win_h * 0.5f;

      const float win_bg[4] = {0.05f, 0.05f, 0.07f, 0.90f};
      const float win_border[4] = {0.20f, 0.52f, 0.32f, 0.70f};
      fill_round(&text_win, 14.0f * u, win_bg);
      outline_round(&text_win, 14.0f * u, win_border);

      const float max_text_w = win_w - pad_x * 2.0f;
      if (text_width(disp, font_size) > max_text_w) {
        size_t len = strlen(disp);
        while (len > 1) {
          disp[--len] = '\0';
          char probe[516];
          SNPRINTF(probe, "%s...", disp);
          if (text_width(probe, font_size) <= max_text_w) {
            BLI_strncpy(disp, probe, sizeof(disp));
            break;
          }
        }
      }

      const float col_active[4] = {0.96f, 0.97f, 0.98f, 1.0f};
      const float col_dim[4] = {0.50f, 0.50f, 0.50f, 0.80f};
      const float *text_col = state->input_text[0] ? col_active : col_dim;
      label_centre(disp, cx, cy, font_size, text_col);
    }
  }

  /* --- Inner panel --- */
  /* Opaque #121212 here is what made frost read as a solid slab: empty
   * TOOLS paints the full island, and dest-over cannot lower dest A=1. */
  if (!agent_bubble_island_bed_is_transparent()) {
    fill_round(&layout->panel, AGENT_PANEL_RADIUS * u, surface);
  }

  /* Neither the prompt nor its placeholder is painted here — both belong to
   * the text button the bottom slab lays over the input line, which draws on
   * top of anything the painter puts in the same place. Painting one here as
   * well is what put TWO ghost texts in the card. */

  /* --- Chip row --- */
  agent_ui_draw_chip_row(region, layout, state);
  agent_ui_motion_end(region);

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

}  // namespace blender
