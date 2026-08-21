/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Statistics operations for image baking (min/max, normalize).
 */

#include "baking_ops_common.hh"

#include <algorithm>
#include <cmath>
#include <limits>
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
/** \name Get Image MinMax Operator
 * \{ */

static wmOperatorStatus get_image_minmax_exec(bContext * /*C*/, wmOperator *op)
{
  ScopedTimer timer("get_image_minmax");

  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    CLOG_WARN(LOG_BAKING, "get_image_minmax: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");

  log_image_op("get_image_minmax", image, width, height);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "get_image_minmax: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  const float *pixels = ibuf->float_data_for_write();
  const int total_pixels = width * height;

  float min_val = std::numeric_limits<float>::max();
  float max_val = std::numeric_limits<float>::lowest();

  /* Find min/max across RGB channels. */
#ifdef _OPENMP
#  pragma omp parallel for reduction(min : min_val) reduction(max : max_val) if (total_pixels > 4096)
#endif
  for (int i = 0; i < total_pixels; ++i) {
    const int idx = i * CHANNELS;
    /* Check RGB channels. */
    for (int c = 0; c < 3; ++c) {
      min_val = std::min(min_val, pixels[idx + c]);
      max_val = std::max(max_val, pixels[idx + c]);
    }
  }

  BKE_image_release_ibuf(image, ibuf, lock);

  /* Store results in operator properties for Python access. */
  RNA_float_set(op->ptr, "min_value", min_val);
  RNA_float_set(op->ptr, "max_value", max_val);

  CLOG_INFO(LOG_BAKING, "get_image_minmax: min=%.4f, max=%.4f", min_val, max_val);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Normalize Image Operator
 * \{ */

static wmOperatorStatus normalize_image_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("normalize_image");

  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    CLOG_WARN(LOG_BAKING, "normalize_image: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const float target_min = RNA_float_get(op->ptr, "target_min");
  const float target_max = RNA_float_get(op->ptr, "target_max");

  log_image_op("normalize_image", image, width, height);
  CLOG_INFO(LOG_BAKING, "normalize_image: target_min=%.2f, target_max=%.2f", target_min, target_max);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "normalize_image: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();
  const int total_pixels = width * height;

  /* First pass: find min/max. */
  float src_min = std::numeric_limits<float>::max();
  float src_max = std::numeric_limits<float>::lowest();

#ifdef _OPENMP
#  pragma omp parallel for reduction(min : src_min) reduction(max : src_max) if (total_pixels > 4096)
#endif
  for (int i = 0; i < total_pixels; ++i) {
    const int idx = i * CHANNELS;
    for (int c = 0; c < 3; ++c) {
      src_min = std::min(src_min, pixels[idx + c]);
      src_max = std::max(src_max, pixels[idx + c]);
    }
  }

  CLOG_INFO(LOG_BAKING, "normalize_image: source range [%.4f, %.4f]", src_min, src_max);

  /* Second pass: normalize. */
  const float src_range = src_max - src_min;
  const float target_range = target_max - target_min;

  if (src_range > 0.0001f) {
    const float scale = target_range / src_range;

#ifdef _OPENMP
#    pragma omp parallel for if (total_pixels > 4096)
#endif
    for (int i = 0; i < total_pixels; ++i) {
      const int idx = i * CHANNELS;
      for (int c = 0; c < 3; ++c) {
        pixels[idx + c] = (pixels[idx + c] - src_min) * scale + target_min;
      }
      /* Alpha unchanged. */
    }
  }
  else {
    CLOG_WARN(LOG_BAKING, "normalize_image: source range too small (%.6f), skipping", src_range);
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

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

void BAKING_OT_get_image_minmax(wmOperatorType *ot)
{
  ot->name = "Get Image MinMax";
  ot->idname = "BAKING_OT_get_image_minmax";
  ot->description = "Calculate minimum and maximum pixel values in image";

  ot->exec = blender::ed::baking::get_image_minmax_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer_runtime(ot->srna, "image", RNA_Image, "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);

  /* Output properties. */
  PropertyRNA *prop;
  prop = RNA_def_float(ot->srna, "min_value", 0.0f, -FLT_MAX, FLT_MAX, "Min Value", "Minimum pixel value found", -FLT_MAX, FLT_MAX);
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
  prop = RNA_def_float(ot->srna, "max_value", 1.0f, -FLT_MAX, FLT_MAX, "Max Value", "Maximum pixel value found", -FLT_MAX, FLT_MAX);
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}

void BAKING_OT_normalize_image(wmOperatorType *ot)
{
  ot->name = "Normalize Image";
  ot->idname = "BAKING_OT_normalize_image";
  ot->description = "Normalize image values to target range";

  ot->exec = blender::ed::baking::normalize_image_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer_runtime(ot->srna, "image", RNA_Image, "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_float(ot->srna, "target_min", 0.0f, -FLT_MAX, FLT_MAX, "Target Min", "", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "target_max", 1.0f, -FLT_MAX, FLT_MAX, "Target Max", "", 0.0f, 1.0f);
}

/** \} */
}  // namespace blender
