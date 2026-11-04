/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Video card hover overlay: dim the movie, show Preview / Play / Sound.
 *
 * Applies to every movie on the board -- an uploaded tile and a generated
 * result inside its node alike. Hovering a card darkens the frame and pops
 * three controls over it: open the preview player (left), play/pause
 * (centre), mute/unmute (right). Hover is only presentation: it never starts
 * or stops playback, so a movie keeps playing to its end wherever the pointer
 * goes.
 *
 * Hover is tracked per canvas region (the Mixie editor and the Zen drawer):
 * the draw pass records each movie's rect, the regions' cursor callbacks (run
 * on every mouse move, `event_cursor`) pick the card under the pointer and
 * redraw only when that changes, and a short context-free timer clears it once
 * the pointer has left the region, which sends the region no event.
 */

#include "mixie_moodboard_ops_common.hh"

#include <string>
#include <unordered_map>
#include <vector>

#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"
#include "BKE_wm_runtime.hh"

#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"
#include "BLI_timer.h"

#include "GPU_immediate.hh"
#include "GPU_immediate_util.hh"
#include "GPU_state.hh"

#include "ED_screen.hh"

#include "UI_view2d.hh"

#include "mixie_moodboard_canvas.hh"
#include "mixie_moodboard_video_glyphs.hh"

namespace blender::ed::mixie {

/* Centre-to-centre spacing of the three controls, in button radii. */
static constexpr float CARD_BUTTON_SPACING = 2.9f;
/* Hit target around each glyph, as a multiple of its radius. */
static constexpr float CARD_BUTTON_HIT = 1.25f;
static constexpr float CARD_DIM_ALPHA = 0.42f;
static constexpr double CARD_HOVER_WATCH_SECONDS = 0.12;

/* -------------------------------------------------------------------- */
/** \name Layout and hit-test
 * \{ */

/** The shared play radius, shrunk further when three buttons would not fit. */
static float card_button_radius(View2D *v2d, const rctf &media_rect)
{
  const float radius = moodboard_video_play_radius(v2d, media_rect);
  /* Outer buttons must stay inside the card: half width >= spacing + 1 radius. */
  const float fit = 0.46f * BLI_rctf_size_x(&media_rect) / (CARD_BUTTON_SPACING + 1.0f);
  return std::max(std::min(radius, fit), 0.0f);
}

void moodboard_video_card_button_rects(View2D *v2d, const rctf &media_rect, rctf r_rects[3])
{
  const float radius = card_button_radius(v2d, media_rect);
  const float cx = BLI_rctf_cent_x(&media_rect);
  const float cy = BLI_rctf_cent_y(&media_rect);
  const float offsets[3] = {-CARD_BUTTON_SPACING, 0.0f, CARD_BUTTON_SPACING};
  for (int i = 0; i < 3; i++) {
    const float x = cx + offsets[i] * radius;
    r_rects[i] = {x - radius, x + radius, cy - radius, cy + radius};
  }
}

int moodboard_video_card_button_at(View2D *v2d,
                                   const rctf &media_rect,
                                   const float x,
                                   const float y)
{
  rctf rects[3];
  moodboard_video_card_button_rects(v2d, media_rect, rects);
  for (int i = 0; i < 3; i++) {
    const float radius = BLI_rctf_size_x(&rects[i]) * 0.5f * CARD_BUTTON_HIT;
    const float dx = x - BLI_rctf_cent_x(&rects[i]);
    const float dy = y - BLI_rctf_cent_y(&rects[i]);
    if (dx * dx + dy * dy <= radius * radius) {
      return i;
    }
  }
  return MOODBOARD_VIDEO_CARD_NONE;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hover tracking
 * \{ */

struct CardRect {
  std::string key;
  rctf rect;
};

struct RegionCards {
  std::vector<CardRect> cards;
  std::string hovered;
};

static std::unordered_map<const ARegion *, RegionCards> g_region_cards;
/** Only its address is used: the BLI timer id of the hover watchdog. */
static char g_hover_watch_identity;

void moodboard_video_cards_frame_begin(const ARegion *region)
{
  g_region_cards[region].cards.clear();
}

bool moodboard_video_card_register(const ARegion *region, const char *key, const rctf &rect)
{
  if (!region || !key || key[0] == '\0') {
    return false;
  }
  RegionCards &cards = g_region_cards[region];
  cards.cards.push_back({key, rect});
  return cards.hovered == key;
}

/** The region still exists in some open window (it may have been freed). */
static bool region_is_live(const ARegion *region, wmWindow **r_win)
{
  wmWindowManager *wm = G_MAIN ? static_cast<wmWindowManager *>(G_MAIN->wm.first) : nullptr;
  if (!wm) {
    return false;
  }
  for (wmWindow &win : wm->windows) {
    bScreen *screen = WM_window_get_active_screen(&win);
    if (!screen) {
      continue;
    }
    for (ScrArea &area : screen->areabase) {
      for (ARegion &candidate : area.regionbase) {
        if (&candidate == region) {
          *r_win = &win;
          return true;
        }
      }
    }
  }
  return false;
}

/**
 * Leaving a region sends it no event, so a hovered card would stay dimmed until
 * something else redrew it. While any card is hovered this checks the pointer
 * against its region a few times a second and clears the hover once it is out.
 */
static double hover_watch_tick(uintptr_t /*uuid*/, void * /*user_data*/)
{
  bool any_hovered = false;
  for (auto it = g_region_cards.begin(); it != g_region_cards.end();) {
    wmWindow *win = nullptr;
    if (!region_is_live(it->first, &win)) {
      it = g_region_cards.erase(it);
      continue;
    }
    RegionCards &cards = it->second;
    if (!cards.hovered.empty()) {
      const wmEvent *event = win->runtime->eventstate;
      const bool inside = event && BLI_rcti_isect_pt_v(&it->first->winrct, event->xy);
      if (!inside) {
        cards.hovered.clear();
        ED_region_tag_redraw(const_cast<ARegion *>(it->first));
      }
      else {
        any_hovered = true;
      }
    }
    ++it;
  }
  return any_hovered ? CARD_HOVER_WATCH_SECONDS : -1.0;
}

void moodboard_video_card_hover_update(wmWindow *win, ScrArea *area, ARegion *region)
{
  const auto found = g_region_cards.find(region);
  if (found == g_region_cards.end()) {
    return;
  }
  RegionCards &cards = found->second;
  std::string hovered;
  const wmEvent *event = win ? win->runtime->eventstate : nullptr;
  if (event && moodboard_canvas_point_is_interactive(area, region, event->xy)) {
    float x = 0.0f, y = 0.0f;
    ui::view2d_region_to_view(&region->v2d,
                              event->xy[0] - region->winrct.xmin,
                              event->xy[1] - region->winrct.ymin,
                              &x,
                              &y);
    /* Drawn last = on top. */
    for (auto it = cards.cards.rbegin(); it != cards.cards.rend(); ++it) {
      if (BLI_rctf_isect_pt(&it->rect, x, y)) {
        hovered = it->key;
        break;
      }
    }
  }
  if (hovered == cards.hovered) {
    return;
  }
  cards.hovered = hovered;
  ED_region_tag_redraw(region);
  if (!hovered.empty()) {
    const uintptr_t tick_id = uintptr_t(&g_hover_watch_identity);
    if (!BLI_timer_is_registered(tick_id)) {
      BLI_timer_register(
          tick_id, hover_watch_tick, nullptr, nullptr, CARD_HOVER_WATCH_SECONDS, true);
    }
  }
}

void mixie_moodboard_video_cards_shutdown()
{
  BLI_timer_unregister(uintptr_t(&g_hover_watch_identity));
  g_region_cards.clear();
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Overlay
 * \{ */

void mixie_draw_moodboard_video_overlay(View2D *v2d,
                                        const rctf &media_rect,
                                        const bool hovered,
                                        const bool is_playing,
                                        const bool muted)
{
  if (!hovered) {
    /* At rest the movie is shown clean, playing or not. */
    return;
  }

  GPU_blend(GPU_BLEND_ALPHA);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.0f, 0.0f, 0.0f, CARD_DIM_ALPHA);
  immRectf(pos, media_rect.xmin, media_rect.ymin, media_rect.xmax, media_rect.ymax);
  immUnbindProgram();
  GPU_blend(GPU_BLEND_NONE);

  rctf rects[3];
  moodboard_video_card_button_rects(v2d, media_rect, rects);
  const float glyph = BLI_rctf_size_x(&rects[0]) * 1.15f;
  /* Strokes scale with the button, within a readable pixel range. */
  const float view_scale = std::max(ui::view2d_scale_get_x(v2d), 0.001f);
  const float line_px = std::clamp(glyph * view_scale * 0.075f, 1.5f, 4.0f);
  const float white[4] = {1.0f, 1.0f, 1.0f, 0.96f};

  video_glyph_draw(VideoGlyph::OpenPreview,
                   BLI_rctf_cent_x(&rects[0]),
                   BLI_rctf_cent_y(&rects[0]),
                   glyph,
                   line_px,
                   white);
  video_glyph_draw(is_playing ? VideoGlyph::Pause : VideoGlyph::Play,
                   BLI_rctf_cent_x(&rects[1]),
                   BLI_rctf_cent_y(&rects[1]),
                   glyph,
                   line_px,
                   white);
  video_glyph_draw(muted ? VideoGlyph::SoundOff : VideoGlyph::SoundOn,
                   BLI_rctf_cent_x(&rects[2]),
                   BLI_rctf_cent_y(&rects[2]),
                   glyph,
                   line_px,
                   white);
}

/** \} */

}  // namespace blender::ed::mixie
