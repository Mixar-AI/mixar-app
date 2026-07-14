/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Baking operator declarations.
 */

#pragma once

struct wmOperatorType;

/* -------------------------------------------------------------------- */
/** \name Pixel Operations (baking_ops_pixels.cc)
 * \{ */

void BAKING_OT_copy_image_pixels(wmOperatorType *ot);
void BAKING_OT_copy_image_channel_pixels(wmOperatorType *ot);
void BAKING_OT_set_image_pixels(wmOperatorType *ot);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Color Space Operations (baking_ops_colorspace.cc)
 * \{ */

void BAKING_OT_pixels_to_srgb(wmOperatorType *ot);
void BAKING_OT_pixels_to_linear(wmOperatorType *ot);
void BAKING_OT_batch_srgb_to_linear(wmOperatorType *ot);
void BAKING_OT_batch_linear_to_srgb(wmOperatorType *ot);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Alpha Operations (baking_ops_alpha.cc)
 * \{ */

void BAKING_OT_multiply_rgb_by_alpha(wmOperatorType *ot);
void BAKING_OT_divide_rgb_by_alpha(wmOperatorType *ot);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Filter Operations (baking_ops_filters.cc)
 * \{ */

void BAKING_OT_gaussian_blur(wmOperatorType *ot);
void BAKING_OT_box_blur(wmOperatorType *ot);
void BAKING_OT_bilateral_filter(wmOperatorType *ot);
void BAKING_OT_fxaa(wmOperatorType *ot);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Morphological Operations (baking_ops_morphology.cc)
 * \{ */

void BAKING_OT_dilate(wmOperatorType *ot);
void BAKING_OT_erode(wmOperatorType *ot);
void BAKING_OT_sobel_edge_detect(wmOperatorType *ot);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Normal Map Operations (baking_ops_normal.cc)
 * \{ */

void BAKING_OT_height_to_normal(wmOperatorType *ot);
void BAKING_OT_blend_normal_maps(wmOperatorType *ot);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend Operations (baking_ops_blend.cc)
 * \{ */

void BAKING_OT_blend_images(wmOperatorType *ot);
void BAKING_OT_dither_image(wmOperatorType *ot);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Statistics Operations (baking_ops_statistics.cc)
 * \{ */

void BAKING_OT_get_image_minmax(wmOperatorType *ot);
void BAKING_OT_normalize_image(wmOperatorType *ot);

/** \} */
