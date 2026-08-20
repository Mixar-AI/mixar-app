/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Alpha premultiplication operations for image baking.
 */

#include "baking_ops_common.hh"

#include "DNA_image_types.h"

#include "BKE_image.hh"

#include "IMB_imbuf.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

namespace blender::ed::baking {

/* -------------------------------------------------------------------- */
/** \name Multiply RGB by Alpha Operator
 * \{ */

static wmOperatorStatus multiply_rgb_by_alpha_exec(bContext *C, wmOperator *op)
{
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int start_x = RNA_int_get(op->ptr, "start_x");
  const int start_y = RNA_int_get(op->ptr, "start_y");
  const int region_width = RNA_int_get(op->ptr, "region_width");
  const int region_height = RNA_int_get(op->ptr, "region_height");

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();

#ifdef _OPENMP
#  pragma omp parallel for if (region_height > 64)
#endif
  for (int y = 0; y < region_height; ++y) {
    for (int x = 0; x < region_width; ++x) {
      const int idx = ((start_y + y) * width + (start_x + x)) * CHANNELS;
      const float alpha = pixels[idx + 3];
      pixels[idx + 0] *= alpha;
      pixels[idx + 1] *= alpha;
      pixels[idx + 2] *= alpha;
    }
  }

  BKE_image_mark_dirty(image, ibuf);
  BKE_image_release_ibuf(image, ibuf, lock);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Divide RGB by Alpha Operator
 * \{ */

static wmOperatorStatus divide_rgb_by_alpha_exec(bContext *C, wmOperator *op)
{
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int start_x = RNA_int_get(op->ptr, "start_x");
  const int start_y = RNA_int_get(op->ptr, "start_y");
  const int region_width = RNA_int_get(op->ptr, "region_width");
  const int region_height = RNA_int_get(op->ptr, "region_height");

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();

#ifdef _OPENMP
#  pragma omp parallel for if (region_height > 64)
#endif
  for (int y = 0; y < region_height; ++y) {
    for (int x = 0; x < region_width; ++x) {
      const int idx = ((start_y + y) * width + (start_x + x)) * CHANNELS;
      const float alpha = pixels[idx + 3];
      if (alpha > 0.0f) {
        const float inv_alpha = 1.0f / alpha;
        pixels[idx + 0] *= inv_alpha;
        pixels[idx + 1] *= inv_alpha;
        pixels[idx + 2] *= inv_alpha;
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


/* Mixar 5.2 port: operator registrations live in namespace blender
 * (wmOperatorType and the decls in baking_ops_common.hh moved there). */
namespace blender {
/* -------------------------------------------------------------------- */
/** \name Registration (C linkage)
 * \{ */

void BAKING_OT_multiply_rgb_by_alpha(wmOperatorType *ot)
{
  ot->name = "Multiply RGB by Alpha";
  ot->idname = "BAKING_OT_multiply_rgb_by_alpha";
  ot->description = "Premultiply RGB channels by alpha (C++ accelerated)";

  ot->exec = blender::ed::baking::multiply_rgb_by_alpha_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "start_x", 0, 0, 32768, "Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "start_y", 0, 0, 32768, "Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "region_width", 1024, 1, 32768, "Region Width", "", 1, 32768);
  RNA_def_int(ot->srna, "region_height", 1024, 1, 32768, "Region Height", "", 1, 32768);
}

void BAKING_OT_divide_rgb_by_alpha(wmOperatorType *ot)
{
  ot->name = "Divide RGB by Alpha";
  ot->idname = "BAKING_OT_divide_rgb_by_alpha";
  ot->description = "Unpremultiply RGB channels by alpha (C++ accelerated)";

  ot->exec = blender::ed::baking::divide_rgb_by_alpha_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  RNA_def_pointer(ot->srna, "image", "Image", "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "start_x", 0, 0, 32768, "Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "start_y", 0, 0, 32768, "Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "region_width", 1024, 1, 32768, "Region Width", "", 1, 32768);
  RNA_def_int(ot->srna, "region_height", 1024, 1, 32768, "Region Height", "", 1, 32768);
}

/** \} */
}  // namespace blender
