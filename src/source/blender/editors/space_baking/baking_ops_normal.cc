/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Normal map operations for image baking (height to normal, blend normal maps).
 */

#include "baking_ops_common.hh"

#include <algorithm>
#include <cmath>
#include <vector>

#include "DNA_image_types.h"

#include "BKE_image.hh"

#include "IMB_imbuf.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_prototypes.hh"

#include "WM_api.hh"
#include "WM_types.hh"

namespace blender::ed::baking {

/* -------------------------------------------------------------------- */
/** \name Height to Normal Operator
 * \{ */

static wmOperatorStatus height_to_normal_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("height_to_normal");

  Image *image = image_from_operator(C, op, "image");

  if (!image) {
    CLOG_WARN(LOG_BAKING, "height_to_normal: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const float strength = RNA_float_get(op->ptr, "strength");

  log_image_op("height_to_normal", image, width, height);
  CLOG_INFO(LOG_BAKING, "height_to_normal: strength=%.2f", strength);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "height_to_normal: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();

  /* Copy height values (use red channel as height). */
  std::vector<float> height_map(width * height);
  for (int i = 0; i < width * height; ++i) {
    height_map[i] = pixels[i * CHANNELS];
  }

  /* Compute normals using Sobel operator. */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 1; y < height - 1; ++y) {
    for (int x = 1; x < width - 1; ++x) {
      /* Sample 3x3 neighborhood. */
      const float tl = height_map[(y - 1) * width + (x - 1)];
      const float t = height_map[(y - 1) * width + x];
      const float tr = height_map[(y - 1) * width + (x + 1)];
      const float l = height_map[y * width + (x - 1)];
      const float r = height_map[y * width + (x + 1)];
      const float bl = height_map[(y + 1) * width + (x - 1)];
      const float b = height_map[(y + 1) * width + x];
      const float br = height_map[(y + 1) * width + (x + 1)];

      /* Sobel gradients. */
      const float dx = (tr + 2.0f * r + br) - (tl + 2.0f * l + bl);
      const float dy = (bl + 2.0f * b + br) - (tl + 2.0f * t + tr);

      /* Construct normal. */
      float nx = -dx * strength;
      float ny = -dy * strength;
      float nz = 1.0f;

      /* Normalize. */
      const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
      if (len > 0.0001f) {
        nx /= len;
        ny /= len;
        nz /= len;
      }

      /* Convert to tangent space normal map format [0, 1]. */
      const int idx = (y * width + x) * CHANNELS;
      pixels[idx + 0] = nx * 0.5f + 0.5f;
      pixels[idx + 1] = ny * 0.5f + 0.5f;
      pixels[idx + 2] = nz * 0.5f + 0.5f;
      /* Keep alpha unchanged. */
    }
  }

  /* Handle edges (set to flat normal). */
  for (int x = 0; x < width; ++x) {
    /* Top row. */
    int idx = x * CHANNELS;
    pixels[idx + 0] = 0.5f;
    pixels[idx + 1] = 0.5f;
    pixels[idx + 2] = 1.0f;

    /* Bottom row. */
    idx = ((height - 1) * width + x) * CHANNELS;
    pixels[idx + 0] = 0.5f;
    pixels[idx + 1] = 0.5f;
    pixels[idx + 2] = 1.0f;
  }
  for (int y = 0; y < height; ++y) {
    /* Left column. */
    int idx = (y * width) * CHANNELS;
    pixels[idx + 0] = 0.5f;
    pixels[idx + 1] = 0.5f;
    pixels[idx + 2] = 1.0f;

    /* Right column. */
    idx = (y * width + (width - 1)) * CHANNELS;
    pixels[idx + 0] = 0.5f;
    pixels[idx + 1] = 0.5f;
    pixels[idx + 2] = 1.0f;
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend Normal Maps Operator
 * \{ */

static wmOperatorStatus blend_normal_maps_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("blend_normal_maps");

  Image *base_image = image_from_operator(C, op, "base_image");
  Image *detail_image = image_from_operator(C, op, "detail_image");

  if (!base_image || !detail_image) {
    CLOG_WARN(LOG_BAKING, "blend_normal_maps: missing image(s)");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const float detail_strength = RNA_float_get(op->ptr, "detail_strength");

  log_image_op("blend_normal_maps", base_image, width, height);
  CLOG_INFO(LOG_BAKING, "blend_normal_maps: detail_strength=%.2f", detail_strength);

  void *base_lock, *detail_lock;
  ImBuf *base_ibuf = BKE_image_acquire_ibuf(base_image, nullptr, &base_lock);
  ImBuf *detail_ibuf = BKE_image_acquire_ibuf(detail_image, nullptr, &detail_lock);

  if (!base_ibuf || !base_ibuf->float_buffer.data || !detail_ibuf ||
      !detail_ibuf->float_buffer.data)
  {
    CLOG_WARN(LOG_BAKING, "blend_normal_maps: failed to acquire image buffers");
    BKE_image_release_ibuf(base_image, base_ibuf, base_lock);
    BKE_image_release_ibuf(detail_image, detail_ibuf, detail_lock);
    return OPERATOR_CANCELLED;
  }

  float *base_pixels = base_ibuf->float_data_for_write();
  const float *detail_pixels = detail_ibuf->float_data_for_write();

  /* Reoriented Normal Mapping (RNM) blend. */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int i = 0; i < width * height; ++i) {
    const int idx = i * CHANNELS;

    /* Unpack normals from [0,1] to [-1,1]. */
    float base_n[3] = {base_pixels[idx + 0] * 2.0f - 1.0f,
                       base_pixels[idx + 1] * 2.0f - 1.0f,
                       base_pixels[idx + 2] * 2.0f - 1.0f};

    float detail_n[3] = {detail_pixels[idx + 0] * 2.0f - 1.0f,
                         detail_pixels[idx + 1] * 2.0f - 1.0f,
                         detail_pixels[idx + 2] * 2.0f - 1.0f};

    /* Apply detail strength. */
    detail_n[0] *= detail_strength;
    detail_n[1] *= detail_strength;

    /* RNM blend: rotate detail normal by base normal. */
    /* This preserves detail orientation relative to base surface. */
    float t[3] = {base_n[2] + base_n[0], base_n[2] - base_n[0], base_n[1]};
    float u[3] = {-base_n[1], base_n[1], base_n[2]};

    float result[3];
    result[0] = t[0] * detail_n[0] + u[0] * detail_n[1] + base_n[0] * detail_n[2];
    result[1] = t[1] * detail_n[0] + u[1] * detail_n[1] + base_n[1] * detail_n[2];
    result[2] = t[2] * detail_n[0] + u[2] * detail_n[1] + base_n[2] * detail_n[2];

    /* Normalize. */
    const float len = std::sqrt(result[0] * result[0] + result[1] * result[1] +
                                result[2] * result[2]);
    if (len > 0.0001f) {
      result[0] /= len;
      result[1] /= len;
      result[2] /= len;
    }

    /* Pack back to [0,1]. */
    base_pixels[idx + 0] = result[0] * 0.5f + 0.5f;
    base_pixels[idx + 1] = result[1] * 0.5f + 0.5f;
    base_pixels[idx + 2] = result[2] * 0.5f + 0.5f;
    /* Keep alpha unchanged. */
  }

  BKE_image_mark_dirty(base_image, base_ibuf);
  BKE_image_release_ibuf(base_image, base_ibuf, base_lock);
  BKE_image_release_ibuf(detail_image, detail_ibuf, detail_lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, base_image);

  return OPERATOR_FINISHED;
}

/** \} */

}  // namespace blender::ed::baking


/* Mixar 5.2 port: operator registrations live in namespace blender
 * (wmOperatorType and the decls in baking_ops_common.hh moved there). */
namespace blender {
/* -------------------------------------------------------------------- */
/** \name Registration (C linkage)
 * \{ */

void BAKING_OT_height_to_normal(wmOperatorType *ot)
{
  ot->name = "Height to Normal";
  ot->idname = "BAKING_OT_height_to_normal";
  ot->description = "Convert height map to tangent space normal map";

  ot->exec = blender::ed::baking::height_to_normal_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  blender::ed::baking::define_image_name_property(ot->srna, "image", "Image");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_float(ot->srna, "strength", 1.0f, 0.01f, 10.0f, "Strength", "", 0.01f, 10.0f);
}

void BAKING_OT_blend_normal_maps(wmOperatorType *ot)
{
  ot->name = "Blend Normal Maps";
  ot->idname = "BAKING_OT_blend_normal_maps";
  ot->description = "Blend two normal maps using Reoriented Normal Mapping";

  ot->exec = blender::ed::baking::blend_normal_maps_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  blender::ed::baking::define_image_name_property(
      ot->srna, "base_image", "Base Image", "Base normal map (modified in place)");
  blender::ed::baking::define_image_name_property(
      ot->srna, "detail_image", "Detail Image", "Detail normal map to blend");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_float(ot->srna, "detail_strength", 1.0f, 0.0f, 2.0f, "Detail Strength", "", 0.0f, 2.0f);
}

/** \} */
}  // namespace blender
