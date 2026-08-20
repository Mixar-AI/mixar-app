/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spimage
 *
 * UV edit helper functions and transform callback for Mixar UV sidebar panels.
 */

#include <cmath>

#include "MEM_guardedalloc.h"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_view3d_types.h"

#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_customdata.hh"
#include "BKE_editmesh.hh"
#include "BKE_layer.hh"
#include "BKE_screen.hh"

#include "DEG_depsgraph.hh"

#include "ED_image.hh"
#include "ED_uvedit.hh"

#include "WM_api.hh"

#include "RNA_access.hh"

#include "image_mixar_uv_panels.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

using blender::Span;
using blender::Vector;

/* -------------------------------------------------------------------- */
/** \name Shared State
 * \{ */

float mixar_uv_vertex_old_center[2];
float mixar_uv_vertex_old_angle = 0.0f;
float mixar_uv_vertex_applied_angle = 0.0f;
float mixar_uv_size_target[2] = {0.0f, 0.0f};
int mixar_uv_pivot_point = V3D_AROUND_CENTER_BOUNDS;
float mixar_uv_cursor_edit[2] = {0.0f, 0.0f};
float mixar_uv_arrange_margin = 0.001f;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Context Helper
 * \{ */

ARegion *mixar_uv_find_window_region(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  if (area == nullptr) {
    return nullptr;
  }
  return BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name UV Edit Helpers
 * \{ */

int mixar_uvedit_center(Scene *scene, const Span<Object *> objects, float center[2])
{
  BMFace *f;
  BMLoop *l;
  BMIter iter, liter;
  float *luv;
  int tot = 0;

  zero_v2(center);

  for (Object *obedit : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(obedit);
    const BMUVOffsets offsets = BM_uv_map_offsets_get(em->bm);

    BM_ITER_MESH (f, &iter, em->bm, BM_FACES_OF_MESH) {
      if (!uvedit_face_visible_test(scene, f)) {
        continue;
      }

      BM_ITER_ELEM (l, &liter, f, BM_LOOPS_OF_FACE) {
        if (uvedit_uv_select_test(scene, em->bm, l, offsets)) {
          luv = BM_ELEM_CD_GET_FLOAT_P(l, offsets.uv);
          add_v2_v2(center, luv);
          tot++;
        }
      }
    }
  }

  if (tot > 0) {
    center[0] /= tot;
    center[1] /= tot;
  }

  return tot;
}

static void mixar_uvedit_translate(Scene *scene,
                                   const Span<Object *> objects,
                                   const float delta[2])
{
  BMFace *f;
  BMLoop *l;
  BMIter iter, liter;
  float *luv;

  for (Object *obedit : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(obedit);
    const BMUVOffsets offsets = BM_uv_map_offsets_get(em->bm);

    BM_ITER_MESH (f, &iter, em->bm, BM_FACES_OF_MESH) {
      if (!uvedit_face_visible_test(scene, f)) {
        continue;
      }

      BM_ITER_ELEM (l, &liter, f, BM_LOOPS_OF_FACE) {
        if (uvedit_uv_select_test(scene, em->bm, l, offsets)) {
          luv = BM_ELEM_CD_GET_FLOAT_P(l, offsets.uv);
          add_v2_v2(luv, delta);
        }
      }
    }
  }
}

static void mixar_uvedit_rotate(Scene *scene,
                                const Span<Object *> objects,
                                const float center[2],
                                float angle)
{
  BMFace *f;
  BMLoop *l;
  BMIter iter, liter;
  float *luv;

  float cos_angle = cosf(angle);
  float sin_angle = sinf(angle);

  for (Object *obedit : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(obedit);
    const BMUVOffsets offsets = BM_uv_map_offsets_get(em->bm);

    BM_ITER_MESH (f, &iter, em->bm, BM_FACES_OF_MESH) {
      if (!uvedit_face_visible_test(scene, f)) {
        continue;
      }

      BM_ITER_ELEM (l, &liter, f, BM_LOOPS_OF_FACE) {
        if (uvedit_uv_select_test(scene, em->bm, l, offsets)) {
          luv = BM_ELEM_CD_GET_FLOAT_P(l, offsets.uv);

          float uv[2] = {luv[0] - center[0], luv[1] - center[1]};

          luv[0] = cos_angle * uv[0] - sin_angle * uv[1] + center[0];
          luv[1] = sin_angle * uv[0] + cos_angle * uv[1] + center[1];
        }
      }
    }
  }
}

static void mixar_uvedit_scale(Scene *scene,
                               const Span<Object *> objects,
                               const float center[2],
                               const float scale[2])
{
  BMFace *f;
  BMLoop *l;
  BMIter iter, liter;
  float *luv;

  for (Object *obedit : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(obedit);
    const BMUVOffsets offsets = BM_uv_map_offsets_get(em->bm);

    BM_ITER_MESH (f, &iter, em->bm, BM_FACES_OF_MESH) {
      if (!uvedit_face_visible_test(scene, f)) {
        continue;
      }

      BM_ITER_ELEM (l, &liter, f, BM_LOOPS_OF_FACE) {
        if (uvedit_uv_select_test(scene, em->bm, l, offsets)) {
          luv = BM_ELEM_CD_GET_FLOAT_P(l, offsets.uv);
          luv[0] = (luv[0] - center[0]) * scale[0] + center[0];
          luv[1] = (luv[1] - center[1]) * scale[1] + center[1];
        }
      }
    }
  }
}

bool mixar_uvedit_bounds(Scene *scene,
                         const Span<Object *> objects,
                         float min_uv[2],
                         float max_uv[2])
{
  BMFace *f;
  BMLoop *l;
  BMIter iter, liter;
  float *luv;
  bool found = false;

  INIT_MINMAX2(min_uv, max_uv);

  for (Object *obedit : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(obedit);
    const BMUVOffsets offsets = BM_uv_map_offsets_get(em->bm);

    BM_ITER_MESH (f, &iter, em->bm, BM_FACES_OF_MESH) {
      if (!uvedit_face_visible_test(scene, f)) {
        continue;
      }

      BM_ITER_ELEM (l, &liter, f, BM_LOOPS_OF_FACE) {
        if (uvedit_uv_select_test(scene, em->bm, l, offsets)) {
          luv = BM_ELEM_CD_GET_FLOAT_P(l, offsets.uv);
          minmax_v2v2_v2(min_uv, max_uv, luv);
          found = true;
        }
      }
    }
  }

  return found;
}

static bool mixar_uvedit_active(Scene *scene, const Span<Object *> objects, float center[2])
{
  for (Object *obedit : objects) {
    BMEditMesh *em = BKE_editmesh_from_object(obedit);
    const BMUVOffsets offsets = BM_uv_map_offsets_get(em->bm);

    BMFace *efa = BM_mesh_active_face_get(em->bm, true, false);
    if (efa) {
      BMLoop *l;
      BMIter liter;
      BM_ITER_ELEM (l, &liter, efa, BM_LOOPS_OF_FACE) {
        if (uvedit_uv_select_test(scene, em->bm, l, offsets)) {
          float *luv = BM_ELEM_CD_GET_FLOAT_P(l, offsets.uv);
          copy_v2_v2(center, luv);
          return true;
        }
      }
    }
  }
  return false;
}

static bool mixar_uvedit_pivot_center(Scene *scene,
                                      SpaceImage *sima,
                                      const Span<Object *> objects,
                                      int pivot,
                                      float center[2])
{
  switch (pivot) {
    case V3D_AROUND_CENTER_BOUNDS: {
      float min_uv[2], max_uv[2];
      if (mixar_uvedit_bounds(scene, objects, min_uv, max_uv)) {
        mid_v2_v2v2(center, min_uv, max_uv);
        return true;
      }
      return false;
    }
    case V3D_AROUND_CURSOR:
      copy_v2_v2(center, sima->cursor);
      return true;
    case V3D_AROUND_CENTER_MEDIAN:
    case V3D_AROUND_LOCAL_ORIGINS:
      return mixar_uvedit_center(scene, objects, center) > 0;
    case V3D_AROUND_ACTIVE:
      if (mixar_uvedit_active(scene, objects, center)) {
        return true;
      }
      return mixar_uvedit_center(scene, objects, center) > 0;
    default:
      return mixar_uvedit_center(scene, objects, center) > 0;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Transform Callback
 * \{ */

void do_mixar_uvedit_transform(bContext *C, void * /*arg*/, int event)
{
  if (event != B_MIXAR_UVEDIT_VERTEX && event != B_MIXAR_UVEDIT_ROTATE &&
      event != B_MIXAR_UVEDIT_SCALE && event != B_MIXAR_UVEDIT_CURSOR &&
      event != B_MIXAR_UVEDIT_ARRANGE && event != B_MIXAR_UVEDIT_MOVE_AXIS &&
      event != B_MIXAR_UVEDIT_PIVOT) {
    return;
  }

  /* Switch region to WINDOW for UV operations (area is already IMAGE_EDITOR) */
  ARegion *window_region = mixar_uv_find_window_region(C);
  if (window_region == nullptr) {
    return;
  }

  ARegion *region_prev = CTX_wm_region(C);
  CTX_wm_region_set(C, window_region);

  SpaceImage *sima = CTX_wm_space_image(C);
  Scene *scene = CTX_data_scene(C);
  float center[2];

  Vector<Object *> objects = BKE_view_layer_array_from_objects_in_edit_mode_unique_data_with_uvs(
      scene, CTX_data_view_layer(C), CTX_wm_view3d(C));

  mixar_uvedit_center(scene, objects, center);

  if (event == B_MIXAR_UVEDIT_VERTEX) {
    float delta[2];
    int imx, imy;

    ED_space_image_get_size(sima, &imx, &imy);

    if (sima->flag & SI_COORDFLOATS) {
      delta[0] = mixar_uv_vertex_old_center[0] - center[0];
      delta[1] = mixar_uv_vertex_old_center[1] - center[1];
    }
    else {
      delta[0] = mixar_uv_vertex_old_center[0] / imx - center[0];
      delta[1] = mixar_uv_vertex_old_center[1] / imy - center[1];
    }

    mixar_uvedit_translate(scene, objects, delta);
  }
  else if (event == B_MIXAR_UVEDIT_ROTATE) {
    float delta_angle = mixar_uv_vertex_old_angle - mixar_uv_vertex_applied_angle;

    if (fabsf(delta_angle) > 0.0001f) {
      float angle_rad = DEG2RADF(delta_angle);

      /* Delegate to Blender's `transform.rotate` operator — the same
       * one R-key invokes. It already iterates UV islands correctly
       * for every pivot mode, including `Individual Origins`, where
       * each island spins around its own center. The previous custom
       * routine reduced the pivot to a single point (the global
       * median for both `MEDIAN` and `LOCAL_ORIGINS`), which made
       * Individual-Origin rotation visually identical to Median. */
      wmOperatorType *ot = WM_operatortype_find("TRANSFORM_OT_rotate", false);
      if (ot != nullptr) {
        PointerRNA op_ptr;
        WM_operator_last_properties_ensure(ot, &op_ptr);
        RNA_float_set(&op_ptr, "value", angle_rad);
        WM_operator_name_call(C,
                              "TRANSFORM_OT_rotate",
                              blender::wm::OpCallContext::ExecDefault,
                              &op_ptr,
                              nullptr);
      }

      mixar_uv_vertex_applied_angle = mixar_uv_vertex_old_angle;
    }
  }
  else if (event == B_MIXAR_UVEDIT_SCALE) {
    float min_uv[2], max_uv[2];
    if (mixar_uvedit_bounds(scene, objects, min_uv, max_uv)) {
      float current_size[2] = {max_uv[0] - min_uv[0], max_uv[1] - min_uv[1]};

      float scale[2] = {1.0f, 1.0f};
      if (current_size[0] > 0.0001f && mixar_uv_size_target[0] > 0.0001f) {
        scale[0] = mixar_uv_size_target[0] / current_size[0];
      }
      if (current_size[1] > 0.0001f && mixar_uv_size_target[1] > 0.0001f) {
        scale[1] = mixar_uv_size_target[1] / current_size[1];
      }

      mixar_uvedit_scale(scene, objects, center, scale);
    }
  }
  else if (event == B_MIXAR_UVEDIT_CURSOR) {
    int imx, imy;
    ED_space_image_get_size(sima, &imx, &imy);

    if (sima->flag & SI_COORDFLOATS) {
      copy_v2_v2(sima->cursor, mixar_uv_cursor_edit);
    }
    else {
      sima->cursor[0] = mixar_uv_cursor_edit[0] / float(imx);
      sima->cursor[1] = mixar_uv_cursor_edit[1] / float(imy);
    }
  }
  else if (event == B_MIXAR_UVEDIT_ARRANGE) {
    wmOperatorType *ot = WM_operatortype_find("UV_OT_arrange_islands", false);
    if (ot) {
      PointerRNA op_ptr;
      WM_operator_last_properties_ensure(ot, &op_ptr);
      RNA_float_set(&op_ptr, "margin", mixar_uv_arrange_margin);
      WM_operator_name_call(
          C, "UV_OT_arrange_islands", blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
    }
  }
  else if (event == B_MIXAR_UVEDIT_MOVE_AXIS) {
    wmOperatorType *ot = WM_operatortype_find("UV_OT_move_on_axis", false);
    if (ot) {
      PointerRNA op_ptr;
      WM_operator_last_properties_ensure(ot, &op_ptr);
      /* Distance is now edited directly through the panel's RNA-bound
       * `distance` prop row, so the value is already up-to-date here —
       * no `RNA_int_set` write-back needed. */
      WM_operator_name_call(
          C, "MIXAR_OT_move_on_axis", blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
    }
  }
  else if (event == B_MIXAR_UVEDIT_PIVOT) {
    sima->around = mixar_uv_pivot_point;
  }

  WM_event_add_notifier(C, NC_IMAGE, sima->image);
  for (Object *obedit : objects) {
    DEG_id_tag_update((ID *)obedit->data, ID_RECALC_GEOMETRY);
  }

  /* Restore original region */
  CTX_wm_region_set(C, region_prev);
}

/** \} */
}  // namespace blender
