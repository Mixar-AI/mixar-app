/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Mixar extensions to the Image RNA API. Included by rna_image_api.cc. */
#pragma once

#ifdef RNA_RUNTIME
#  include <climits>

#  include "BKE_image.hh"
#  include "BKE_report.hh"
#  include "DNA_image_types.h"
#  include "GPU_texture.hh"
#  include "IMB_imbuf.hh"
#endif

namespace blender {
#ifdef RNA_RUNTIME
/* Mixar: decode movie frame `frame` (1-based, like `gl_load`) and upload it into the image's
 * cached GPU texture IN PLACE. Blender's own frame handling (`BKE_image_user_frame_calc`) marks a
 * full update whenever the frame changes, which frees and recreates the texture; a Python draw
 * handler playing a video at 24 fps would therefore churn one texture per frame, and on Metal
 * that stalls the command buffer. Here the texture that `gpu.texture.from_image()` hands out is
 * kept alive and only its content changes, replicating exactly the conversion that
 * `IMB_create_gpu_texture` applied when the texture was created (`IMB_update_gpu_texture_sub`
 * runs the same `imb_gpu_get_data` path: colorspace, premultiplied alpha, grayscale packing). */
static bool rna_Image_mixar_movie_frame_update(Image *image, ReportList *reports, int frame)
{
  if (image->source != IMA_SRC_MOVIE) {
    BKE_reportf(reports, RPT_ERROR, "Image '%s' is not a movie", image->id.name + 2);
    return false;
  }

  ImageUser iuser;
  BKE_imageuser_default(&iuser);
  iuser.framenr = frame;

  /* Decode (or fetch from the movie cache) before touching the GPU so a failed decode never
   * leaves the 1x1 error texture behind. */
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, &iuser, nullptr);
  if (ibuf == nullptr) {
    BKE_reportf(reports,
                RPT_ERROR,
                "Image '%s' failed to decode movie frame %d",
                image->id.name + 2,
                frame);
    return false;
  }

  /* Get the cached texture. This also consumes any pending partial-update changeset; when that
   * (or first use) makes Blender create the texture, it is built from `iuser`, i.e. already from
   * this frame, and no second upload is needed. */
  gpu::Texture *const tex_before = image->runtime->gputexture[TEXTARGET_2D][0];
  gpu::Texture *tex = BKE_image_get_gpu_texture(image, &iuser);
  if (tex == nullptr) {
    BKE_image_release_ibuf(image, ibuf, nullptr);
    BKE_reportf(reports, RPT_ERROR, "Failed to load image texture '%s'", image->id.name + 2);
    return false;
  }

  bool updated = false;
  if (tex != tex_before) {
    updated = true;
  }
  else {
    const bool use_high_bitdepth = (image->flag & IMA_HIGH_BITDEPTH) != 0;
    const bool same_size = (GPU_texture_width(tex) == ibuf->x) &&
                           (GPU_texture_height(tex) == ibuf->y);
    const bool same_format = (GPU_texture_format(tex) ==
                              IMB_gpu_get_texture_format(ibuf, use_high_bitdepth, true));

    if (same_size && same_format) {
      const bool store_premultiplied = BKE_image_has_gpu_texture_premultiplied_alpha(image, ibuf);
      IMB_update_gpu_texture_sub(tex,
                                 ibuf,
                                 0,
                                 0,
                                 0,
                                 ibuf->x,
                                 ibuf->y,
                                 use_high_bitdepth,
                                 true,
                                 store_premultiplied);
      GPU_texture_update_mipmap_chain(tex);
      image->runtime->gpuflag |= IMA_GPU_MIPMAP_COMPLETE;
      updated = true;
    }
    else {
      /* Size-limited or differently typed texture: fall back to Blender's recreate path.
       * Callers must re-fetch `gpu.texture.from_image()` afterwards. */
      BKE_image_free_gputextures(image);
      updated = BKE_image_get_gpu_texture(image, &iuser) != nullptr;
    }
  }

  BKE_image_release_ibuf(image, ibuf, nullptr);

  if (updated) {
    /* Keep Blender's frame bookkeeping in agreement so `BKE_image_user_frame_calc` for the same
     * frame does not mark a full update (which would free the texture). */
    image->runtime->gpuframenr = frame;
  }
  return updated;
}
#else
static void rna_def_image_api_mixar(StructRNA *srna)
{
  FunctionRNA *func;
  PropertyRNA *parm;

  /* In-place movie frame upload into the cached GPU texture. */
  func = RNA_def_function(srna, "mixar_movie_frame_update", "rna_Image_mixar_movie_frame_update");
  RNA_def_function_ui_description(
      func,
      "Decode a movie frame and upload it into the image's cached GPU texture in place, so "
      "gpu.texture.from_image() keeps returning the same texture (Mixar)");
  RNA_def_function_flag(func, FUNC_USE_REPORTS);
  parm = RNA_def_int(func, "frame", 1, 1, INT_MAX, "Frame", "Movie frame (1-based)", 1, INT_MAX);
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  /* return value */
  parm = RNA_def_boolean(
      func, "updated", false, "Updated", "True when the cached texture now holds the frame");
  RNA_def_function_return(func, parm);
}
#endif
}  // namespace blender
