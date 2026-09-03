/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Graceful RNA bridge from Python-owned Director state to native drawing.
 */

#include <algorithm>

#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "view3d_director.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static PropertyRNA *director_prop(PointerRNA *ptr, const char *name)
{
  return ptr && ptr->data ? RNA_struct_find_property(ptr, name) : nullptr;
}

static bool director_bool(PointerRNA *ptr, const char *name, const bool fallback)
{
  PropertyRNA *prop = director_prop(ptr, name);
  return prop ? RNA_property_boolean_get(ptr, prop) : fallback;
}

static int director_int(PointerRNA *ptr, const char *name, const int fallback)
{
  PropertyRNA *prop = director_prop(ptr, name);
  return prop ? RNA_property_int_get(ptr, prop) : fallback;
}

static int director_enum(PointerRNA *ptr, const char *name, const int fallback)
{
  PropertyRNA *prop = director_prop(ptr, name);
  return prop ? RNA_property_enum_get(ptr, prop) : fallback;
}

bool view3d_director_state_pointer(Scene *scene, PointerRNA *r_state_ptr)
{
  if (!scene) {
    return false;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *state_prop = director_prop(&scene_ptr, "mixar_director");
  if (!state_prop) {
    return false;
  }
  *r_state_ptr = RNA_property_pointer_get(&scene_ptr, state_prop);
  return r_state_ptr->data != nullptr;
}

static bool director_active_shot_pointer_from_state(PointerRNA *state_ptr, PointerRNA *r_shot_ptr)
{
  PropertyRNA *shots_prop = director_prop(state_ptr, "shots");
  const int shot_count = shots_prop ? RNA_property_collection_length(state_ptr, shots_prop) : 0;
  if (shot_count <= 0) {
    return false;
  }
  const int shot_index = std::clamp(
      director_int(state_ptr, "active_shot_index", 0), 0, shot_count - 1);
  return RNA_property_collection_lookup_int(state_ptr, shots_prop, shot_index, r_shot_ptr);
}

bool view3d_director_active_shot_pointer(Scene *scene, PointerRNA *r_shot_ptr)
{
  PointerRNA state_ptr;
  return r_shot_ptr && view3d_director_state_pointer(scene, &state_ptr) &&
         director_active_shot_pointer_from_state(&state_ptr, r_shot_ptr);
}

bool view3d_director_state_read(Scene *scene, DirectorViewState *r_state)
{
  *r_state = DirectorViewState{};
  PointerRNA state_ptr;
  if (!view3d_director_state_pointer(scene, &state_ptr)) {
    return false;
  }

  r_state->available = true;
  r_state->active = director_bool(&state_ptr, "is_directing", false);
  r_state->timeline_expanded = director_bool(&state_ptr, "timeline_expanded", true);
  r_state->auto_key = director_bool(&state_ptr, "auto_key", false);
  /* `ruler_unit` is an enum whose MIN item is index 0. */
  r_state->ruler_minutes = director_enum(&state_ptr, "ruler_unit", 1) == 0;
  r_state->frame_current = scene->r.cfra;
  r_state->frame_start = scene->r.sfra;
  r_state->frame_end = scene->r.efra;
  r_state->scene_frame_start = scene->r.sfra;
  r_state->fps = (scene->r.frs_sec_base > 0.0f) ? float(scene->r.frs_sec) / scene->r.frs_sec_base :
                                                  24.0f;

  PointerRNA shot_ptr;
  if (!director_active_shot_pointer_from_state(&state_ptr, &shot_ptr)) {
    return true;
  }

  r_state->has_shot = true;
  r_state->shot_identity = shot_ptr.data;
  r_state->locked = director_enum(&shot_ptr, "state", 0) == 1;
  r_state->active_beat_index = director_int(&shot_ptr, "active_beat_index", 0);

  PropertyRNA *camera_prop = director_prop(&shot_ptr, "camera");
  if (camera_prop) {
    PointerRNA camera_ptr = RNA_property_pointer_get(&shot_ptr, camera_prop);
    Object *camera = static_cast<Object *>(camera_ptr.data);
    if (camera && camera->type == OB_CAMERA) {
      r_state->has_camera = true;
      r_state->camera_name = camera->id.name + 2;
    }
  }

  const int navigation_mode = director_enum(&state_ptr, "navigation_mode", 0);
  r_state->navigate_mode = navigation_mode == 0;
  r_state->explore_mode = navigation_mode == 2;
  PropertyRNA *beats_prop = director_prop(&shot_ptr, "beats");
  const int beat_count = beats_prop ? RNA_property_collection_length(&shot_ptr, beats_prop) : 0;
  r_state->beats.reserve(beat_count);
  for (int index = 0; index < beat_count; index++) {
    PointerRNA beat_ptr;
    if (!RNA_property_collection_lookup_int(&shot_ptr, beats_prop, index, &beat_ptr)) {
      continue;
    }
    DirectorBeatView beat;
    beat.index = index;
    beat.frame = director_int(&beat_ptr, "frame", scene->r.sfra);
    r_state->beats.append(beat);
  }

  if (!r_state->beats.is_empty()) {
    auto frame_less = [](const DirectorBeatView &a, const DirectorBeatView &b) {
      return a.frame < b.frame;
    };
    const auto bounds = std::minmax_element(
        r_state->beats.begin(), r_state->beats.end(), frame_less);
    r_state->frame_start = bounds.first->frame;
    r_state->frame_end = bounds.second->frame;
  }
  return true;
}
}  // namespace blender
