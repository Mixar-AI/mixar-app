/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The per-Image sRGB GPU texture cache behind the moodboard's drawing.
 *
 * Split out of `mixie_draw_moodboard_images.cc` for the 500-line rule. The
 * seam is the cache's own: process-global texture state with an eviction
 * sweep, which the draw pass and the attachment ribbon both consume but
 * neither owns. Nothing here paints.
 */

#include "mixie_draw_moodboard_intern.hh"

#include <unordered_map>

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name sRGB Texture Cache
 *
 * On macOS Metal, the immDrawPixelsTexScaledFullSize fallback creates and
 * destroys temporary GPU textures every frame.  This causes Metal command-
 * buffer stalls that lock up or crash the application (especially after
 * duplicating images, which increases the per-frame texture churn).
 *
 * We cache a UNORM_8_8_8_8 texture per Image* so sRGB pixel bytes are
 * stored as-is (no sRGB-to-linear conversion), matching the visual output
 * of the old immDrawPixelsTexScaledFullSize path without per-frame churn.
 * \{ */

struct CachedImageTex {
  blender::gpu::Texture *tex;
  int width;
  int height;
  int frame;
  uint64_t last_used_frame;
};

static std::unordered_map<Image *, CachedImageTex> s_srgb_tex_cache;
static uint64_t s_cache_frame = 0;

/* Shared with the attachment ribbon; raw sRGB bytes preserve the board's colors. */
blender::gpu::Texture *mixie_moodboard_srgb_texture(Image *image, ImageUser *image_user)
{
  auto it = s_srgb_tex_cache.find(image);
  const int requested_frame = image_user ? image_user->framenr : 0;

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, image_user, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return nullptr;
  }

  /* A >8-bit movie frame (e.g. a 10-bit HEVC video-gen result) decodes to a
   * scene-linear float buffer with NO byte buffer, which this byte cache
   * cannot upload — node previews then drew nothing (a black tile). Convert
   * to display bytes once per decoded frame; the byte buffer lands on the
   * movie-cache ibuf, so a paused frame pays this exactly once. */
  if (ibuf->byte_buffer.data == nullptr && ibuf->float_buffer.data != nullptr) {
    IMB_byte_from_float(ibuf);
  }

  /* Return cached texture if dimensions still match. */
  if (it != s_srgb_tex_cache.end()) {
    if (ibuf->x == it->second.width && ibuf->y == it->second.height) {
      it->second.last_used_frame = s_cache_frame;
      if (it->second.frame == requested_frame) {
        BKE_image_release_ibuf(image, ibuf, lock);
        return it->second.tex;
      }
      if (ibuf->byte_buffer.data) {
        GPU_texture_update(it->second.tex, GPU_DATA_UBYTE, ibuf->byte_buffer.data);
        it->second.frame = requested_frame;
        BKE_image_release_ibuf(image, ibuf, lock);
        return it->second.tex;
      }
    }
    /* Stale dimensions, or a frame this byte cache cannot represent. */
    GPU_texture_free(it->second.tex);
    s_srgb_tex_cache.erase(it);
  }

  /* Create UNORM texture from raw byte data (no sRGB conversion). */
  blender::gpu::Texture *tex = nullptr;
  if (ibuf->byte_buffer.data) {
    eGPUTextureUsage usage = GPU_TEXTURE_USAGE_GENERAL;
    tex = GPU_texture_create_2d(
        "moodboard_srgb", ibuf->x, ibuf->y, 1,
        blender::gpu::TextureFormat::UNORM_8_8_8_8, usage, nullptr);
    if (tex) {
      GPU_texture_update(tex, GPU_DATA_UBYTE, ibuf->byte_buffer.data);
      s_srgb_tex_cache[image] = {tex, ibuf->x, ibuf->y, requested_frame, s_cache_frame};
    }
  }

  BKE_image_release_ibuf(image, ibuf, lock);
  return tex;
}

void mixie_moodboard_texture_cache_frame_begin()
{
  s_cache_frame++;
}

void mixie_moodboard_texture_cache_frame_end()
{
  /* Evict entries not touched this frame: the image was removed or deleted. */
  for (auto it = s_srgb_tex_cache.begin(); it != s_srgb_tex_cache.end();) {
    if (it->second.last_used_frame != s_cache_frame) {
      GPU_texture_free(it->second.tex);
      it = s_srgb_tex_cache.erase(it);
    }
    else {
      ++it;
    }
  }
}

void mixie_moodboard_free_texture_cache()
{
  for (auto &[_, entry] : s_srgb_tex_cache) {
    if (entry.tex) {
      GPU_texture_free(entry.tex);
    }
  }
  s_srgb_tex_cache.clear();
}

/** \} */

}  // namespace blender::ed::mixie
