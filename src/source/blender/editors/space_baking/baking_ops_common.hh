/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Common utilities for baking operators.
 *
 * Contains shared utility functions, constants, and helper routines
 * used across all baking operator implementations.
 */

#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <vector>

#include "DNA_image_types.h"
#include "DNA_ID.h"
#include "DNA_scene_types.h"

#include "BKE_context.hh"
#include "BKE_image.hh"
#include "BKE_lib_id.hh"
#include "BKE_report.hh"

#include "BLI_math_vector.h"

#include "CLG_log.h"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"

#ifdef _OPENMP
#  include <omp.h>
#endif

/* Declare logging module for baking operations (defined in space_baking.cc). */
extern CLG_LogRef *LOG_BAKING;

namespace blender::ed::baking {

/* -------------------------------------------------------------------- */
/** \name Constants
 * \{ */

constexpr float SRGB_LINEAR_THRESHOLD = 0.03928f;
constexpr float LINEAR_SRGB_THRESHOLD = 0.0031308f;
constexpr float PI = 3.14159265358979323846f;
constexpr int CHANNELS = 4;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Image Operator Properties
 * \{ */

/**
 * Blender operators cannot own ID pointer properties. Pass the image datablock name through
 * RNA and resolve it immediately when the operator executes instead.
 */
inline Image *image_from_operator(bContext *C, wmOperator *op, const char *property)
{
  char image_name[MAX_ID_NAME - 2];
  RNA_string_get(op->ptr, property, image_name);
  if (image_name[0] == '\0') {
    BKE_reportf(op->reports, RPT_ERROR, "Image property '%s' is empty", property);
    return nullptr;
  }

  Main *bmain = CTX_data_main(C);
  Image *image = reinterpret_cast<Image *>(BKE_libblock_find_name(bmain, ID_IM, image_name));
  if (!image) {
    BKE_reportf(op->reports, RPT_ERROR, "Image '%s' was not found", image_name);
  }
  return image;
}

inline void define_image_name_property(StructRNA *srna,
                                       const char *identifier,
                                       const char *name,
                                       const char *description = "")
{
  RNA_def_string(srna, identifier, nullptr, MAX_ID_NAME - 2, name, description);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Color Space Conversion
 * \{ */

inline float srgb_to_linear(float e)
{
  if (e <= SRGB_LINEAR_THRESHOLD) {
    return e / 12.92f;
  }
  return std::pow((e + 0.055f) / 1.055f, 2.4f);
}

inline float linear_to_srgb(float e)
{
  if (e > LINEAR_SRGB_THRESHOLD) {
    return 1.055f * std::pow(e, 1.0f / 2.4f) - 0.055f;
  }
  return 12.92f * e;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Math Utilities
 * \{ */

inline float safe_divide(float a, float b)
{
  return a / std::max(b, 0.00001f);
}

inline float clamp_f(float v, float lo, float hi)
{
  return std::min(std::max(v, lo), hi);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Gaussian Kernel Generation
 * \{ */

inline std::vector<float> generate_gaussian_kernel_1d(int radius, float sigma)
{
  const int size = 2 * radius + 1;
  std::vector<float> kernel(size);
  float sum = 0.0f;

  for (int i = 0; i < size; ++i) {
    const float x = static_cast<float>(i - radius);
    kernel[i] = std::exp(-(x * x) / (2.0f * sigma * sigma));
    sum += kernel[i];
  }

  /* Normalize. */
  for (int i = 0; i < size; ++i) {
    kernel[i] /= sum;
  }

  return kernel;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Poll Functions
 * \{ */

/**
 * Basic poll function for baking operators.
 * Checks that a scene exists in the context.
 */
inline bool baking_ops_poll(bContext *C)
{
  return CTX_data_scene(C) != nullptr;
}

/**
 * Poll function requiring an active image.
 * Checks that a scene exists and an image is available in the context.
 */
inline bool baking_ops_image_poll(bContext *C)
{
  if (!CTX_data_scene(C)) {
    return false;
  }

  /* Can check for active image here if needed */
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Logging Utilities
 * \{ */

/**
 * Simple timer class for performance logging.
 */
class ScopedTimer {
 private:
  const char *operation_name_;
  std::chrono::high_resolution_clock::time_point start_;

 public:
  ScopedTimer(const char *name) : operation_name_(name)
  {
    start_ = std::chrono::high_resolution_clock::now();
    CLOG_INFO(LOG_BAKING, "%s: started", operation_name_);
  }

  ~ScopedTimer()
  {
    auto end = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start_);
    CLOG_INFO(LOG_BAKING, "%s: completed in %lld ms", operation_name_, duration.count());
  }

  double elapsed_ms() const
  {
    auto now = std::chrono::high_resolution_clock::now();
    return std::chrono::duration<double, std::milli>(now - start_).count();
  }
};

/**
 * Log image operation details.
 */
inline void log_image_op(const char *op_name, Image *image, int width, int height)
{
  if (image) {
    CLOG_INFO(LOG_BAKING,
              "%s: image='%s', dimensions=%dx%d",
              op_name,
              image->id.name + 2,
              width,
              height);
  }
  else {
    CLOG_WARN(LOG_BAKING, "%s: null image provided", op_name);
  }
}

/** \} */

}  // namespace blender::ed::baking
