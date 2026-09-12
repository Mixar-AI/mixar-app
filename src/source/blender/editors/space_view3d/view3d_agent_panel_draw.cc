/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Parallel Agents panel painting: one dark rounded card per agent, carrying a
 * status dot, the agent's name, its task and an elapsed clock.
 *
 * Pure painting — the rects come from `view3d_agent_panel_layout_cards`, which
 * has already applied the scroll offset and the slide-in animation. Nothing
 * here re-derives geometry, and nothing here resizes the region: a draw pass
 * has this region's framebuffer bound and is iterating `area->regionbase`
 * (the Agent Bubble footer crash class).
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_time.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "../space_agent_bubble/agent_ui_pill_cat.hh"
#include "view3d_agent_panel.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* The reference design's language: a pill whose green washes in from the left
 * behind the avatar and falls away to near-black under the controls. */
constexpr float CARD_GREEN[4] = {0.106f, 0.478f, 0.243f, 0.96f};
constexpr float CARD_DARK[4] = {0.043f, 0.055f, 0.047f, 0.94f};
constexpr float CARD_BORDER[4] = {0.180f, 0.478f, 0.278f, 0.55f};
constexpr float CARD_BORDER_RUNNING[4] = {0.220f, 0.760f, 0.400f, 0.75f};

constexpr float TEXT_NAME[4] = {0.94f, 0.96f, 0.94f, 1.0f};
constexpr float GLYPH[4] = {0.80f, 0.86f, 0.82f, 1.0f};
constexpr float GLYPH_DONE[4] = {0.36f, 0.86f, 0.50f, 1.0f};
constexpr float GLYPH_FAILED[4] = {0.90f, 0.42f, 0.38f, 1.0f};

/* The reference design carries no status text on a card: the outcome is the
 * right-hand glyph (a dismiss cross while the agent works, a check or a red
 * cross once it settles) and the pill's own green wash. The elapsed clock the
 * mirror keeps (`started_at`/`ended_at`/`seen_running_at`) is deliberately not
 * drawn here — it stays available for a surface that has room for it. */

void with_alpha(const float src[4], const float alpha, float r_out[4])
{
  r_out[0] = src[0];
  r_out[1] = src[1];
  r_out[2] = src[2];
  r_out[3] = src[3] * alpha;
}

rctf to_rctf(const rcti &r)
{
  rctf out;
  out.xmin = float(r.xmin);
  out.xmax = float(r.xmax + 1);
  out.ymin = float(r.ymin);
  out.ymax = float(r.ymax + 1);
  return out;
}

/** Draw `text` at `x`, eliding it with a trailing "…" if it would run past
 * `max_width`. `BLF_clipping` truncates with no ellipsis at all, which reads
 * as a typo rather than as elision (the same trap the profile card documents). */
void draw_elided(const int font_id,
                 const char *text,
                 const float x,
                 const float baseline_y,
                 const float max_width,
                 const float color[4])
{
  if (!text || text[0] == '\0' || max_width <= 0.0f) {
    return;
  }
  BLF_color4fv(font_id, color);

  const size_t len = strlen(text);
  if (BLF_width(font_id, text, len) <= max_width) {
    BLF_position(font_id, x, baseline_y, 0.0f);
    BLF_draw(font_id, text, len);
    return;
  }

  /* `BLF_width_to_strlen` respects UTF-8 boundaries, so the cut can never
   * land inside a multi-byte character. */
  const float ellipsis_w = BLF_width(font_id, "…", strlen("…"));
  float measured = 0.0f;
  const size_t fit = BLF_width_to_strlen(
      font_id, text, len, std::max(max_width - ellipsis_w, 0.0f), &measured);

  char buf[AGENT_PANEL_TASK_BUF + 8];
  const size_t take = std::min(fit, sizeof(buf) - strlen("…") - 1);
  memcpy(buf, text, take);
  buf[take] = '\0';
  BLI_strncat(buf, "…", sizeof(buf));

  BLF_position(font_id, x, baseline_y, 0.0f);
  BLF_draw(font_id, buf, strlen(buf));
}

void draw_card(const AgentPanelCard &card, const float alpha, const double now)
{
  const float scale = UI_SCALE_FAC;
  const bool running = card.status == AgentCardStatus::Running;
  const rctf rect = to_rctf(card.rect);

  /* Horizontal gradient: `shade_dir <= 0` shades along x and the shader mixes
   * `inner2 -> inner1` across it, so inner2 is the LEFT end. A running agent's
   * green breathes; a settled one is still. */
  float wash = 1.0f;
  if (running) {
    wash = 0.78f + 0.22f * (0.5f + 0.5f * float(sin(now * 2.4)));
  }
  else if (card.status == AgentCardStatus::Pending) {
    wash = 0.45f;
  }

  float dark[4], green[4], border[4];
  with_alpha(CARD_DARK, alpha, dark);
  with_alpha(CARD_GREEN, alpha * wash, green);
  with_alpha(running ? CARD_BORDER_RUNNING : CARD_BORDER, alpha, border);

  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv_ex(&rect,
                           /*inner1 (right)*/ dark,
                           /*inner2 (left)*/ green,
                           /*shade_dir*/ 0.0f,
                           border,
                           U.pixelsize,
                           AGENT_PANEL_CARD_RADIUS * scale);

  /* The same silhouette as the island, with per-task identity and phase. */
  const rctf cat = to_rctf(card.cat_rect);
  const double cat_time = running ? now + double(card.cat_ordinal) * 1.137 : 1.0;
  agent_ui_draw_cat(cat, cat_time, running, card.cat_ordinal, alpha);
  const float avatar_cy = BLI_rctf_cent_y(&cat);

  /* Name, then the elapsed clock right after it in muted type. */
  const int font_id = BLF_default();
  BLF_size(font_id, 12.0f * scale);
  const float line_h = BLF_height_max(font_id);
  const float baseline = avatar_cy - line_h * 0.34f;

  const float text_x = cat.xmax + 7.0f * scale;
  const float text_right = float(card.eye_rect.xmin) - 8.0f * scale;

  BLF_size(font_id, 12.0f * scale);
  float name_color[4];
  with_alpha(TEXT_NAME, alpha, name_color);
  /* The eye swaps the short agent name for the full task it was given —
   * the name is derived from that task and elides early, so this is where a
   * long instruction is actually readable. */
  draw_elided(font_id,
              card.expanded ? card.task : card.name,
              text_x,
              baseline,
              text_right - text_x,
              name_color);

  /* Controls: the eye expands the card's full task; the right slot is a
   * dismiss cross while the agent works and its outcome once it settles. */
  float glyph[4];
  with_alpha(GLYPH, alpha, glyph);
  view3d_agent_panel_glyph_eye(card.eye_rect, scale, glyph);

  switch (card.status) {
    case AgentCardStatus::Done: {
      float done[4];
      with_alpha(GLYPH_DONE, alpha, done);
      view3d_agent_panel_glyph_check(card.action_rect, scale, done);
      break;
    }
    case AgentCardStatus::Failed: {
      float failed[4];
      with_alpha(GLYPH_FAILED, alpha, failed);
      view3d_agent_panel_glyph_cross(card.action_rect, scale, failed);
      break;
    }
    default:
      view3d_agent_panel_glyph_cross(card.action_rect, scale, glyph);
      break;
  }
}

void draw_chevron(const rcti &box, const float alpha)
{
  if (BLI_rcti_size_x(&box) <= 0) {
    return;
  }
  const float scale = UI_SCALE_FAC;
  const rctf rect = to_rctf(box);
  float body[4], border[4], glyph[4];
  with_alpha(CARD_DARK, alpha, body);
  with_alpha(CARD_BORDER, alpha, border);
  with_alpha(GLYPH, alpha, glyph);

  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv_ex(
      &rect, body, nullptr, 1.0f, border, U.pixelsize, BLI_rctf_size_y(&rect) * 0.5f);
  view3d_agent_panel_glyph_chevrons_down(box, scale, glyph);
}

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Region Init / Exit
 * \{ */

void view3d_agent_panel_region_init(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Agent Panel", SPACE_VIEW3D, RGN_TYPE_EXECUTE);
  WM_event_add_keymap_handler(&region->runtime->handlers, keymap);

  /* A newly polled-in region draws only when something tags it, and its
   * cards, hit rects and QA targets do not exist until it has. */
  ED_region_tag_redraw(region);
}

void view3d_agent_panel_region_exit(wmWindowManager *wm, ARegion *region)
{
  /* Stop the animation tick while the panel is hidden (no agents) or
   * closing; the runtime itself stays alive so scroll and clocks survive a
   * temporary hide. */
  AgentPanelRuntime *runtime = static_cast<AgentPanelRuntime *>(region->regiondata);
  view3d_agent_panel_tick_timer_remove(wm, runtime);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region Draw
 * \{ */

void view3d_agent_panel_region_draw(const bContext *C, ARegion *region)
{
  if (region->overlap) {
    /* Transparent background: the cards float over the main viewport, which
     * extends behind this region. */
    GPU_clear_color(0.0f, 0.0f, 0.0f, 0.0f);
  }
  else {
    /* Region overlap disabled in the preferences — docked opaque, fall back
     * to the editor background. */
    ui::theme::frame_buffer_clear(TH_BACK);
  }

  AgentPanelRuntime *runtime = view3d_agent_panel_runtime_ensure(region);
  view3d_agent_panel_cards_sync(C, runtime);
  view3d_agent_panel_layout_cards(region, runtime);

  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);

  /* Clip to the card column so a half-scrolled card is cut cleanly at the
   * boundary. A right dock is as tall as the whole area, so without this a
   * long fan-out would simply paint every card and scrolling would mean
   * nothing. Restored below — the scissor is region state the rest of the
   * frame relies on. */
  const rcti &column = runtime->column_rect;
  const bool clip = BLI_rcti_size_x(&column) > 0 && BLI_rcti_size_y(&column) > 0;
  int scissor_prev[4];
  if (clip) {
    /* REGION-LOCAL coordinates. Each region draws into its own framebuffer,
     * whose origin is the region's corner (`wm_draw_region_bind` scissors to
     * `0, 0, winx, winy`) — offsetting by `winrct` puts the box outside that
     * framebuffer and clips every card away, with nothing drawn and no error. */
    GPU_scissor_get(scissor_prev);
    GPU_scissor(
        column.xmin, column.ymin, BLI_rcti_size_x(&column) + 1, BLI_rcti_size_y(&column) + 1);
  }

  const double now = BLI_time_now_seconds();
  const int n = int(runtime->cards.size());
  for (int i = 0; i < n; i++) {
    const AgentPanelCard &card = runtime->cards[i];
    /* Cards scrolled out of the column are laid out but never painted —
     * the same test the hit test and the QA provider apply. */
    if (!view3d_agent_panel_card_visible(runtime, card.rect)) {
      continue;
    }
    /* A finished card fades as it leaves, so it does not simply blink out at
     * the column edge. */
    const float alpha = 1.0f - card.slide.value;
    draw_card(card, alpha, now);
  }

  if (clip) {
    GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
  }

  /* The chevron sits BELOW the clipped column, so it is drawn unclipped. */
  draw_chevron(runtime->chevron_rect, view3d_agent_panel_reveal(runtime, 0));

  GPU_blend(GPU_BLEND_NONE);

  /* The animation is time-driven, not event-driven, so it needs a tick to
   * keep producing frames — and the tick has to be what requests the repaint:
   * a redraw tagged from HERE is cleared the moment this callback returns
   * (`wm_draw.cc` sets `do_draw = 0` right after `ED_region_do_draw`), which
   * is why the panel animated at the timer's rate rather than the display's.
   * `agent_panel_region_listener` does the tagging; this only owns the
   * timer's lifetime. Cards persist after a turn ends, so an ungated timer
   * would tick over the viewport until the next turn. */
  if (view3d_agent_panel_is_animating(runtime)) {
    view3d_agent_panel_tick_timer_ensure(C, runtime);
  }
  else {
    view3d_agent_panel_tick_timer_remove(CTX_wm_manager(C), runtime);
  }
}

/** \} */

}  // namespace blender
