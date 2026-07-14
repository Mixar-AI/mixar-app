/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Filter operations for image baking (blur, FXAA, etc.).
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
/** \name Gaussian Blur Operator
 * \{ */

static wmOperatorStatus gaussian_blur_exec(bContext *C, wmOperator *op)
{
  ScopedTimer timer("gaussian_blur");

  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    CLOG_WARN(LOG_BAKING, "gaussian_blur: no image provided");
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const int radius = RNA_int_get(op->ptr, "radius");
  const float sigma = RNA_float_get(op->ptr, "sigma");

  log_image_op("gaussian_blur", image, width, height);
  CLOG_INFO(LOG_BAKING, "gaussian_blur: radius=%d, sigma=%.2f", radius, sigma);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    CLOG_WARN(LOG_BAKING, "gaussian_blur: failed to acquire image buffer");
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_buffer.data;

  /* Generate 1D Gaussian kernel. */
  std::vector<float> kernel = generate_gaussian_kernel_1d(radius, sigma);
  const int kernel_size = static_cast<int>(kernel.size());

  /* Allocate temporary buffer for separable blur. */
  std::vector<float> temp(width * height * CHANNELS);

  /* Horizontal pass. */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      float sum[4] = {0.0f, 0.0f, 0.0f, 0.0f};
      float weight_sum = 0.0f;

      for (int k = 0; k < kernel_size; ++k) {
        const int ox = k - radius;
        const int sx = std::clamp(x + ox, 0, width - 1);
        const int src_idx = (y * width + sx) * CHANNELS;
        const float w = kernel[k];

        sum[0] += pixels[src_idx + 0] * w;
        sum[1] += pixels[src_idx + 1] * w;
        sum[2] += pixels[src_idx + 2] * w;
        sum[3] += pixels[src_idx + 3] * w;
        weight_sum += w;
      }

      const int dst_idx = (y * width + x) * CHANNELS;
      const float inv_weight = 1.0f / weight_sum;
      temp[dst_idx + 0] = sum[0] * inv_weight;
      temp[dst_idx + 1] = sum[1] * inv_weight;
      temp[dst_idx + 2] = sum[2] * inv_weight;
      temp[dst_idx + 3] = sum[3] * inv_weight;
    }
  }

  /* Vertical pass. */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      float sum[4] = {0.0f, 0.0f, 0.0f, 0.0f};
      float weight_sum = 0.0f;

      for (int k = 0; k < kernel_size; ++k) {
        const int oy = k - radius;
        const int sy = std::clamp(y + oy, 0, height - 1);
        const int src_idx = (sy * width + x) * CHANNELS;
        const float w = kernel[k];

        sum[0] += temp[src_idx + 0] * w;
        sum[1] += temp[src_idx + 1] * w;
        sum[2] += temp[src_idx + 2] * w;
        sum[3] += temp[src_idx + 3] * w;
        weight_sum += w;
      }

      const int dst_idx = (y * width + x) * CHANNELS;
      const float inv_weight = 1.0f / weight_sum;
      pixels[dst_idx + 0] = sum[0] * inv_weight;
      pixels[dst_idx + 1] = sum[1] * inv_weight;
      pixels[dst_idx + 2] = sum[2] * inv_weight;
      pixels[dst_idx + 3] = sum[3] * inv_weight;
    }
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Box Blur Operator
 * \{ */

static wmOperatorStatus box_blur_exec(bContext *C, wmOperator *op)
{
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const int radius = RNA_int_get(op->ptr, "radius");

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_buffer.data;
  const int kernel_size = 2 * radius + 1;

  std::vector<float> temp(width * height * CHANNELS);

  /* Horizontal pass (box filter). */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      float sum[4] = {0.0f, 0.0f, 0.0f, 0.0f};

      for (int k = -radius; k <= radius; ++k) {
        const int sx = std::clamp(x + k, 0, width - 1);
        const int src_idx = (y * width + sx) * CHANNELS;
        sum[0] += pixels[src_idx + 0];
        sum[1] += pixels[src_idx + 1];
        sum[2] += pixels[src_idx + 2];
        sum[3] += pixels[src_idx + 3];
      }

      const int dst_idx = (y * width + x) * CHANNELS;
      const float inv_size = 1.0f / kernel_size;
      temp[dst_idx + 0] = sum[0] * inv_size;
      temp[dst_idx + 1] = sum[1] * inv_size;
      temp[dst_idx + 2] = sum[2] * inv_size;
      temp[dst_idx + 3] = sum[3] * inv_size;
    }
  }

  /* Vertical pass. */
#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      float sum[4] = {0.0f, 0.0f, 0.0f, 0.0f};

      for (int k = -radius; k <= radius; ++k) {
        const int sy = std::clamp(y + k, 0, height - 1);
        const int src_idx = (sy * width + x) * CHANNELS;
        sum[0] += temp[src_idx + 0];
        sum[1] += temp[src_idx + 1];
        sum[2] += temp[src_idx + 2];
        sum[3] += temp[src_idx + 3];
      }

      const int dst_idx = (y * width + x) * CHANNELS;
      const float inv_size = 1.0f / kernel_size;
      pixels[dst_idx + 0] = sum[0] * inv_size;
      pixels[dst_idx + 1] = sum[1] * inv_size;
      pixels[dst_idx + 2] = sum[2] * inv_size;
      pixels[dst_idx + 3] = sum[3] * inv_size;
    }
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Bilateral Filter Operator
 * \{ */

static wmOperatorStatus bilateral_filter_exec(bContext *C, wmOperator *op)
{
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  const int radius = RNA_int_get(op->ptr, "radius");
  const float sigma_space = RNA_float_get(op->ptr, "sigma_space");
  const float sigma_color = RNA_float_get(op->ptr, "sigma_color");

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_buffer.data;

  std::vector<float> temp(width * height * CHANNELS);
  std::copy(pixels, pixels + width * height * CHANNELS, temp.begin());

  const float inv_sigma_space_sq = -0.5f / (sigma_space * sigma_space);
  const float inv_sigma_color_sq = -0.5f / (sigma_color * sigma_color);

#ifdef _OPENMP
#  pragma omp parallel for if (height > 32)
#endif
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      const int center_idx = (y * width + x) * CHANNELS;
      const float center_r = temp[center_idx + 0];
      const float center_g = temp[center_idx + 1];
      const float center_b = temp[center_idx + 2];

      float sum[4] = {0.0f, 0.0f, 0.0f, 0.0f};
      float weight_sum = 0.0f;

      for (int ky = -radius; ky <= radius; ++ky) {
        for (int kx = -radius; kx <= radius; ++kx) {
          const int sx = std::clamp(x + kx, 0, width - 1);
          const int sy = std::clamp(y + ky, 0, height - 1);
          const int src_idx = (sy * width + sx) * CHANNELS;

          /* Spatial weight. */
          const float dist_sq = static_cast<float>(kx * kx + ky * ky);
          const float spatial_weight = std::exp(dist_sq * inv_sigma_space_sq);

          /* Color weight. */
          const float dr = temp[src_idx + 0] - center_r;
          const float dg = temp[src_idx + 1] - center_g;
          const float db = temp[src_idx + 2] - center_b;
          const float color_dist_sq = dr * dr + dg * dg + db * db;
          const float color_weight = std::exp(color_dist_sq * inv_sigma_color_sq);

          const float weight = spatial_weight * color_weight;

          sum[0] += temp[src_idx + 0] * weight;
          sum[1] += temp[src_idx + 1] * weight;
          sum[2] += temp[src_idx + 2] * weight;
          sum[3] += temp[src_idx + 3] * weight;
          weight_sum += weight;
        }
      }

      if (weight_sum > 0.0f) {
        const float inv_weight = 1.0f / weight_sum;
        pixels[center_idx + 0] = sum[0] * inv_weight;
        pixels[center_idx + 1] = sum[1] * inv_weight;
        pixels[center_idx + 2] = sum[2] * inv_weight;
        pixels[center_idx + 3] = sum[3] * inv_weight;
      }
    }
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name FXAA Operator
 * \{ */

static wmOperatorStatus fxaa_exec(bContext *C, wmOperator *op)
{
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_buffer.data;

  std::vector<float> temp(width * height * CHANNELS);
  std::copy(pixels, pixels + width * height * CHANNELS, temp.begin());

  /* FXAA constants. */
  constexpr float FXAA_REDUCE_MIN = 1.0f / 128.0f;
  constexpr float FXAA_REDUCE_MUL = 1.0f / 8.0f;
  constexpr float FXAA_SPAN_MAX = 8.0f;

  auto get_luma = [](float r, float g, float b) -> float {
    return r * 0.299f + g * 0.587f + b * 0.114f;
  };

#ifdef _OPENMP
#  pragma omp parallel for if (height > 64)
#endif
  for (int y = 1; y < height - 1; ++y) {
    for (int x = 1; x < width - 1; ++x) {
      /* Sample neighbors. */
      const int idx_nw = ((y - 1) * width + (x - 1)) * CHANNELS;
      const int idx_ne = ((y - 1) * width + (x + 1)) * CHANNELS;
      const int idx_sw = ((y + 1) * width + (x - 1)) * CHANNELS;
      const int idx_se = ((y + 1) * width + (x + 1)) * CHANNELS;
      const int idx_m = (y * width + x) * CHANNELS;

      const float luma_nw = get_luma(temp[idx_nw], temp[idx_nw + 1], temp[idx_nw + 2]);
      const float luma_ne = get_luma(temp[idx_ne], temp[idx_ne + 1], temp[idx_ne + 2]);
      const float luma_sw = get_luma(temp[idx_sw], temp[idx_sw + 1], temp[idx_sw + 2]);
      const float luma_se = get_luma(temp[idx_se], temp[idx_se + 1], temp[idx_se + 2]);
      const float luma_m = get_luma(temp[idx_m], temp[idx_m + 1], temp[idx_m + 2]);

      const float luma_min = std::min({luma_nw, luma_ne, luma_sw, luma_se, luma_m});
      const float luma_max = std::max({luma_nw, luma_ne, luma_sw, luma_se, luma_m});

      float dir_x = -((luma_nw + luma_ne) - (luma_sw + luma_se));
      float dir_y = ((luma_nw + luma_sw) - (luma_ne + luma_se));

      const float dir_reduce = std::max(
          (luma_nw + luma_ne + luma_sw + luma_se) * 0.25f * FXAA_REDUCE_MUL, FXAA_REDUCE_MIN);

      const float rcp_dir_min = 1.0f / (std::min(std::abs(dir_x), std::abs(dir_y)) + dir_reduce);
      dir_x = std::clamp(dir_x * rcp_dir_min, -FXAA_SPAN_MAX, FXAA_SPAN_MAX);
      dir_y = std::clamp(dir_y * rcp_dir_min, -FXAA_SPAN_MAX, FXAA_SPAN_MAX);

      /* Sample along the detected edge. */
      auto sample_bilinear = [&](float ox, float oy) -> std::array<float, 4> {
        const float fx = x + ox;
        const float fy = y + oy;
        const int x0 = std::clamp(static_cast<int>(fx), 0, width - 1);
        const int y0 = std::clamp(static_cast<int>(fy), 0, height - 1);
        const int idx = (y0 * width + x0) * CHANNELS;
        return {temp[idx], temp[idx + 1], temp[idx + 2], temp[idx + 3]};
      };

      auto s1 = sample_bilinear(dir_x * (1.0f / 3.0f - 0.5f), dir_y * (1.0f / 3.0f - 0.5f));
      auto s2 = sample_bilinear(dir_x * (2.0f / 3.0f - 0.5f), dir_y * (2.0f / 3.0f - 0.5f));

      float rgb_a[4] = {(s1[0] + s2[0]) * 0.5f,
                        (s1[1] + s2[1]) * 0.5f,
                        (s1[2] + s2[2]) * 0.5f,
                        (s1[3] + s2[3]) * 0.5f};

      auto s3 = sample_bilinear(dir_x * -0.5f, dir_y * -0.5f);
      auto s4 = sample_bilinear(dir_x * 0.5f, dir_y * 0.5f);

      float rgb_b[4] = {rgb_a[0] * 0.5f + (s3[0] + s4[0]) * 0.25f,
                        rgb_a[1] * 0.5f + (s3[1] + s4[1]) * 0.25f,
                        rgb_a[2] * 0.5f + (s3[2] + s4[2]) * 0.25f,
                        rgb_a[3] * 0.5f + (s3[3] + s4[3]) * 0.25f};

      const float luma_b = get_luma(rgb_b[0], rgb_b[1], rgb_b[2]);

      if (luma_b < luma_min || luma_b > luma_max) {
        pixels[idx_m + 0] = rgb_a[0];
        pixels[idx_m + 1] = rgb_a[1];
        pixels[idx_m + 2] = rgb_a[2];
        pixels[idx_m + 3] = rgb_a[3];
      }
      else {
        pixels[idx_m + 0] = rgb_b[0];
        pixels[idx_m + 1] = rgb_b[1];
        pixels[idx_m + 2] = rgb_b[2];
        pixels[idx_m + 3] = rgb_b[3];
      }
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

void BAKING_OT_gaussian_blur(wmOperatorType *ot)
{
  ot->name = "Gaussian Blur";
  ot->idname = "BAKING_OT_gaussian_blur";
  ot->description = "Apply Gaussian blur to image (C++ accelerated)";

  ot->exec = blender::ed::baking::gaussian_blur_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "radius", 3, 1, 100, "Radius", "", 1, 100);
  RNA_def_float(ot->srna, "sigma", 1.0f, 0.1f, 100.0f, "Sigma", "", 0.1f, 100.0f);
}

void BAKING_OT_box_blur(wmOperatorType *ot)
{
  ot->name = "Box Blur";
  ot->idname = "BAKING_OT_box_blur";
  ot->description = "Apply box blur to image (C++ accelerated)";

  ot->exec = blender::ed::baking::box_blur_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "radius", 3, 1, 100, "Radius", "", 1, 100);
}

void BAKING_OT_bilateral_filter(wmOperatorType *ot)
{
  ot->name = "Bilateral Filter";
  ot->idname = "BAKING_OT_bilateral_filter";
  ot->description = "Apply edge-preserving bilateral filter (C++ accelerated)";

  ot->exec = blender::ed::baking::bilateral_filter_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "radius", 3, 1, 20, "Radius", "", 1, 20);
  RNA_def_float(ot->srna, "sigma_space", 3.0f, 0.1f, 50.0f, "Sigma Space", "", 0.1f, 50.0f);
  RNA_def_float(ot->srna, "sigma_color", 0.1f, 0.01f, 1.0f, "Sigma Color", "", 0.01f, 1.0f);
}

void BAKING_OT_fxaa(wmOperatorType *ot)
{
  ot->name = "FXAA";
  ot->idname = "BAKING_OT_fxaa";
  ot->description = "Apply FXAA anti-aliasing to image (C++ accelerated)";

  ot->exec = blender::ed::baking::fxaa_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
}

/** \} */
