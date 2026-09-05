/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * QA harness target provider for the Director timeline dock: exports the
 * strip, keyframe markers and timeline viewport from DirectorTimelineRuntime —
 * the SAME stored rects the interaction handler hit-tests against
 * (view3d_director_timeline_interaction.cc). Bounds there are region-local
 * pixels compared against event->mval, so conversion is a winrct offset.
 * Strictly read-only.
 */

#include <string>

#include "BLI_rect.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "../interface/interface_qa_inspect.hh"

#include "view3d_director_timeline.hh"

namespace {

bool region_rect_to_window(const ARegion *region, const rctf &rect, rcti *r_win)
{
  if (!(rect.xmax > rect.xmin) || !(rect.ymax > rect.ymin)) {
    return false;
  }
  r_win->xmin = region->winrct.xmin + int(rect.xmin);
  r_win->xmax = region->winrct.xmin + int(rect.xmax);
  r_win->ymin = region->winrct.ymin + int(rect.ymin);
  r_win->ymax = region->winrct.ymin + int(rect.ymax);
  return true;
}

void director_qa_targets(const wmWindow * /*win*/,
                         const ScrArea *area,
                         const ARegion *region,
                         std::vector<MixarQATarget> &r_targets)
{
  if (area->spacetype != SPACE_VIEW3D || region->regiontype != RGN_TYPE_CHANNELS) {
    return;
  }
  /* Read the runtime the way ``timeline_ui_handler`` does — never
   * ``runtime_ensure``: a dump must not allocate region data (and set
   * RGN_FLAG_TEMP_REGIONDATA) on a dock the user has not opened yet. No
   * runtime simply means no targets. */
  const DirectorTimelineRuntime *runtime = static_cast<const DirectorTimelineRuntime *>(
      region->regiondata);
  if (runtime == nullptr) {
    return;
  }

  MixarQATarget viewport;
  if (region_rect_to_window(region, runtime->viewport_bounds, &viewport.rect_win)) {
    viewport.surface = "director_timeline";
    viewport.text = "timeline";
    r_targets.push_back(std::move(viewport));
  }
  MixarQATarget strip;
  if (region_rect_to_window(region, runtime->strip_bounds, &strip.rect_win)) {
    strip.surface = "director_strip";
    strip.text = "strip";
    r_targets.push_back(std::move(strip));
  }
  for (const DirectorTimelineBeatHit &hit : runtime->beat_hits) {
    MixarQATarget t;
    if (!region_rect_to_window(region, hit.bounds, &t.rect_win)) {
      continue;
    }
    t.surface = "director_beat";
    t.text = "beat";
    t.index = hit.index;
    r_targets.push_back(std::move(t));
  }
}

}  // namespace

void view3d_director_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_VIEW3D, director_qa_targets);
}
