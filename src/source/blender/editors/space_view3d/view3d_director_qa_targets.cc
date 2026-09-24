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

#include <cmath>
#include <string>

#include "BLI_rect.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "UI_interface_c.hh"

#include "../interface/interface_qa_inspect.hh"

#include "view3d_director_cinema.hh"
#include "view3d_director_timeline.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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
  if (area->spacetype != SPACE_VIEW3D) {
    return;
  }
  /* Cinema Mode surface: the rows publish the very rects they laid their
   * buttons over, so the harness can tell apart controls that share one
   * operator id. */
  for (const CinemaQARecord &record : cinema_qa_records()) {
    if (record.region != region) {
      continue;
    }
    MixarQATarget target;
    if (!region_rect_to_window(region, record.rect, &target.rect_win)) {
      continue;
    }
    target.surface = record.surface;
    target.value = record.value;
    target.index = record.index;
    r_targets.push_back(std::move(target));
  }
  if (region->regiontype != RGN_TYPE_CHANNELS) {
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
  /* Every key column is a handle; the ones carrying a beat are also
   * published as that beat, indexed the way the shot's collection is. */
  for (const DirectorTimelineKeyHit &hit : runtime->key_hits) {
    MixarQATarget key;
    if (!region_rect_to_window(region, hit.bounds, &key.rect_win)) {
      continue;
    }
    key.surface = "director_key";
    key.text = hit.selected ? "key selected" : "key";
    key.index = int(std::lround(hit.frame));
    if (hit.beat >= 0) {
      MixarQATarget beat = key;
      beat.surface = "director_beat";
      beat.text = "beat";
      beat.index = hit.beat;
      r_targets.push_back(std::move(beat));
    }
    r_targets.push_back(std::move(key));
  }
}

}  // namespace

void view3d_director_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_VIEW3D, director_qa_targets);
}

}  // namespace blender
