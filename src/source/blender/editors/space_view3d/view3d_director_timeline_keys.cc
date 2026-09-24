/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The shot camera's own keyframes on the dock's strip, drawn the way the
 * Timeline draws them.
 *
 * The strip showed Director BEATS and nothing else. A recorded take keys
 * every frame the timeline plays (`director/core/record.py`, Blender's
 * `JITTER` key type) but mints beats only at the shot's cadence once playback
 * stops — so the Timeline showed a key on every frame while Cinema Mode
 * showed one a second, and nothing at all until the take ended.
 *
 * These marks are Blender's own: the keylist the Dope Sheet builds for an
 * object row (`ob_to_keylist`: the object's action and its camera data's, so
 * lens keys count too), drawn through `draw_keyframe_shape` and the keyframe
 * shader, so the shapes, per-type sizes and theme colours and the selection
 * are exactly the Timeline's. The only thing that differs is the transform:
 * the dock has no View2D, so each column is placed with the dock's own
 * frame->pixel mapping, in the pixel space the dock already draws in.
 *
 * They are marks, not handles. The beat diamonds drawn over them are still
 * what a click, a drag and a delete act on.
 */

#include "BLI_rect.h"

#include "DNA_action_types.h"
#include "DNA_object_types.h"
#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"

#include "ED_keyframes_draw.hh"
#include "ED_keyframes_keylist.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "view3d_director_timeline.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

void director_timeline_draw_native_keys(Object *camera,
                                        const DirectorTimelineRuntime &runtime,
                                        const ARegion *region,
                                        const float cy)
{
  const float width = BLI_rctf_size_x(&runtime.viewport_bounds);
  if (camera == nullptr || width <= 0.0f || runtime.view_span_frames <= 0.0f) {
    return;
  }
  const float view_start = runtime.view_start_frame;
  const float view_end = view_start + runtime.view_span_frames;

  /* No filters: every key the camera carries, whatever the selection. */
  bDopeSheet ads = {};
  AnimKeylist *keylist = ED_keylist_create();
  ob_to_keylist(&ads, camera, keylist, 0, {view_start, view_end});
  ED_keylist_prepare_for_direct_access(keylist);
  const int64_t key_len = ED_keylist_array_len(keylist);
  const ActKeyColumn *keys = ED_keylist_array(keylist);

  int visible = 0;
  for (int64_t index = 0; index < key_len; index++) {
    visible += int(IN_RANGE_INCL(keys[index].cfra, view_start, view_end));
  }
  if (visible == 0) {
    ED_keylist_free(keylist);
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
  immBegin(GPU_PRIM_POINTS, visible);

  /* The Timeline's key size (`channel_ui_data_init`: half a widget unit);
   * `draw_keyframe_shape` scales it per key type, as it does there. */
  const float icon_size = float(U.widget_unit) * 0.5f;
  for (int64_t index = 0; index < key_len; index++) {
    const ActKeyColumn &key = keys[index];
    if (!IN_RANGE_INCL(key.cfra, view_start, view_end)) {
      continue;
    }
    const float x = runtime.viewport_bounds.xmin +
                    (key.cfra - view_start) / runtime.view_span_frames * width;
    draw_keyframe_shape(x,
                        cy,
                        icon_size,
                        (key.sel & SELECT) != 0,
                        key.key_type,
                        KEYFRAME_SHAPE_BOTH,
                        1.0f,
                        &sh_bindings,
                        KEYFRAME_HANDLE_NONE,
                        KEYFRAME_EXTREME_NONE);
  }

  immEnd();
  GPU_program_point_size(false);
  immUnbindProgram();
  ED_keylist_free(keylist);
}

}  // namespace blender
