/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Color space conversion operations for image baking.
 */

#include "baking_ops_common.hh"

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
/** \name Pixels to sRGB Operator
 * \{ */

static wmOperatorStatus pixels_to_srgb_exec(bContext *C, wmOperator *op)
{
  /* Get RNA properties. */
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int start_x = RNA_int_get(op->ptr, "start_x");
  const int start_y = RNA_int_get(op->ptr, "start_y");
  const int convert_width = RNA_int_get(op->ptr, "convert_width");
  const int convert_height = RNA_int_get(op->ptr, "convert_height");

  /* Acquire image buffer. */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();

  /* Convert linear to sRGB. */
#ifdef _OPENMP
#  pragma omp parallel for if (convert_height > 64)
#endif
  for (int y = 0; y < convert_height; ++y) {
    const int row_start = ((start_y + y) * width + start_x) * CHANNELS;
    for (int x = 0; x < convert_width; ++x) {
      const int idx = row_start + x * CHANNELS;
      pixels[idx + 0] = linear_to_srgb(pixels[idx + 0]);
      pixels[idx + 1] = linear_to_srgb(pixels[idx + 1]);
      pixels[idx + 2] = linear_to_srgb(pixels[idx + 2]);
      /* Alpha unchanged */
    }
  }

  /* Mark dirty and release. */
  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  /* Notify. */
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Pixels to Linear Operator
 * \{ */

static wmOperatorStatus pixels_to_linear_exec(bContext *C, wmOperator *op)
{
  /* Get RNA properties. */
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int start_x = RNA_int_get(op->ptr, "start_x");
  const int start_y = RNA_int_get(op->ptr, "start_y");
  const int convert_width = RNA_int_get(op->ptr, "convert_width");
  const int convert_height = RNA_int_get(op->ptr, "convert_height");

  /* Acquire image buffer. */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();

  /* Convert sRGB to linear. */
#ifdef _OPENMP
#  pragma omp parallel for if (convert_height > 64)
#endif
  for (int y = 0; y < convert_height; ++y) {
    const int row_start = ((start_y + y) * width + start_x) * CHANNELS;
    for (int x = 0; x < convert_width; ++x) {
      const int idx = row_start + x * CHANNELS;
      pixels[idx + 0] = srgb_to_linear(pixels[idx + 0]);
      pixels[idx + 1] = srgb_to_linear(pixels[idx + 1]);
      pixels[idx + 2] = srgb_to_linear(pixels[idx + 2]);
      /* Alpha unchanged */
    }
  }

  /* Mark dirty and release. */
  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  /* Notify. */
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Batch sRGB to Linear Operator
 * \{ */

static wmOperatorStatus batch_srgb_to_linear_exec(bContext *C, wmOperator *op)
{
  /* Get RNA properties. */
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const bool convert_r = RNA_boolean_get(op->ptr, "convert_r");
  const bool convert_g = RNA_boolean_get(op->ptr, "convert_g");
  const bool convert_b = RNA_boolean_get(op->ptr, "convert_b");

  /* Acquire image buffer. */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();
  const int total_pixels = width * height;

  /* Convert sRGB to linear for selected channels. */
#ifdef _OPENMP
#  pragma omp parallel for if (total_pixels > 4096)
#endif
  for (int i = 0; i < total_pixels; ++i) {
    const int idx = i * CHANNELS;
    if (convert_r) {
      pixels[idx + 0] = srgb_to_linear(pixels[idx + 0]);
    }
    if (convert_g) {
      pixels[idx + 1] = srgb_to_linear(pixels[idx + 1]);
    }
    if (convert_b) {
      pixels[idx + 2] = srgb_to_linear(pixels[idx + 2]);
    }
    /* Alpha unchanged */
  }

  /* Mark dirty and release. */
  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  /* Notify. */
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Batch Linear to sRGB Operator
 * \{ */

static wmOperatorStatus batch_linear_to_srgb_exec(bContext *C, wmOperator *op)
{
  /* Get RNA properties. */
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const bool convert_r = RNA_boolean_get(op->ptr, "convert_r");
  const bool convert_g = RNA_boolean_get(op->ptr, "convert_g");
  const bool convert_b = RNA_boolean_get(op->ptr, "convert_b");

  /* Acquire image buffer. */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();
  const int total_pixels = width * height;

  /* Convert linear to sRGB for selected channels. */
#ifdef _OPENMP
#  pragma omp parallel for if (total_pixels > 4096)
#endif
  for (int i = 0; i < total_pixels; ++i) {
    const int idx = i * CHANNELS;
    if (convert_r) {
      pixels[idx + 0] = linear_to_srgb(pixels[idx + 0]);
    }
    if (convert_g) {
      pixels[idx + 1] = linear_to_srgb(pixels[idx + 1]);
    }
    if (convert_b) {
      pixels[idx + 2] = linear_to_srgb(pixels[idx + 2]);
    }
    /* Alpha unchanged */
  }

  /* Mark dirty and release. */
  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  /* Notify. */
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

void BAKING_OT_pixels_to_srgb(wmOperatorType *ot)
{
  ot->name = "Pixels to sRGB";
  ot->idname = "BAKING_OT_pixels_to_srgb";
  ot->description = "Convert image region from linear to sRGB color space";

  ot->exec = blender::ed::baking::pixels_to_srgb_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  /* RNA properties. */
  RNA_def_pointer_runtime(ot->srna, "image", RNA_Image, "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "start_x", 0, 0, 32768, "Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "start_y", 0, 0, 32768, "Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "convert_width", 1024, 1, 32768, "Convert Width", "", 1, 32768);
  RNA_def_int(ot->srna, "convert_height", 1024, 1, 32768, "Convert Height", "", 1, 32768);
}

void BAKING_OT_pixels_to_linear(wmOperatorType *ot)
{
  ot->name = "Pixels to Linear";
  ot->idname = "BAKING_OT_pixels_to_linear";
  ot->description = "Convert image region from sRGB to linear color space";

  ot->exec = blender::ed::baking::pixels_to_linear_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  /* RNA properties. */
  RNA_def_pointer_runtime(ot->srna, "image", RNA_Image, "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "start_x", 0, 0, 32768, "Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "start_y", 0, 0, 32768, "Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "convert_width", 1024, 1, 32768, "Convert Width", "", 1, 32768);
  RNA_def_int(ot->srna, "convert_height", 1024, 1, 32768, "Convert Height", "", 1, 32768);
}

void BAKING_OT_batch_srgb_to_linear(wmOperatorType *ot)
{
  ot->name = "Batch sRGB to Linear";
  ot->idname = "BAKING_OT_batch_srgb_to_linear";
  ot->description = "Convert entire image from sRGB to linear (per-channel control)";

  ot->exec = blender::ed::baking::batch_srgb_to_linear_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  /* RNA properties. */
  RNA_def_pointer_runtime(ot->srna, "image", RNA_Image, "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_boolean(ot->srna, "convert_r", true, "Convert Red", "");
  RNA_def_boolean(ot->srna, "convert_g", true, "Convert Green", "");
  RNA_def_boolean(ot->srna, "convert_b", true, "Convert Blue", "");
}

void BAKING_OT_batch_linear_to_srgb(wmOperatorType *ot)
{
  ot->name = "Batch Linear to sRGB";
  ot->idname = "BAKING_OT_batch_linear_to_srgb";
  ot->description = "Convert entire image from linear to sRGB (per-channel control)";

  ot->exec = blender::ed::baking::batch_linear_to_srgb_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  /* RNA properties. */
  RNA_def_pointer_runtime(ot->srna, "image", RNA_Image, "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_boolean(ot->srna, "convert_r", true, "Convert Red", "");
  RNA_def_boolean(ot->srna, "convert_g", true, "Convert Green", "");
  RNA_def_boolean(ot->srna, "convert_b", true, "Convert Blue", "");
}

/** \} */
}  // namespace blender
