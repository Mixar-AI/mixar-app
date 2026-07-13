/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Morphological operations for image baking (dilate, erode, edge detection).
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

#include "WM_api.hh"
#include "WM_types.hh"

namespace blender::ed::baking {

/* -------------------------------------------------------------------- */
/** \name Dilate Operator
 * \{ */

static wmOperatorStatus dilate_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("dilate");

  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    CLOG_WARN(LOG_BAKING, "dilate: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const int radius = RNA_int_get(op->ptr, "radius");
  const int channel = RNA_int_get(op->ptr, "channel");

  log_image_op("dilate", image, width, height);
  CLOG_INFO(LOG_BAKING, "dilate: radius=%d, channel=%d", radius, channel);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "dilate: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_buffer.data;

  std::vector<float> temp(width * height * CHANNELS);
  std::copy(pixels, pixels + width * height * CHANNELS, temp.begin());

  /* Dilate: take maximum value in neighborhood. */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      float max_val = -1e10f;

      for (int ky = -radius; ky <= radius; ++ky) {
        for (int kx = -radius; kx <= radius; ++kx) {
          const int sx = std::clamp(x + kx, 0, width - 1);
          const int sy = std::clamp(y + ky, 0, height - 1);
          const int src_idx = (sy * width + sx) * CHANNELS + channel;
          max_val = std::max(max_val, temp[src_idx]);
        }
      }

      const int dst_idx = (y * width + x) * CHANNELS + channel;
      pixels[dst_idx] = max_val;
    }
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Erode Operator
 * \{ */

static wmOperatorStatus erode_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("erode");

  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    CLOG_WARN(LOG_BAKING, "erode: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const int radius = RNA_int_get(op->ptr, "radius");
  const int channel = RNA_int_get(op->ptr, "channel");

  log_image_op("erode", image, width, height);
  CLOG_INFO(LOG_BAKING, "erode: radius=%d, channel=%d", radius, channel);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "erode: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_buffer.data;

  std::vector<float> temp(width * height * CHANNELS);
  std::copy(pixels, pixels + width * height * CHANNELS, temp.begin());

  /* Erode: take minimum value in neighborhood. */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      float min_val = 1e10f;

      for (int ky = -radius; ky <= radius; ++ky) {
        for (int kx = -radius; kx <= radius; ++kx) {
          const int sx = std::clamp(x + kx, 0, width - 1);
          const int sy = std::clamp(y + ky, 0, height - 1);
          const int src_idx = (sy * width + sx) * CHANNELS + channel;
          min_val = std::min(min_val, temp[src_idx]);
        }
      }

      const int dst_idx = (y * width + x) * CHANNELS + channel;
      pixels[dst_idx] = min_val;
    }
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Sobel Edge Detect Operator
 * \{ */

static wmOperatorStatus sobel_edge_detect_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("sobel_edge_detect");

  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    CLOG_WARN(LOG_BAKING, "sobel_edge_detect: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");

  log_image_op("sobel_edge_detect", image, width, height);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "sobel_edge_detect: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_buffer.data;

  std::vector<float> temp(width * height * CHANNELS);
  std::copy(pixels, pixels + width * height * CHANNELS, temp.begin());

  /* Sobel kernels. */
  const float sobel_x[9] = {-1, 0, 1, -2, 0, 2, -1, 0, 1};
  const float sobel_y[9] = {-1, -2, -1, 0, 0, 0, 1, 2, 1};

#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 1; y < height - 1; ++y) {
    for (int x = 1; x < width - 1; ++x) {
      float gx = 0.0f, gy = 0.0f;

      /* Compute luminance gradient. */
      int k = 0;
      for (int ky = -1; ky <= 1; ++ky) {
        for (int kx = -1; kx <= 1; ++kx) {
          const int src_idx = ((y + ky) * width + (x + kx)) * CHANNELS;
          /* Luminance. */
          const float lum = temp[src_idx + 0] * 0.299f + temp[src_idx + 1] * 0.587f +
                            temp[src_idx + 2] * 0.114f;
          gx += lum * sobel_x[k];
          gy += lum * sobel_y[k];
          k++;
        }
      }

      const float magnitude = std::sqrt(gx * gx + gy * gy);
      const int dst_idx = (y * width + x) * CHANNELS;

      /* Store edge magnitude in all RGB channels. */
      pixels[dst_idx + 0] = magnitude;
      pixels[dst_idx + 1] = magnitude;
      pixels[dst_idx + 2] = magnitude;
      /* Keep alpha unchanged. */
    }
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

}  // namespace blender::ed::baking

/* -------------------------------------------------------------------- */
/** \name Registration (C linkage)
 * \{ */

void BAKING_OT_dilate(wmOperatorType *ot)
{
  ot->name = "Dilate";
  ot->idname = "BAKING_OT_dilate";
  ot->description = "Dilate image channel (expand bright areas)";

  ot->exec = blender::ed::baking::dilate_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "radius", 1, 1, 50, "Radius", "", 1, 50);
  RNA_def_int(ot->srna, "channel", 0, 0, 3, "Channel", "Channel to dilate (0=R, 1=G, 2=B, 3=A)", 0, 3);
}

void BAKING_OT_erode(wmOperatorType *ot)
{
  ot->name = "Erode";
  ot->idname = "BAKING_OT_erode";
  ot->description = "Erode image channel (shrink bright areas)";

  ot->exec = blender::ed::baking::erode_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "radius", 1, 1, 50, "Radius", "", 1, 50);
  RNA_def_int(ot->srna, "channel", 0, 0, 3, "Channel", "Channel to erode (0=R, 1=G, 2=B, 3=A)", 0, 3);
}

void BAKING_OT_sobel_edge_detect(wmOperatorType *ot)
{
  ot->name = "Sobel Edge Detect";
  ot->idname = "BAKING_OT_sobel_edge_detect";
  ot->description = "Detect edges using Sobel operator";

  ot->exec = blender::ed::baking::sobel_edge_detect_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
}

/** \} */
