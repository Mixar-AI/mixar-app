/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Parallel Agents panel: reading the WindowManager card mirror, laying the
 * cards out, hit-testing them, and the region-type registration.
 *
 * The layout pass is the ONE owner of `card.rect`. Draw, the mouse hit test
 * and the QA target provider all read what it wrote — including the scroll
 * offset and the slide-in animation — so a card can never be drawn in one
 * place and clicked in another.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_map.hh"
#include "BLI_set.hh"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_view2d_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_agent_panel.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Animation
 * \{ */

/** Ease-out cubic: fast entry, soft landing. */
static float agent_panel_ease_out(const float t)
{
  const float inv = 1.0f - std::clamp(t, 0.0f, 1.0f);
  return 1.0f - inv * inv * inv;
}

float view3d_agent_panel_exit_progress(const AgentPanelCard &card)
{
  if (card.seen_exit_at == 0.0) {
    return 0.0f;
  }
  if (!card.dismissing && card.status != AgentCardStatus::Done) {
    return 0.0f;
  }
  /* A dismissal is a direct answer to a click and leaves at once; a finished
   * card dwells first so its check mark registers. */
  const double dwell = card.dismissing ? 0.0 : AGENT_PANEL_DONE_DWELL_SECONDS;
  const double elapsed = BLI_time_now_seconds() - card.seen_exit_at - dwell;
  if (elapsed <= 0.0) {
    return 0.0f;
  }
  return agent_panel_ease_out(float(elapsed / AGENT_PANEL_EXIT_SECONDS));
}

float view3d_agent_panel_reveal(const AgentPanelRuntime *runtime, const int card_index)
{
  if (runtime->reveal_started_at == 0.0) {
    return 1.0f;
  }
  const double delay = (card_index > 0) ? double(card_index) * AGENT_PANEL_STAGGER_SECONDS : 0.0;
  const double elapsed = BLI_time_now_seconds() - runtime->reveal_started_at - delay;
  if (elapsed <= 0.0) {
    return 0.0f;
  }
  return agent_panel_ease_out(float(elapsed / AGENT_PANEL_REVEAL_SECONDS));
}

bool view3d_agent_panel_is_animating(const AgentPanelRuntime *runtime)
{
  if (runtime->cards.is_empty()) {
    return false;
  }
  /* Still sliding in? The last card carries the largest stagger. */
  if (view3d_agent_panel_reveal(runtime, int(runtime->cards.size()) - 1) < 1.0f) {
    return true;
  }
  for (const AgentPanelCard &card : runtime->cards) {
    /* A running agent's elapsed clock has to keep ticking. */
    if (card.status == AgentCardStatus::Running) {
      return true;
    }
    /* A card is on its way out, or waiting to start leaving. */
    if ((card.dismissing || card.status == AgentCardStatus::Done) &&
        view3d_agent_panel_exit_progress(card) < 1.0f)
    {
      return true;
    }
  }
  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Layout & Hit Testing
 * \{ */

/** Publish the card column as the region's View2D extent.
 *
 * This is what makes the panel clickable at all. For an overlapping side
 * region `ED_region_contains_xy` does NOT stop at `winrct`: it runs
 * `ED_region_overlap_isect_y_with_margin`, which bails immediately when
 * `v2d.mask` is degenerate and otherwise tests the event against `v2d.tot`.
 * A custom-drawn region that never sets up a View2D therefore has an empty
 * mask and is transparent to every event — the keymap resolves, the operator
 * polls fine, and no wheel or click ever arrives, with nothing logged.
 *
 * Publishing the CARD COLUMN rather than the whole region is also what the
 * surface wants: the panel is as tall as the area, so anything below the last
 * card stays viewport, and an orbit drag started there still reaches the 3D
 * view. `cur` is set equal to `mask` so the region→view mapping is the
 * identity and `tot` can be given in region pixels. */
static void agent_panel_view2d_sync(const ARegion *region, const rcti &column)
{
  View2D *v2d = &const_cast<ARegion *>(region)->v2d;

  BLI_rcti_init(&v2d->mask, 0, std::max(region->winx - 1, 0), 0, std::max(region->winy - 1, 0));
  v2d->cur.xmin = 0.0f;
  v2d->cur.xmax = float(region->winx);
  v2d->cur.ymin = 0.0f;
  v2d->cur.ymax = float(region->winy);

  v2d->tot.xmin = float(column.xmin);
  v2d->tot.xmax = float(column.xmax + 1);
  v2d->tot.ymin = float(column.ymin);
  v2d->tot.ymax = float(column.ymax + 1);
}

void view3d_agent_panel_layout_cards(const ARegion *region, AgentPanelRuntime *runtime)
{
  const int n = int(runtime->cards.size());
  if (n == 0) {
    runtime->scroll = 0.0f;
    runtime->scroll_max = 0.0f;
    BLI_rcti_init(&runtime->column_rect, 0, 0, 0, 0);
    BLI_rcti_init(&runtime->chevron_rect, 0, 0, 0, 0);
    agent_panel_view2d_sync(region, runtime->column_rect);
    return;
  }

  const float scale = UI_SCALE_FAC;
  const int left = int(AGENT_PANEL_MARGIN_LEFT * scale);
  const int bottom = int(AGENT_PANEL_MARGIN_BOTTOM * scale);
  const int card_h = int(AGENT_PANEL_CARD_HEIGHT * scale);
  const int gap = int(AGENT_PANEL_CARD_GAP * scale);
  const int card_w = std::min(int(AGENT_PANEL_CARD_WIDTH * scale),
                              std::max(region->winx - 2 * left, 0));

  const int stride = card_h + gap;
  const int column_h = n * stride - gap;
  const int chevron_h = int(AGENT_PANEL_CHEVRON_HEIGHT * scale);
  const int chevron_gap = int(AGENT_PANEL_CHEVRON_GAP * scale);

  /* The stack sits at the BOTTOM-LEFT and grows upward, with the chevron
   * tucked under its lowest card. */
  const int stack_bottom = bottom + chevron_h + chevron_gap;
  const int room_h = std::max(region->winy - stack_bottom - bottom, 0);
  const int visible_h = std::min(room_h, AGENT_PANEL_VISIBLE_CARDS * stride - gap);

  runtime->scroll_max = float(std::max(column_h - visible_h, 0));
  runtime->scroll = std::clamp(runtime->scroll, 0.0f, runtime->scroll_max);

  /* The clipped window the column scrolls behind. A left-docked region is as
   * tall as the whole area, so this — not `region->winy` — is what "visible"
   * means for a card. */
  BLI_rcti_init(&runtime->column_rect,
                left,
                left + card_w - 1,
                stack_bottom,
                stack_bottom + visible_h - 1);

  /* Card 0 is the top of the reading order and starts at the TOP of the
   * visible band, so an unscrolled stack shows the FIRST three agents and the
   * chevron's downward arrow means what it says: more of them are below. */
  const int column_top = stack_bottom + visible_h;
  for (int i = 0; i < n; i++) {
    /* Both the slide-in and a finished card's slide-out travel the same way:
     * off the LEFT edge of the region. */
    const float reveal = view3d_agent_panel_reveal(runtime, i);
    const float exit = view3d_agent_panel_exit_progress(runtime->cards[i]);
    const float offscreen = std::clamp((1.0f - reveal) + exit, 0.0f, 1.0f);
    const int slide = int(roundf(offscreen * float(left + card_w)));

    const int card_bottom = column_top - (i + 1) * stride + gap +
                            int(roundf(runtime->scroll));
    rcti *rect = &runtime->cards[i].rect;
    rect->xmin = left - slide;
    rect->xmax = rect->xmin + card_w - 1;
    rect->ymin = card_bottom;
    rect->ymax = card_bottom + card_h - 1;

    const int avatar = int(AGENT_PANEL_AVATAR_SIZE * scale);
    rcti &cat = runtime->cards[i].cat_rect;
    cat.xmin = rect->xmin + int(AGENT_PANEL_AVATAR_INSET * scale);
    cat.xmax = cat.xmin + avatar - 1;
    cat.ymin = card_bottom + (card_h - avatar) / 2;
    cat.ymax = cat.ymin + avatar - 1;

    /* The two glyph buttons, right-aligned inside the card. */
    const int icon = int(AGENT_PANEL_ICON_SIZE * scale);
    const int icon_gap = int(AGENT_PANEL_ICON_GAP * scale);
    const int icon_inset = int(AGENT_PANEL_ICON_INSET * scale);
    const int icon_y = card_bottom + (card_h - icon) / 2;

    rcti *action = &runtime->cards[i].action_rect;
    action->xmax = rect->xmax - icon_inset;
    action->xmin = action->xmax - icon + 1;
    action->ymin = icon_y;
    action->ymax = icon_y + icon - 1;

    rcti *eye = &runtime->cards[i].eye_rect;
    eye->xmax = action->xmin - icon_gap;
    eye->xmin = eye->xmax - icon + 1;
    eye->ymin = icon_y;
    eye->ymax = icon_y + icon - 1;
  }

  /* The chevron only exists while there are MORE AGENTS THAN THE STACK SHOWS
   * — it is the discoverable half of scrolling. Keyed on the card count
   * rather than on `scroll_max` alone: a viewport short enough to squeeze the
   * column gives a non-zero `scroll_max` at three cards or fewer, and a
   * chevron appearing next to a stack that plainly shows everything reads as
   * a bug. `scroll_max` still gates it too, so it is never a dead control. */
  if (n > AGENT_PANEL_VISIBLE_CARDS && runtime->scroll_max > 0.0f) {
    const int chevron_w = int(AGENT_PANEL_CHEVRON_WIDTH * scale);
    const int cx = left + card_w / 2;
    BLI_rcti_init(&runtime->chevron_rect,
                  cx - chevron_w / 2,
                  cx - chevron_w / 2 + chevron_w - 1,
                  bottom,
                  bottom + chevron_h - 1);
  }
  else {
    BLI_rcti_init(&runtime->chevron_rect, 0, 0, 0, 0);
  }

  /* The View2D extent covers the cards AND the chevron, so both are
   * clickable and everything else in this full-height region stays
   * transparent to the viewport behind it. */
  rcti hit = runtime->column_rect;
  if (BLI_rcti_size_x(&runtime->chevron_rect) > 0) {
    BLI_rcti_union(&hit, &runtime->chevron_rect);
  }
  agent_panel_view2d_sync(region, hit);
}

bool view3d_agent_panel_card_visible(const AgentPanelRuntime *runtime, const rcti &rect)
{
  const rcti &column = runtime->column_rect;
  if (BLI_rcti_size_x(&column) <= 0 || BLI_rcti_size_y(&column) <= 0) {
    return false;
  }
  return !(rect.ymax < column.ymin || rect.ymin > column.ymax || rect.xmin > column.xmax ||
           rect.xmax < column.xmin);
}

AgentPanelHit view3d_agent_panel_hit_test(AgentPanelRuntime *runtime,
                                          const int mval[2],
                                          int *r_card_index)
{
  if (r_card_index != nullptr) {
    *r_card_index = -1;
  }
  if (BLI_rcti_isect_pt(&runtime->chevron_rect, mval[0], mval[1]) &&
      BLI_rcti_size_x(&runtime->chevron_rect) > 0)
  {
    return AgentPanelHit::Chevron;
  }
  /* Clipped away is not clickable — the same test draw and the QA provider
   * apply, so a card scrolled out of the column is hit nowhere. */
  if (!BLI_rcti_isect_pt(&runtime->column_rect, mval[0], mval[1])) {
    return AgentPanelHit::None;
  }
  const int n = int(runtime->cards.size());
  for (int i = 0; i < n; i++) {
    const AgentPanelCard &card = runtime->cards[i];
    if (!BLI_rcti_isect_pt(&card.rect, mval[0], mval[1])) {
      continue;
    }
    if (r_card_index != nullptr) {
      *r_card_index = i;
    }
    if (BLI_rcti_isect_pt(&card.action_rect, mval[0], mval[1])) {
      return AgentPanelHit::Action;
    }
    if (BLI_rcti_isect_pt(&card.eye_rect, mval[0], mval[1])) {
      return AgentPanelHit::Eye;
    }
    return AgentPanelHit::Card;
  }
  return AgentPanelHit::None;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Runtime Lifecycle
 * \{ */

ARegion *view3d_agent_panel_region_find(const ScrArea *area)
{
  if (!area || area->spacetype != SPACE_VIEW3D) {
    return nullptr;
  }
  for (ARegion &region_iter : area->regionbase) {
    ARegion *region = &region_iter;
    if (region->regiontype == RGN_TYPE_EXECUTE) {
      return region;
    }
  }
  return nullptr;
}

AgentPanelRuntime *view3d_agent_panel_runtime_ensure(ARegion *region)
{
  if (region->regiondata == nullptr) {
    region->regiondata = MEM_new<AgentPanelRuntime>("AgentPanelRuntime");
    region->flag |= RGN_FLAG_TEMP_REGIONDATA;
  }
  return static_cast<AgentPanelRuntime *>(region->regiondata);
}

void view3d_agent_panel_tick_timer_ensure(const bContext *C, AgentPanelRuntime *runtime)
{
  if (runtime->tick_timer != nullptr) {
    return;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  wmWindow *win = CTX_wm_window(C);
  if (wm == nullptr || win == nullptr) {
    return;
  }
  runtime->tick_timer = WM_event_timer_add(wm, win, TIMERNOTIFIER, AGENT_PANEL_TICK_INTERVAL);
}

void view3d_agent_panel_tick_timer_remove(wmWindowManager *wm, AgentPanelRuntime *runtime)
{
  if (runtime == nullptr || runtime->tick_timer == nullptr) {
    return;
  }
  if (wm != nullptr) {
    WM_event_timer_remove(wm, runtime->tick_timer->win, runtime->tick_timer);
  }
  runtime->tick_timer = nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region Type Registration
 * \{ */

void view3d_agent_panel_space_listener(const wmSpaceTypeListenerParams *params)
{
  /* Cheap: one category compare, then a flag. `ED_area_tag_refresh` only sets
   * `do_refresh`; the refresh itself runs in the event loop's own pass, never
   * inside a draw. */
  const wmNotifier *wmn = params->notifier;
  if (ELEM(wmn->category, NC_WINDOW, NC_SCREEN)) {
    ED_area_tag_refresh(params->area);
    /* A region the refresh brings back has no `regiondata` until it draws —
     * and until it draws it has no cards, no hit rects and no QA targets. The
     * refresh alone does not tag it, so a panel could exist at full size and
     * paint nothing at all. */
    ED_area_tag_redraw_regiontype(params->area, RGN_TYPE_EXECUTE);
  }
}

static void agent_panel_region_listener(const wmRegionListenerParams *params)
{
  /* The animation tick arrives here, and this is the only place that can act
   * on it: `wm_draw.cc` clears `region->runtime->do_draw` immediately AFTER
   * `ED_region_do_draw` returns, so a redraw tagged from inside the draw
   * callback is wiped before it can take effect. Tagging from a listener —
   * outside the draw — is what actually produces the next frame, which makes
   * the tick interval the animation's real frame rate.
   *
   * Gated on the runtime, so a settled panel costs a pointer read. */
  ARegion *region = params->region;
  const AgentPanelRuntime *runtime = static_cast<const AgentPanelRuntime *>(region->regiondata);
  if (runtime != nullptr && view3d_agent_panel_is_animating(runtime)) {
    ED_region_tag_redraw(region);
  }
}

static bool agent_panel_region_poll(const RegionPollParams *params)
{
  /* Polls run every event-loop cycle, so this stays a single RNA read: the
   * Python mirror maintains the count, and the panel exists exactly while
   * the running (or last) turn fanned out to parallel agents. */
  return view3d_agent_panel_card_count(params->context) > 0;
}

static void agent_panel_region_free(ARegion *region)
{
  if (region->regiondata != nullptr) {
    AgentPanelRuntime *runtime = static_cast<AgentPanelRuntime *>(region->regiondata);
    /* The timer is owned by the window manager and removed in the region
     * exit callback, which always runs first; clear the pointer regardless
     * so a stale one can never be dereferenced. */
    runtime->tick_timer = nullptr;
    MEM_delete(runtime);
    region->regiondata = nullptr;
  }
}

static void *agent_panel_region_duplicate(void * /*poin*/)
{
  /* Runtime is per-region; copies (area split/duplicate) start fresh. */
  return nullptr;
}

void view3d_agent_panel_region_register(SpaceType *st)
{
  /* Fully custom GPU drawing — no ED_KEYMAP_UI, whose ui_region_handler could
   * consume LEFTMOUSE before our keymap (same reasoning as the Mixie Chat
   * main region). */
  ARegionType *art = MEM_new_zeroed<ARegionType>("spacetype view3d agent panel region");
  art->regionid = RGN_TYPE_EXECUTE;
  art->prefsizey = AGENT_PANEL_PREFSIZEY;
  art->keymapflag = 0;
  art->poll = agent_panel_region_poll;
  art->init = view3d_agent_panel_region_init;
  art->exit = view3d_agent_panel_region_exit;
  art->draw = view3d_agent_panel_region_draw;
  art->free = agent_panel_region_free;
  art->duplicate = agent_panel_region_duplicate;
  art->listener = agent_panel_region_listener;
  BLI_addhead(&st->regiontypes, art);
}

/** \} */

}  // namespace blender
