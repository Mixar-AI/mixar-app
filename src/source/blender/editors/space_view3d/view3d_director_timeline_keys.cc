/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The shot camera's own keyframes on the dock's strip, drawn — and hit —
 * the way the Timeline draws them.
 *
 * Every mark is a COLUMN of the camera's native keys: the keys of every
 * F-curve that share a frame, which is the unit the Timeline draws and
 * selects. A recorded take keys every frame the timeline plays
 * (`director/core/record.py`), so the dock shows a key on every frame, as
 * the Timeline does, and every one of them is a real handle: a click, a
 * drag, a box and a delete act on Blender's own keys
 * (`mixar.director_*_keys`). A Director beat is metadata ON a column, drawn
 * as a ring around its key when it carries an image
 * (view3d_director_timeline_draw.cc).
 *
 * The marks are Blender's own: the keylist the Dope Sheet builds for an
 * object row (`ob_to_keylist`: the object's action and its camera data's, so
 * lens keys count too), drawn through the keyframe shader, so the per-type
 * sizes and the selection are exactly the Timeline's. Two things differ. The
 * transform: the dock has no View2D, so each column is placed with the dock's
 * own frame->pixel mapping, in the pixel space the dock already draws in. And
 * the mark: a green DOT in Director's accent rather than the theme's
 * per-key-type diamonds (`emit_key_dot`).
 */

#include <algorithm>
#include <cfloat>
#include <cmath>

#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_action_types.h"
#include "DNA_anim_types.h"
#include "DNA_camera_types.h"
#include "DNA_curve_types.h"
#include "DNA_object_types.h"
#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"

#include "ANIM_animdata.hh"

#include "ED_keyframes_draw.hh"
#include "ED_keyframes_keylist.hh"

#include "GPU_immediate.hh"
#include "GPU_shader_shared.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"

#include "view3d_director_timeline.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** A beat's frame is an integer; its key is the column that rounds to it
 * (`BEAT_EPSILON` in `core/native_keys.py`, which matches the same way). */
constexpr float BEAT_EPSILON = 0.5f;

/* Director's key is a GREEN DOT, not the Timeline's white diamond: the dock
 * is one camera's row on a neutral grey span, so the marks carry Director's
 * own accent and the theme's per-type colours (white keyframes, green jitter
 * samples) would only say which recorder wrote them. Selection is the
 * brighter green — the shape never changes, so a dense take still reads. */
constexpr uchar KEY_FILL[4] = {40, 179, 102, 255};
constexpr uchar KEY_FILL_SELECTED[4] = {104, 240, 152, 255};
/** The dark rim that holds a dot off the span behind it. */
constexpr uchar KEY_OUTLINE[4] = {10, 26, 18, 210};
constexpr uchar KEY_OUTLINE_SELECTED[4] = {255, 255, 255, 235};

/**
 * One key column as a dot, in the keyframe shader's vertex attributes.
 *
 * `draw_keyframe_shape` would read the fill from the THEME's key-type slots,
 * which is the one thing the dock does differently; its per-type size scaling
 * is kept, so recorded samples stay smaller than the keys a capture wrote.
 */
void emit_key_dot(const float x,
                  const float y,
                  float size,
                  const bool selected,
                  const eBezTriple_KeyframeType key_type,
                  const KeyframeShaderBindings &sh_bindings)
{
  switch (key_type) {
    case BEZT_KEYTYPE_BREAKDOWN:
      size *= 0.85f;
      break;
    case BEZT_KEYTYPE_MOVEHOLD:
      size *= 0.925f;
      break;
    case BEZT_KEYTYPE_EXTREME:
      size *= 1.2f;
      break;
    case BEZT_KEYTYPE_JITTER:
      size *= 0.8f;
      break;
    case BEZT_KEYTYPE_GENERATED:
      size *= 0.75f;
      break;
    case BEZT_KEYTYPE_KEYFRAME:
      break;
  }
  immAttr1f(sh_bindings.size_id, size);
  immAttr4ubv(sh_bindings.color_id, selected ? KEY_FILL_SELECTED : KEY_FILL);
  immAttr4ubv(sh_bindings.outline_color_id, selected ? KEY_OUTLINE_SELECTED : KEY_OUTLINE);
  immAttr1u(sh_bindings.flags_id, uint32_t(GPU_KEYFRAME_SHAPE_CIRCLE));
  immVertex2f(sh_bindings.pos_id, x, y);
}

/** Every F-curve the dock draws for \a camera: the object's and its data's —
 * the same two `ob_to_keylist` gathers for an object row. */
template<typename Fn> void foreach_camera_fcurve(const Object *camera, Fn fn)
{
  const AnimData *owners[2] = {
      camera->adt,
      camera->data ? id_cast<const Camera *>(camera->data)->adt : nullptr};
  for (const AnimData *adt : owners) {
    for (const FCurve *fcu : animrig::fcurves_for_assigned_action(adt)) {
      if (fcu->bezt != nullptr) {
        fn(*fcu);
      }
    }
  }
}

}  // namespace

bool director_timeline_collect_keys(Object *camera,
                                    DirectorTimelineRuntime *runtime,
                                    const float strip_y,
                                    const float strip_h,
                                    float *r_first,
                                    float *r_last)
{
  runtime->key_hits.clear();
  const float width = BLI_rctf_size_x(&runtime->viewport_bounds);
  if (camera == nullptr || width <= 0.0f || runtime->view_span_frames <= 0.0f) {
    return false;
  }
  const float view_start = runtime->view_start_frame;
  const float view_end = view_start + runtime->view_span_frames;

  /* No filters: every key the camera carries, whatever the selection. */
  bDopeSheet ads = {};
  AnimKeylist *keylist = ED_keylist_create();
  ob_to_keylist(&ads, camera, keylist, 0, {view_start, view_end});
  ED_keylist_prepare_for_direct_access(keylist);
  const int64_t key_len = ED_keylist_array_len(keylist);
  const ActKeyColumn *keys = ED_keylist_array(keylist);
  if (key_len == 0) {
    ED_keylist_free(keylist);
    return false;
  }
  /* The keylist holds the nearest key past each edge of the view as well,
   * so its ends are where the camera's animation continues off screen. */
  *r_first = keys[0].cfra;
  *r_last = keys[key_len - 1].cfra;

  const float u = UI_SCALE_FAC;
  const float frames_to_px = width / runtime->view_span_frames;
  for (int64_t index = 0; index < key_len; index++) {
    const ActKeyColumn &key = keys[index];
    if (!IN_RANGE_INCL(key.cfra, view_start, view_end)) {
      continue;
    }
    DirectorTimelineKeyHit hit;
    hit.frame = key.cfra;
    hit.x = runtime->viewport_bounds.xmin + (key.cfra - view_start) * frames_to_px;
    hit.selected = (key.sel & SELECT) != 0;
    hit.key_type = int(key.key_type);
    /* Wide enough to aim at, never wider than the gap to the next column:
     * a take keyed every frame puts columns a few pixels apart, and the
     * nearest one wins inside a shared rect (`key_at_event`). */
    const float half = std::max(3.0f * u, std::min(10.0f * u, frames_to_px * 0.5f));
    hit.bounds = {hit.x - half, hit.x + half, strip_y - 4.0f * u, strip_y + strip_h + 4.0f * u};
    runtime->key_hits.append(hit);
  }
  ED_keylist_free(keylist);
  return true;
}

void director_timeline_draw_keys(const DirectorTimelineRuntime &runtime,
                                 const ARegion *region,
                                 const float cy)
{
  if (runtime.key_hits.is_empty()) {
    return;
  }
  /* The Timeline's own setup (`channel_list_draw_keys`, keyframes_draw.cc). */
  GPU_blend(GPU_BLEND_ALPHA);
  GPUVertFormat *format = immVertexFormat();
  KeyframeShaderBindings sh_bindings;
  sh_bindings.pos_id = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  sh_bindings.size_id = GPU_vertformat_attr_add(format, "size", gpu::VertAttrType::SFLOAT_32);
  sh_bindings.color_id = GPU_vertformat_attr_add(
      format, "color", gpu::VertAttrType::UNORM_8_8_8_8);
  sh_bindings.outline_color_id = GPU_vertformat_attr_add(
      format, "outlineColor", gpu::VertAttrType::UNORM_8_8_8_8);
  sh_bindings.flags_id = GPU_vertformat_attr_add(format, "flags", gpu::VertAttrType::UINT_32);

  GPU_program_point_size(true);
  immBindBuiltinProgram(GPU_SHADER_KEYFRAME_SHAPE);
  immUniform1f("outline_scale", 1.0f);
  /* The shader snaps to the pixel grid of this size; the dock draws in its
   * region's own pixel space. */
  immUniform2f("ViewportSize", float(region->winx), float(region->winy));
  immBegin(GPU_PRIM_POINTS, int(runtime.key_hits.size()));

  /* The Timeline's key size (`channel_ui_data_init`: half a widget unit);
   * `draw_keyframe_shape` scales it per key type, as it does there. */
  const float icon_size = float(U.widget_unit) * 0.5f;
  for (const DirectorTimelineKeyHit &hit : runtime.key_hits) {
    emit_key_dot(hit.x,
                 cy,
                 icon_size,
                 hit.selected,
                 eBezTriple_KeyframeType(hit.key_type),
                 sh_bindings);
  }

  immEnd();
  GPU_program_point_size(false);
  immUnbindProgram();
}

bool director_timeline_camera_key_range(Object *camera, float *r_first, float *r_last)
{
  if (camera == nullptr) {
    return false;
  }
  float first = FLT_MAX;
  float last = -FLT_MAX;
  foreach_camera_fcurve(camera, [&](const FCurve &fcu) {
    for (uint i = 0; i < fcu.totvert; i++) {
      first = std::min(first, fcu.bezt[i].vec[1][0]);
      last = std::max(last, fcu.bezt[i].vec[1][0]);
    }
  });
  if (first > last) {
    return false;
  }
  *r_first = first;
  *r_last = last;
  return true;
}

bool view3d_director_timeline_selection(const bContext *C, blender::Vector<int> *r_selected)
{
  r_selected->clear();
  DirectorViewState state;
  if (!view3d_director_state_read(CTX_data_scene(C), &state) || state.shot_camera == nullptr ||
      state.beats.is_empty())
  {
    return false;
  }
  blender::Vector<float> selected;
  foreach_camera_fcurve(state.shot_camera, [&](const FCurve &fcu) {
    for (uint i = 0; i < fcu.totvert; i++) {
      if (BEZT_ISSEL_ANY(&fcu.bezt[i])) {
        selected.append(fcu.bezt[i].vec[1][0]);
      }
    }
  });
  if (selected.is_empty()) {
    return false;
  }
  std::sort(selected.begin(), selected.end());
  for (const DirectorBeatView &beat : state.beats) {
    const float frame = float(beat.frame);
    const float *found = std::lower_bound(selected.begin(), selected.end(), frame - BEAT_EPSILON);
    if (found != selected.end() && *found <= frame + BEAT_EPSILON) {
      r_selected->append(beat.index);
    }
  }
  return !r_selected->is_empty();
}

}  // namespace blender
