/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Pixel operations for image baking.
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
/** \name Copy Image Pixels Operator
 * \{ */

static wmOperatorStatus copy_image_pixels_exec(bContext *C, wmOperator *op)
{
  /* Get RNA properties. */
  PointerRNA src_image_ptr = RNA_pointer_get(op->ptr, "src_image");
  PointerRNA dest_image_ptr = RNA_pointer_get(op->ptr, "dest_image");
  Image *src_image = static_cast<Image *>(src_image_ptr.data);
  Image *dest_image = static_cast<Image *>(dest_image_ptr.data);

  if (!src_image || !dest_image) {
    return OPERATOR_CANCELLED;
  }

  const int src_width = RNA_int_get(op->ptr, "src_width");
  const int src_height = RNA_int_get(op->ptr, "src_height");
  const int dest_width = RNA_int_get(op->ptr, "dest_width");
  const int dest_height = RNA_int_get(op->ptr, "dest_height");
  const int start_x = RNA_int_get(op->ptr, "start_x");
  const int start_y = RNA_int_get(op->ptr, "start_y");
  const int src_start_x = RNA_int_get(op->ptr, "src_start_x");
  const int src_start_y = RNA_int_get(op->ptr, "src_start_y");
  const int copy_width = RNA_int_get(op->ptr, "copy_width");
  const int copy_height = RNA_int_get(op->ptr, "copy_height");

  /* Acquire image buffers. */
  void *lock;
  ImBuf *src_ibuf = BKE_image_acquire_ibuf(src_image, nullptr, &lock);
  if (!src_ibuf || !src_ibuf->float_buffer.data) {
    BKE_image_release_ibuf(src_image, src_ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  void *dest_lock;
  ImBuf *dest_ibuf = BKE_image_acquire_ibuf(dest_image, nullptr, &dest_lock);
  if (!dest_ibuf || !dest_ibuf->float_buffer.data) {
    BKE_image_release_ibuf(src_image, src_ibuf, lock);
    BKE_image_release_ibuf(dest_image, dest_ibuf, dest_lock);
    return OPERATOR_CANCELLED;
  }

  float *src_pixels = src_ibuf->float_data_for_write();
  float *dest_pixels = dest_ibuf->float_data_for_write();

  /* Fast path: full image copy with matching dimensions. */
  if (start_x == 0 && start_y == 0 && src_start_x == 0 && src_start_y == 0 &&
      copy_width == src_width && copy_width == dest_width && copy_height == src_height &&
      copy_height == dest_height)
  {
    std::memcpy(dest_pixels, src_pixels, src_width * src_height * CHANNELS * sizeof(float));
  }
  else {
    /* Row-by-row copy for regions. */
#ifdef _OPENMP
#  pragma omp parallel for if (copy_height > 256)
#endif
    for (int y = 0; y < copy_height; ++y) {
      const int src_row = (src_start_y + y) * src_width * CHANNELS + src_start_x * CHANNELS;
      const int dest_row = (start_y + y) * dest_width * CHANNELS + start_x * CHANNELS;
      std::memcpy(
          &dest_pixels[dest_row], &src_pixels[src_row], copy_width * CHANNELS * sizeof(float));
    }
  }

  /* Mark dirty and release. */
  BKE_image_mark_dirty(dest_image, dest_ibuf);
  BKE_image_release_ibuf(src_image, src_ibuf, lock);
  BKE_image_release_ibuf(dest_image, dest_ibuf, dest_lock);

  /* Notify. */
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, dest_image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Copy Image Channel Pixels Operator
 * \{ */

static wmOperatorStatus copy_image_channel_pixels_exec(bContext *C, wmOperator *op)
{
  /* Get RNA properties. */
  PointerRNA src_image_ptr = RNA_pointer_get(op->ptr, "src_image");
  PointerRNA dest_image_ptr = RNA_pointer_get(op->ptr, "dest_image");
  Image *src_image = static_cast<Image *>(src_image_ptr.data);
  Image *dest_image = static_cast<Image *>(dest_image_ptr.data);

  if (!src_image || !dest_image) {
    return OPERATOR_CANCELLED;
  }

  const int src_width = RNA_int_get(op->ptr, "src_width");
  const int src_height = RNA_int_get(op->ptr, "src_height");
  (void)src_height; /* Used for API consistency, actual bounds use copy_height. */
  const int dest_width = RNA_int_get(op->ptr, "dest_width");
  const int dest_height = RNA_int_get(op->ptr, "dest_height");
  (void)dest_height; /* Used for API consistency, actual bounds use copy_height. */
  const int src_idx = RNA_int_get(op->ptr, "src_idx");
  const int dest_idx = RNA_int_get(op->ptr, "dest_idx");
  const int start_x = RNA_int_get(op->ptr, "start_x");
  const int start_y = RNA_int_get(op->ptr, "start_y");
  const int src_start_x = RNA_int_get(op->ptr, "src_start_x");
  const int src_start_y = RNA_int_get(op->ptr, "src_start_y");
  const int copy_width = RNA_int_get(op->ptr, "copy_width");
  const int copy_height = RNA_int_get(op->ptr, "copy_height");
  const bool invert_value = RNA_boolean_get(op->ptr, "invert_value");

  /* Acquire image buffers. */
  void *lock;
  ImBuf *src_ibuf = BKE_image_acquire_ibuf(src_image, nullptr, &lock);
  if (!src_ibuf || !src_ibuf->float_buffer.data) {
    BKE_image_release_ibuf(src_image, src_ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  void *dest_lock;
  ImBuf *dest_ibuf = BKE_image_acquire_ibuf(dest_image, nullptr, &dest_lock);
  if (!dest_ibuf || !dest_ibuf->float_buffer.data) {
    BKE_image_release_ibuf(src_image, src_ibuf, lock);
    BKE_image_release_ibuf(dest_image, dest_ibuf, dest_lock);
    return OPERATOR_CANCELLED;
  }

  const float *src_pixels = src_ibuf->float_data_for_write();
  float *dest_pixels = dest_ibuf->float_data_for_write();

  /* Copy channel data. */
#ifdef _OPENMP
#  pragma omp parallel for if (copy_height > 64)
#endif
  for (int y = 0; y < copy_height; ++y) {
    for (int x = 0; x < copy_width; ++x) {
      const int src_idx_flat = ((src_start_y + y) * src_width + (src_start_x + x)) * CHANNELS +
                               src_idx;
      const int dest_idx_flat = ((start_y + y) * dest_width + (start_x + x)) * CHANNELS +
                                dest_idx;

      float value = src_pixels[src_idx_flat];
      if (invert_value) {
        value = 1.0f - value;
      }
      dest_pixels[dest_idx_flat] = value;
    }
  }

  /* Mark dirty and release. */
  BKE_image_mark_dirty(dest_image, dest_ibuf);
  BKE_image_release_ibuf(src_image, src_ibuf, lock);
  BKE_image_release_ibuf(dest_image, dest_ibuf, dest_lock);

  /* Notify. */
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, dest_image);

  return OPERATOR_FINISHED;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Set Image Pixels Operator
 * \{ */

static wmOperatorStatus set_image_pixels_exec(bContext *C, wmOperator *op)
{
  /* Get RNA properties. */
  PointerRNA image_ptr = RNA_pointer_get(op->ptr, "image");
  Image *image = static_cast<Image *>(image_ptr.data);

  if (!image) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");
  (void)height; /* Used for API consistency, actual bounds use fill_height. */
  const int start_x = RNA_int_get(op->ptr, "start_x");
  const int start_y = RNA_int_get(op->ptr, "start_y");
  const int fill_width = RNA_int_get(op->ptr, "fill_width");
  const int fill_height = RNA_int_get(op->ptr, "fill_height");

  float color[4];
  RNA_float_get_array(op->ptr, "color", color);

  /* Acquire image buffer. */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || !ibuf->float_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return OPERATOR_CANCELLED;
  }

  float *pixels = ibuf->float_data_for_write();
  const float r = color[0], g = color[1], b = color[2], a = color[3];

  /* Fill pixels. */
#ifdef _OPENMP
#  pragma omp parallel for if (fill_height > 64)
#endif
  for (int y = 0; y < fill_height; ++y) {
    const int row_start = ((start_y + y) * width + start_x) * CHANNELS;
    for (int x = 0; x < fill_width; ++x) {
      const int idx = row_start + x * CHANNELS;
      pixels[idx + 0] = r;
      pixels[idx + 1] = g;
      pixels[idx + 2] = b;
      pixels[idx + 3] = a;
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

}  // namespace blender::ed::baking


/* Mixar 5.2 port: operator registrations live in namespace blender
 * (wmOperatorType and the decls in baking_ops_common.hh moved there). */
namespace blender {
/* -------------------------------------------------------------------- */
/** \name Registration (C linkage)
 * \{ */

void BAKING_OT_copy_image_pixels(wmOperatorType *ot)
{
  ot->name = "Copy Image Pixels";
  ot->idname = "BAKING_OT_copy_image_pixels";
  ot->description = "Copy pixels from one image to another (C++ accelerated)";

  ot->exec = blender::ed::baking::copy_image_pixels_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  /* RNA properties. */
  RNA_def_pointer_runtime(ot->srna, "src_image", RNA_Image, "Source Image", "");
  RNA_def_pointer_runtime(ot->srna, "dest_image", RNA_Image, "Destination Image", "");
  RNA_def_int(ot->srna, "src_width", 1024, 1, 32768, "Source Width", "", 1, 32768);
  RNA_def_int(ot->srna, "src_height", 1024, 1, 32768, "Source Height", "", 1, 32768);
  RNA_def_int(ot->srna, "dest_width", 1024, 1, 32768, "Destination Width", "", 1, 32768);
  RNA_def_int(ot->srna, "dest_height", 1024, 1, 32768, "Destination Height", "", 1, 32768);
  RNA_def_int(ot->srna, "start_x", 0, 0, 32768, "Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "start_y", 0, 0, 32768, "Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "src_start_x", 0, 0, 32768, "Source Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "src_start_y", 0, 0, 32768, "Source Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "copy_width", 1024, 1, 32768, "Copy Width", "", 1, 32768);
  RNA_def_int(ot->srna, "copy_height", 1024, 1, 32768, "Copy Height", "", 1, 32768);
}

void BAKING_OT_copy_image_channel_pixels(wmOperatorType *ot)
{
  ot->name = "Copy Image Channel Pixels";
  ot->idname = "BAKING_OT_copy_image_channel_pixels";
  ot->description = "Copy a single channel from one image to another (C++ accelerated)";

  ot->exec = blender::ed::baking::copy_image_channel_pixels_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  /* RNA properties. */
  RNA_def_pointer_runtime(ot->srna, "src_image", RNA_Image, "Source Image", "");
  RNA_def_pointer_runtime(ot->srna, "dest_image", RNA_Image, "Destination Image", "");
  RNA_def_int(ot->srna, "src_width", 1024, 1, 32768, "Source Width", "", 1, 32768);
  RNA_def_int(ot->srna, "src_height", 1024, 1, 32768, "Source Height", "", 1, 32768);
  RNA_def_int(ot->srna, "dest_width", 1024, 1, 32768, "Destination Width", "", 1, 32768);
  RNA_def_int(ot->srna, "dest_height", 1024, 1, 32768, "Destination Height", "", 1, 32768);
  RNA_def_int(ot->srna, "src_idx", 0, 0, 3, "Source Channel", "", 0, 3);
  RNA_def_int(ot->srna, "dest_idx", 0, 0, 3, "Destination Channel", "", 0, 3);
  RNA_def_int(ot->srna, "start_x", 0, 0, 32768, "Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "start_y", 0, 0, 32768, "Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "src_start_x", 0, 0, 32768, "Source Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "src_start_y", 0, 0, 32768, "Source Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "copy_width", 1024, 1, 32768, "Copy Width", "", 1, 32768);
  RNA_def_int(ot->srna, "copy_height", 1024, 1, 32768, "Copy Height", "", 1, 32768);
  RNA_def_boolean(ot->srna, "invert_value", false, "Invert Value", "Invert the copied value");
}

void BAKING_OT_set_image_pixels(wmOperatorType *ot)
{
  ot->name = "Set Image Pixels";
  ot->idname = "BAKING_OT_set_image_pixels";
  ot->description = "Fill image region with a solid color (C++ accelerated)";

  ot->exec = blender::ed::baking::set_image_pixels_exec;
  ot->poll = blender::ed::baking::baking_ops_poll;

  ot->flag = 0;

  /* RNA properties. */
  RNA_def_pointer_runtime(ot->srna, "image", RNA_Image, "Image", "");
  RNA_def_int(ot->srna, "width", 1024, 1, 32768, "Width", "", 1, 32768);
  RNA_def_int(ot->srna, "height", 1024, 1, 32768, "Height", "", 1, 32768);
  RNA_def_int(ot->srna, "start_x", 0, 0, 32768, "Start X", "", 0, 32768);
  RNA_def_int(ot->srna, "start_y", 0, 0, 32768, "Start Y", "", 0, 32768);
  RNA_def_int(ot->srna, "fill_width", 1024, 1, 32768, "Fill Width", "", 1, 32768);
  RNA_def_int(ot->srna, "fill_height", 1024, 1, 32768, "Fill Height", "", 1, 32768);
  RNA_def_float_color(
      ot->srna, "color", 4, nullptr, 0.0f, 1.0f, "Color", "Fill color (RGBA)", 0.0f, 1.0f);
}

/** \} */
}  // namespace blender
