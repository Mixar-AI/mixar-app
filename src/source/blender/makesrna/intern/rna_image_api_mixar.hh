/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Mixar extensions to the Image RNA API. Included by rna_image_api.cc. */
#pragma once

#ifdef RNA_RUNTIME
#  include <climits>

#  include "BKE_image.hh"
#  include "BKE_image_gpu.hh"
#  include "BKE_report.hh"
#  include "DNA_image_types.h"
#  include "GPU_texture.hh"
#  include "IMB_imbuf.hh"
#  include "IMB_partial_update.hh"
#endif

namespace blender {
#ifdef RNA_RUNTIME
/* Reuse the previous frame's texture while moving its owned reference between
 * Blender 5.3's per-ImBuf caches. A previous frame must never keep a texture
 * containing different pixels: revisiting that frame would show stale content. */
static bool rna_Image_mixar_movie_frame_update(Image *image, ReportList *reports, int frame)
{
  if (image->source != IMA_SRC_MOVIE) {
    BKE_reportf(reports, RPT_ERROR, "Image '%s' is not a movie", image->id.name + 2);
    return false;
  }

  const int previous_frame = image->lastframe;
  ImageUser iuser;
  BKE_imageuser_default(&iuser);
  iuser.framenr = previous_frame;
  /* Never decode an old frame solely to find a reusable GPU allocation. */
  ImBuf *previous = BKE_image_acquire_ibuf_gpu(image, &iuser, nullptr, nullptr, true);
  iuser.framenr = frame;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, &iuser, nullptr);
  if (ibuf == nullptr) {
    image->lastframe = previous_frame;
    BKE_image_release_ibuf(image, previous, nullptr);
    BKE_reportf(reports,
                RPT_ERROR,
                "Image '%s' failed to decode movie frame %d",
                image->id.name + 2,
                frame);
    return false;
  }

  /* Acquiring adds a reference; assigning below transfers it to the new buffer. */
  gpu::Texture *tex = previous ?
      IMB_acquire_gpu_texture(image->id.name + 2,
                             previous,
                             GPUTextureCreateFlags::EnableMipmaps,
                             true) : nullptr;
  const bool use_high_bitdepth = (image->flag & IMA_HIGH_BITDEPTH) != 0;
  const bool can_reuse = tex && GPU_texture_width(tex) == ibuf->x &&
                        GPU_texture_height(tex) == ibuf->y &&
                        GPU_texture_format(tex) ==
                            IMB_gpu_get_texture_format(ibuf, use_high_bitdepth, true);
  bool updated;
  if (can_reuse) {
    if (previous != ibuf) {
      IMB_free_gpu_textures(previous);
    }
    /* Finish CPU update tracking before adopting the fully refreshed texture. */
    IMB_partial_update_flush(ibuf);
    const bool premultiplied = BKE_image_has_gpu_texture_premultiplied_alpha(image, ibuf);
    IMB_update_gpu_texture_sub(tex, ibuf, 0, 0, 0, ibuf->x, ibuf->y, true, premultiplied);
    GPU_texture_update_mipmap_chain(tex);
    IMB_assign_gpu_texture(ibuf, tex);
    updated = true;
  }
  else {
    if (tex) {
      GPU_texture_free(tex);
    }
    /* First use, a size limit or a format change uses Blender's normal creation path. */
    tex = BKE_image_acquire_gpu_texture(image, &iuser);
    updated = tex != nullptr;
    if (tex) {
      GPU_texture_free(tex);
    }
  }
  BKE_image_release_ibuf(image, previous, nullptr);
  BKE_image_release_ibuf(image, ibuf, nullptr);
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
