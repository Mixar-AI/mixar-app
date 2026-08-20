/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Blend and dither operations for image baking.
 */

#include "baking_ops_common.hh"

#include <algorithm>
#include <cmath>
#include <random>
#include <vector>

#include "DNA_image_types.h"

#include "BKE_image.hh"

#include "IMB_imbuf.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_enum_types.hh"

#include "WM_api.hh"
#include "WM_types.hh"

namespace blender::ed::baking {

/* -------------------------------------------------------------------- */
/** \name Blend Mode Enum
 * \{ */

enum BlendMode {
  BLEND_MIX = 0,
  BLEND_ADD = 1,
  BLEND_MULTIPLY = 2,
  BLEND_SCREEN = 3,
  BLEND_OVERLAY = 4,
  BLEND_SOFT_LIGHT = 5,
  BLEND_DIFFERENCE = 6,
};

static float blend_channel(float base, float blend, BlendMode mode)
{
  switch (mode) {
    case BLEND_MIX:
      return blend;
    case BLEND_ADD:
      return base + blend;
    case BLEND_MULTIPLY:
      return base * blend;
    case BLEND_SCREEN:
      return 1.0f - (1.0f - base) * (1.0f - blend);
    case BLEND_OVERLAY:
      if (base < 0.5f) {
        return 2.0f * base * blend;
      }
      return 1.0f - 2.0f * (1.0f - base) * (1.0f - blend);
    case BLEND_SOFT_LIGHT:
      if (blend < 0.5f) {
        return base - (1.0f - 2.0f * blend) * base * (1.0f - base);
      }
      return base + (2.0f * blend - 1.0f) * (std::sqrt(base) - base);
    case BLEND_DIFFERENCE:
      return std::abs(base - blend);
    default:
      return blend;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend Images Operator
 * \{ */

static wmOperatorStatus blend_images_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("blend_images");

  PointerRNA base_image_ptr = RNA_pointer_get(op->ptr, "base_image");
  PointerRNA blend_image_ptr = RNA_pointer_get(op->ptr, "blend_image");
  Image *base_image = static_cast<Image *>(base_image_ptr.data);
  Image *blend_image = static_cast<Image *>(blend_image_ptr.data);

  if (!base_image || !blend_image) {
    CLOG_WARN(LOG_BAKING, "blend_images: missing image(s)");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const float opacity = RNA_float_get(op->ptr, "opacity");
  const BlendMode mode = static_cast<BlendMode>(RNA_enum_get(op->ptr, "blend_mode"));

  log_image_op("blend_images", base_image, width, height);
  CLOG_INFO(LOG_BAKING, "blend_images: opacity=%.2f, mode=%d", opacity, static_cast<int>(mode));

  void *base_lock, *blend_lock;
  ImBuf *base_ibuf = BKE_image_acquire_ibuf(base_image, nullptr, &base_lock);
  ImBuf *blend_ibuf = BKE_image_acquire_ibuf(blend_image, nullptr, &blend_lock);

  if (!base_ibuf || !base_ibuf->float_buffer.data || !blend_ibuf ||
      !blend_ibuf->float_buffer.data)
  {
    CLOG_WARN(LOG_BAKING, "blend_images: failed to acquire image buffers");
    BKE_image_release_ibuf(base_image, base_ibuf, base_lock);
    BKE_image_release_ibuf(blend_image, blend_ibuf, blend_lock);
    return OPERATOR_CANCELLED;
  }

  float *base_pixels = base_ibuf->float_data_for_write();
  const float *blend_pixels = blend_ibuf->float_data_for_write();

#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int i = 0; i < width * height; ++i) {
    const int idx = i * CHANNELS;

    for (int c = 0; c < 3; ++c) {
      const float base_val = base_pixels[idx + c];
      const float blend_val = blend_pixels[idx + c];
      const float blended = blend_channel(base_val, blend_val, mode);
      /* Mix with opacity. */
      base_pixels[idx + c] = base_val + (blended - base_val) * opacity;
    }
    /* Blend alpha separately (always mix mode). */
    base_pixels[idx + 3] = base_pixels[idx + 3] +
                           (blend_pixels[idx + 3] - base_pixels[idx + 3]) * opacity;
  }

  BKE_image_mark_dirty(base_image, base_ibuf);
  BKE_image_release_ibuf(base_image, base_ibuf, base_lock);
  BKE_image_release_ibuf(blend_image, blend_ibuf, blend_lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, base_image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Dither Image Operator
 * \{ */

static wmOperatorStatus dither_image_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("dither_image");

  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    CLOG_WARN(LOG_BAKING, "dither_image: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const float amount = RNA_float_get(op->ptr, "amount");
  const int seed = RNA_int_get(op->ptr, "seed");

  log_image_op("dither_image", image, width, height);
  CLOG_INFO(LOG_BAKING, "dither_image: amount=%.4f, seed=%d", amount, seed);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "dither_image: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();

  /* Use deterministic noise based on seed for reproducibility. */
#ifdef _OPENMP
#  pragma omp parallel
  {
    std::mt19937 rng(seed + omp_get_thread_num());
    std::uniform_real_distribution<float> dist(-amount, amount);

#    pragma omp for
    for (int i = 0; i < width * height; ++i) {
      const int idx = i * CHANNELS;
      /* Re-seed based on pixel position for determinism across threads. */
      rng.seed(seed + i);

      for (int c = 0; c < 3; ++c) {
        pixels[idx + c] = std::clamp(pixels[idx + c] + dist(rng), 0.0f, 1.0f);
      }
      /* Don't dither alpha. */
    }
  }
#else
  std::mt19937 rng(seed);
  std::uniform_real_distribution<float> dist(-amount, amount);

  for (int i = 0; i < width * height; ++i) {
    const int idx = i * CHANNELS;
    for (int c = 0; c < 3; ++c) {
      pixels[idx + c] = std::clamp(pixels[idx + c] + dist(rng), 0.0f, 1.0f);
    }
  }
#endif

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
/** \name Blend Mode Enum Items
 * \{ */

static const EnumPropertyItem blend_mode_items[] = {
    {blender::ed::baking::BLEND_MIX, "MIX", 0, "Mix", "Simple alpha blend"},
    {blender::ed::baking::BLEND_ADD, "ADD", 0, "Add", "Additive blend"},
    {blender::ed::baking::BLEND_MULTIPLY, "MULTIPLY", 0, "Multiply", "Multiply blend"},
    {blender::ed::baking::BLEND_SCREEN, "SCREEN", 0, "Screen", "Screen blend"},
    {blender::ed::baking::BLEND_OVERLAY, "OVERLAY", 0, "Overlay", "Overlay blend"},
    {blender::ed::baking::BLEND_SOFT_LIGHT, "SOFT_LIGHT", 0, "Soft Light", "Soft light blend"},
    {blender::ed::baking::BLEND_DIFFERENCE, "DIFFERENCE", 0, "Difference", "Difference blend"},
    {0, nullptr, 0, nullptr, nullptr},
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Registration (C linkage)
 * \{ */

void BAKING_OT_blend_images(wmOperatorType *ot)
{
  ot->name = "Blend Images";
  ot->idname = "BAKING_OT_blend_images";
  ot->description = "Blend two images using various blend modes";

  ot->exec = blender::ed::baking::blend_images_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(
      ot->srna, "base_image", "Image", "Base Image", "Base image (modified in place)");
  RNA_def_pointer(ot->srna, "blend_image", "Image", "Blend Image", "Image to blend on top");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_float(ot->srna, "opacity", 1.0f, 0.0f, 1.0f, "Opacity", "", 0.0f, 1.0f);
  RNA_def_enum(ot->srna, "blend_mode", blend_mode_items, 0, "Blend Mode", "How to blend images");
}

void BAKING_OT_dither_image(wmOperatorType *ot)
{
  ot->name = "Dither Image";
  ot->idname = "BAKING_OT_dither_image";
  ot->description = "Add dithering noise to reduce banding artifacts";

  ot->exec = blender::ed::baking::dither_image_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_float(ot->srna,
                "amount",
                0.004f,
                0.0f,
                0.1f,
                "Amount",
                "Dither amount (1/255 ≈ 0.004 for 8-bit)",
                0.0f,
                0.1f);
  RNA_def_int(ot->srna, "seed", 0, 0, INT_MAX, "Seed", "Random seed for reproducibility", 0, 1000);
}

/** \} */
}  // namespace blender
