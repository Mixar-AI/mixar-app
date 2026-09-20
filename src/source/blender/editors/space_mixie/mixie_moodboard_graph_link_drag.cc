/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The in-flight link drag: the noodle the user is dragging, and nothing else.
 *
 * Split out of `mixie_moodboard_graph_geometry.cc` for the 500-line rule. The
 * seam is real rather than arbitrary: everything here is RUNTIME STATE for one
 * gesture -- a process-global keyed on the scene's session UID -- while the
 * geometry file is pure functions of the scene. `LinkDragPreview`, its global
 * and `scene_drag_uid` are private to this translation unit and were used by
 * nothing else.
 */

/* Reaches `mixie_intern.hh` (the drag entry points' declarations) and
 * `DNA_scene_types.h` (Scene, and the ID whose session_uid keys the drag). */
#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

struct LinkDragPreview {
  /* Keyed on the scene's session UID rather than its pointer: a raw Scene *
   * kept in a static outlives the scene across a file load, and a freshly
   * allocated Scene landing on the same address would resurrect a stale drag
   * preview. Session UIDs are never reused within a session. */
  uint32_t scene_uid = 0;
  bool active = false;
  float x1 = 0.0f;
  float y1 = 0.0f;
  float x2 = 0.0f;
  float y2 = 0.0f;
};

static LinkDragPreview g_link_drag;

static uint32_t scene_drag_uid(const Scene *scene)
{
  return scene ? scene->id.session_uid : 0;
}

static bool link_drag_matches(const Scene *scene)
{
  const uint32_t uid = scene_drag_uid(scene);
  return g_link_drag.active && uid != 0 && g_link_drag.scene_uid == uid;
}

bool moodboard_graph_link_drag_active(Scene *scene)
{
  return link_drag_matches(scene);
}

void moodboard_graph_link_drag_begin(Scene *scene, const float x, const float y)
{
  g_link_drag = {scene_drag_uid(scene), true, x, y, x, y};
}

void moodboard_graph_link_drag_update(Scene *scene, const float x, const float y)
{
  if (link_drag_matches(scene)) {
    g_link_drag.x2 = x;
    g_link_drag.y2 = y;
  }
}

void moodboard_graph_link_drag_end(Scene *scene)
{
  if (link_drag_matches(scene)) {
    g_link_drag = {};
  }
}

void moodboard_graph_link_drag_reset()
{
  g_link_drag = {};
}

bool moodboard_graph_link_drag_preview(
    Scene *scene, float *r_x1, float *r_y1, float *r_x2, float *r_y2)
{
  if (!link_drag_matches(scene)) {
    return false;
  }
  *r_x1 = g_link_drag.x1;
  *r_y1 = g_link_drag.y1;
  *r_x2 = g_link_drag.x2;
  *r_y2 = g_link_drag.y2;
  return true;
}

}  // namespace blender::ed::mixie
