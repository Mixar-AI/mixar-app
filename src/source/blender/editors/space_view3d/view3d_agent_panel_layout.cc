/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Shared card layout, pointer bounds and notification anchor. */
#include "../interface/interface_intern.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_view2d_types.h"
#include "ED_agent_panel.hh"
#include "UI_interface.hh"
#include "view3d_agent_panel.hh"
#include "view3d_workspace_viewer.hh"
#include <algorithm>
#include <cmath>

namespace blender {
/** Publish the card column as the region's View2D extent.
 *
 * This is what makes the panel clickable at all. For an overlapping region
 * `ED_region_contains_xy` does NOT stop at `winrct`: it bails immediately when
 * `v2d.mask` is degenerate and otherwise tests the event against `v2d.tot`.
 * A custom-drawn region that never sets up a View2D therefore has an empty
 * mask and is transparent to every event — the keymap resolves, the operator
 * polls fine, and no wheel or click ever arrives, with nothing logged.
 *
 * Publishing the CARD COLUMN rather than the whole region is also what the
 * surface wants. The region is taller than its cards, and `ED_region_contains_xy`
 * clips it on BOTH axes (a stock BOTTOM-aligned overlap clips X only), so the
 * band above the cards stays viewport: an orbit drag started there reaches the
 * 3D view and the notifications stacked there receive their own presses.
 * `cur` is set equal to `mask` so the region→view mapping is the identity and
 * `tot` can be given in region pixels. */
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
    runtime->chevron_label[0] = '\0';
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
  const bool paging = n > AGENT_PANEL_VISIBLE_CARDS || column_h > region->winy - 2 * bottom;
  const int stack_bottom = bottom + (paging ? chevron_h + chevron_gap : 0);
  const int room_h = std::max(region->winy - stack_bottom - bottom, 0);
  const int visible_h = std::min({room_h, column_h, AGENT_PANEL_VISIBLE_CARDS * stride - gap});

  runtime->scroll_max = float(std::max(column_h - visible_h, 0));
  runtime->scroll = std::clamp(runtime->scroll, 0.0f, runtime->scroll_max);
  const int scroll_px = int(roundf(runtime->scroll));
  /* Count completed rows with the exact integer stride and scroll used below.
   * Re-scaling the unrounded metrics can lose a row at fractional UI scales. */
  const int seen = (scroll_px + visible_h + gap) / stride;
  const int remaining = std::max(n - seen, 1);
  if (view3d_agent_panel_at_end(runtime)) {
    STRNCPY(runtime->chevron_label, "Back to first");
  }
  else {
    SNPRINTF(runtime->chevron_label, "%d more agent%s", remaining, remaining == 1 ? "" : "s");
  }

  /* The clipped window the column scrolls behind. A left-docked region is as
   * tall as the whole area, so this — not `region->winy` — is what "visible"
   * means for a card. */
  BLI_rcti_init(
      &runtime->column_rect, left, left + card_w - 1, stack_bottom, stack_bottom + visible_h - 1);

  /* Card 0 is the top of the reading order and starts at the TOP of the
   * visible band, so an unscrolled stack shows the FIRST three agents and the
   * chevron's downward arrow means what it says: more of them are below. */
  const int column_top = stack_bottom + visible_h;
  const double now = BLI_time_now_seconds();
  for (int i = 0; i < n; i++) {
    /* Both the slide-in and a finished card's slide-out travel the same way:
     * off the LEFT edge of the region. */
    AgentPanelCard &card = runtime->cards[i];
    const bool leaving = card.seen_exit_at != 0.0 &&
                         (card.dismissing || card.status == AgentCardStatus::Done) &&
                         now >= card.seen_exit_at +
                                    (card.dismissing ? 0.0 : AGENT_PANEL_DONE_DWELL_SECONDS);
    if (now >= card.reveal_started_at) {
      card.slide.sample(leaving ? 1.0f : 0.0f,
                        now,
                        leaving ? AGENT_PANEL_EXIT_SECONDS : AGENT_PANEL_REVEAL_SECONDS);
    }
    const float offscreen = card.slide.value;
    const int slide = int(roundf(offscreen * float(left + card_w)));

    const float row = card.row.sample(float(i), now, ui::mixar_motion::selection_seconds);
    const int card_bottom = column_top - int(roundf((row + 1.0f) * stride)) + gap +
                            scroll_px;
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

  /* Every clipped list has a reachable paging control, including short viewports. */
  if (runtime->scroll_max > 0.0f) {
    const int chevron_w = std::min(card_w, int(AGENT_PANEL_CHEVRON_WIDTH * scale));
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
    if (card.has_workspace && BLI_rcti_isect_pt(&card.eye_rect, mval[0], mval[1])) {
      return AgentPanelHit::Eye;
    }
    return AgentPanelHit::Card;
  }
  return AgentPanelHit::None;
}

bool view3d_agent_panel_at_end(const AgentPanelRuntime *runtime)
{
  return runtime->scroll >= runtime->scroll_max - 0.5f;
}

void ED_agent_panel_bounds(const ScrArea *area, const ARegion *viewport, int bounds[5])
{
  const int inset = int(AGENT_PANEL_MARGIN_LEFT * UI_SCALE_FAC);
  bounds[0] = inset;
  bounds[1] = bounds[3] = int(AGENT_PANEL_MARGIN_BOTTOM * UI_SCALE_FAC);
  bounds[2] = std::max(
      inset, std::min(inset + int(AGENT_PANEL_CARD_WIDTH * UI_SCALE_FAC), viewport->winx - inset));
  bounds[4] = viewport->winy;
  /* Native tool button geometry includes the floating toolbar's layout offset.
   * Keep long notifications below it, rather than behind its later draw pass. */
  if (area) {
    for (const ARegion &tools : area->regionbase) {
      if (tools.regiontype != RGN_TYPE_TOOLS || !tools.runtime->visible) {
        continue;
      }
      for (const ui::Block &block : tools.runtime->uiblocks) {
        for (const auto &button : block.buttons_ptrs) {
          if (!button->optype || (button->flag & ui::UI_HIDDEN)) {
            continue;
          }
          rcti rect;
          ui::button_to_pixelrect(&rect, &tools, &block, button.get());
          BLI_rcti_translate(&rect,
                             tools.winrct.xmin - viewport->winrct.xmin,
                             tools.winrct.ymin - viewport->winrct.ymin);
          if (rect.xmax > bounds[0] && rect.xmin < bounds[2] && rect.ymax > 0 &&
              rect.ymin < viewport->winy)
          {
            bounds[4] = std::min(bounds[4], rect.ymin - int(12.0f * UI_SCALE_FAC));
          }
        }
      }
    }
  }
  const ARegion *panel = view3d_agent_panel_region_find(area);
  if (!panel || !panel->runtime->visible || !panel->regiondata) {
    return;
  }
  if (const WorkspaceViewer *viewer = view3d_workspace_viewer_active()) {
    if (viewer->region && viewer->area == area) {
      return;
    }
  }
  const auto *runtime = static_cast<const AgentPanelRuntime *>(panel->regiondata);
  if (runtime->cards.is_empty()) {
    return;
  }
  const rcti &column = runtime->column_rect;
  if (BLI_rcti_size_x(&column) <= 0 || BLI_rcti_size_y(&column) <= 0) {
    return;
  }
  bounds[0] = panel->winrct.xmin - viewport->winrct.xmin + column.xmin;
  bounds[2] = panel->winrct.xmin - viewport->winrct.xmin + column.xmax + 1;
  bounds[3] = panel->winrct.ymin - viewport->winrct.ymin + column.ymax + 1;
}
}  // namespace blender
