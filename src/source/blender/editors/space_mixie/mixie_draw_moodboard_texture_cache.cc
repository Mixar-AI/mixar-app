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
 *
 * A warm still must not take the image lock on every redraw. The early-out
 * is the draw stamp: session uid (pointer reuse), `runtime->update_count`
 * (depsgraph tag — the only signal that same-size pixels changed), `lastframe`,
 * and the requested movie frame. Session uid 0 or a missing runtime never
 * early-outs. The aspect map is separate from the per-frame GPU sweep: graph
 * layout runs before that sweep, and off-screen tiles are culled before they
 * touch a GPU texture, so tying aspect to the sweep would re-lock them every
 * frame.
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

struct ImageDrawStamp {
  unsigned int session_uid = 0;
  uint64_t update_count = 0;
  int lastframe = 0;
};

struct CachedImageTex {
  blender::gpu::Texture *tex;
  int width;
  int height;
  int frame;
  uint64_t last_used_frame;
  ImageDrawStamp stamp;
};

struct CachedImageSize {
  ImageDrawStamp stamp;
  int width;
  int height;
};

static std::unordered_map<Image *, CachedImageTex> s_srgb_tex_cache;
static std::unordered_map<uint64_t, CachedImageSize> s_image_size_cache;
static uint64_t s_cache_frame = 0;

/* Off-screen tiles and hit-tests outlive one draw's GPU entries. Past this
 * the map is dropped and the next layout refills it; a few thousand tiles
 * is already far past a board anyone pans. */
static constexpr size_t IMAGE_SIZE_CACHE_MAX = 1024;

static bool image_draw_stamp(const Image *image, ImageDrawStamp *r_stamp)
{
  if (image == nullptr || image->id.session_uid == 0 || image->runtime == nullptr) {
    return false;
  }
  r_stamp->session_uid = image->id.session_uid;
  r_stamp->update_count = image->runtime->update_count;
  r_stamp->lastframe = image->lastframe;
  return true;
}

static bool stamp_matches(const ImageDrawStamp &cached, const ImageDrawStamp &live)
{
  return cached.session_uid == live.session_uid && cached.update_count == live.update_count &&
         cached.lastframe == live.lastframe;
}

static uint64_t image_size_key(const unsigned int session_uid, const int frame)
{
  return (uint64_t(session_uid) << 32) | uint64_t(uint32_t(frame));
}

static void remember_image_size(const ImageDrawStamp &stamp,
                                const int frame,
                                const int width,
                                const int height)
{
  if (stamp.session_uid == 0 || width <= 0 || height <= 0) {
    return;
  }
  const uint64_t key = image_size_key(stamp.session_uid, frame);
  auto it = s_image_size_cache.find(key);
  if (it != s_image_size_cache.end()) {
    it->second = {stamp, width, height};
    return;
  }
  if (s_image_size_cache.size() >= IMAGE_SIZE_CACHE_MAX) {
    s_image_size_cache.clear();
  }
  s_image_size_cache.emplace(key, CachedImageSize{stamp, width, height});
}

static void store_cached_tex(Image *image,
                             blender::gpu::Texture *tex,
                             const int width,
                             const int height,
                             const int frame)
{
  ImageDrawStamp stamp{};
  const bool stamped = image_draw_stamp(image, &stamp);
  s_srgb_tex_cache[image] = {
      tex, width, height, frame, s_cache_frame, stamped ? stamp : ImageDrawStamp{}};
  if (stamped) {
    remember_image_size(stamp, frame, width, height);
  }
}

bool mixie_moodboard_image_size(Image *image,
                                ImageUser *image_user,
                                int *r_width,
                                int *r_height)
{
  if (image == nullptr || r_width == nullptr || r_height == nullptr) {
    return false;
  }
  const int requested_frame = image_user ? image_user->framenr : 0;
  ImageDrawStamp stamp{};
  if (image_draw_stamp(image, &stamp)) {
    const auto sized = s_image_size_cache.find(image_size_key(stamp.session_uid, requested_frame));
    if (sized != s_image_size_cache.end() && stamp_matches(sized->second.stamp, stamp) &&
        sized->second.width > 0 && sized->second.height > 0)
    {
      *r_width = sized->second.width;
      *r_height = sized->second.height;
      return true;
    }
    const auto tex = s_srgb_tex_cache.find(image);
    if (tex != s_srgb_tex_cache.end() && tex->second.tex != nullptr &&
        stamp_matches(tex->second.stamp, stamp) && tex->second.frame == requested_frame &&
        tex->second.width > 0 && tex->second.height > 0)
    {
      *r_width = tex->second.width;
      *r_height = tex->second.height;
      remember_image_size(stamp, requested_frame, tex->second.width, tex->second.height);
      return true;
    }
  }

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, image_user, &lock);
  const bool ok = ibuf && ibuf->x > 0 && ibuf->y > 0;
  if (ok) {
    *r_width = ibuf->x;
    *r_height = ibuf->y;
    ImageDrawStamp stored{};
    if (image_draw_stamp(image, &stored)) {
      remember_image_size(stored, requested_frame, ibuf->x, ibuf->y);
    }
  }
  BKE_image_release_ibuf(image, ibuf, lock);
  return ok;
}

float mixie_moodboard_image_aspect(Image *image)
{
  int width = 0;
  int height = 0;
  if (!mixie_moodboard_image_size(image, nullptr, &width, &height) || width <= 0) {
    return 1.0f;
  }
  return float(height) / float(width);
}

/* Shared with the attachment ribbon; raw sRGB bytes preserve the board's colors. */
blender::gpu::Texture *mixie_moodboard_srgb_texture(Image *image, ImageUser *image_user)
{
  const int requested_frame = image_user ? image_user->framenr : 0;
  ImageDrawStamp stamp{};
  const bool stamped = image_draw_stamp(image, &stamp);
  auto it = s_srgb_tex_cache.find(image);

  /* Same datablock, same pixels, same movie frame: the texture already on
   * the GPU is the one this redraw would upload. */
  if (stamped && it != s_srgb_tex_cache.end() && it->second.tex != nullptr &&
      stamp_matches(it->second.stamp, stamp) && it->second.frame == requested_frame)
  {
    it->second.last_used_frame = s_cache_frame;
    remember_image_size(stamp, requested_frame, it->second.width, it->second.height);
    return it->second.tex;
  }

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

  /* Same dimensions: reupload. A same-size pixel edit used to return the
   * previous texture because only width/height were compared. */
  if (it != s_srgb_tex_cache.end()) {
    if (ibuf->x == it->second.width && ibuf->y == it->second.height && ibuf->byte_buffer.data) {
      GPU_texture_update(it->second.tex, GPU_DATA_UBYTE, ibuf->byte_buffer.data);
      it->second.frame = requested_frame;
      it->second.last_used_frame = s_cache_frame;
      ImageDrawStamp stored{};
      if (image_draw_stamp(image, &stored)) {
        it->second.stamp = stored;
        remember_image_size(stored, requested_frame, ibuf->x, ibuf->y);
      }
      else {
        it->second.stamp = {};
      }
      BKE_image_release_ibuf(image, ibuf, lock);
      return it->second.tex;
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
      store_cached_tex(image, tex, ibuf->x, ibuf->y, requested_frame);
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
  /* Evict GPU entries not touched this frame: the image was removed, deleted,
   * or culled. The aspect map stays — layout of off-screen tiles still needs
   * it, and this sweep runs after graph layout has already read those sizes. */
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
  s_image_size_cache.clear();
}

/** \} */

}  // namespace blender::ed::mixie
