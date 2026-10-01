/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Image loading, measurement and drawing for chat attachments.
 */

#include <cstring>

#include "BLI_listbase.h"
#include "BLI_path_utils.hh"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"
#include "BKE_image.hh"
#include "BKE_main.hh"

#include "DNA_image_types.h"

#include "BIF_glutil.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "mixie_chat_ui_types.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Image Loading
 * \{ */

/**
 * Find an image in Main data by name.
 */
static Image *find_image_by_name(Main *bmain, const char *name)
{
  if (!bmain || !name || name[0] == '\0') {
    return nullptr;
  }

  /* Images are stored with "IM" prefix in id.name, search from offset 2 */
  return static_cast<Image *>(BLI_findstring(&bmain->images, name, offsetof(ID, name) + 2));
}

/**
 * Load or find an image by path and source type.
 * Supports both BLEND_DATA (name lookup) and FILE (disk loading).
 */
static Image *load_or_find_image(Main *bmain, const char *path, int source)
{
  if (!bmain || !path || path[0] == '\0') {
    return nullptr;
  }

  if (source == 1) {
    /* BLEND_DATA - look up by name */
    return find_image_by_name(bmain, path);
  }
  else {
    /* FILE - load from disk */
    /* First check if already loaded by basename */
    const char *basename = BLI_path_basename(path);
    Image *existing = find_image_by_name(bmain, basename);
    if (existing) {
      return existing;
    }

    /* Load from file. Tag as sRGB so raw-upload path displays correctly. */
    Image *img = BKE_image_load_exists(bmain, path);
    if (img) {
      STRNCPY(img->colorspace_settings.name, "sRGB");
    }
    return img;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Image Attachment Widget
 * \{ */

float chat_ui_calc_image_attachment_height(Main *bmain,
                                           const char *image_path,
                                           int image_source,
                                           const ChatImageStyle *style)
{
  Image *image = load_or_find_image(bmain, image_path, image_source);
  if (!image) {
    return 0.0f;
  }

  /* Use ImBuf dimensions instead of GPU texture to stay consistent
   * with the raw-upload draw path (avoids creating a GPU texture
   * just to query width/height). */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return 0.0f;
  }

  float display_width, display_height;
  chat_ui_calc_image_bounds(
      ibuf->x, ibuf->y, style->max_width, style->max_height, &display_width, &display_height);

  BKE_image_release_ibuf(image, ibuf, lock);
  return display_height + style->margin * 2.0f;
}

float chat_ui_draw_image_attachment(Main *bmain,
                                    const char *image_path,
                                    int image_source,
                                    float x,
                                    float y,
                                    float max_width,
                                    const ChatImageStyle *style)
{
  Image *image = load_or_find_image(bmain, image_path, image_source);
  if (!image) {
    return 0.0f;
  }

  /* Acquire the raw image buffer directly instead of BKE_image_get_gpu_texture.
   * BKE_image_get_gpu_texture applies colorspace conversion (sRGB → Linear)
   * when creating the GPU texture.  GPU_SHADER_3D_IMAGE then outputs those
   * linear values without an inverse transform, producing washed-out images.
   * The ImBuf path uploads raw pixel data (already sRGB-encoded for
   * photos/screenshots) straight to the GPU for correct display colors. */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return 0.0f;
  }

  /* Clamp style max_width to available width */
  float effective_max_width = (style->max_width < max_width) ? style->max_width : max_width;

  float display_width, display_height;
  chat_ui_calc_image_bounds(
      ibuf->x, ibuf->y, effective_max_width, style->max_height, &display_width, &display_height);

  /* Draw position */
  float draw_x = x + style->margin;
  float draw_y = y - display_height - style->margin;

  /* Draw using raw pixel upload — bypasses colorspace conversion. */
  PixelBitmapDrawer drawer(GPU_SHADER_3D_IMAGE);
  GPU_blend(GPU_BLEND_ALPHA_PREMULT);

  if (ibuf->float_buffer.data) {
    drawer.draw(draw_x,
                                   draw_y,
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::SFLOAT_16_16_16_16,
                                   true,
                                   ibuf->float_buffer.data,
                                   display_width / float(ibuf->x),
                                   display_height / float(ibuf->y), nullptr);
  }
  else if (ibuf->byte_buffer.data) {
    drawer.draw(draw_x,
                                   draw_y,
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                   false,
                                   ibuf->byte_buffer.data,
                                   display_width / float(ibuf->x),
                                   display_height / float(ibuf->y), nullptr);
  }

  GPU_blend(GPU_BLEND_NONE);
  BKE_image_release_ibuf(image, ibuf, lock);

  return display_height + style->margin * 2.0f;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Fitted Image (tiles + lightbox)
 * \{ */

bool chat_ui_image_pixel_size(Main *bmain,
                              const char *image_path,
                              int image_source,
                              int *r_width,
                              int *r_height)
{
  *r_width = 0;
  *r_height = 0;
  Image *image = load_or_find_image(bmain, image_path, image_source);
  if (!image) {
    return false;
  }
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  const bool ok = ibuf && ibuf->x > 0 && ibuf->y > 0;
  if (ok) {
    *r_width = ibuf->x;
    *r_height = ibuf->y;
  }
  BKE_image_release_ibuf(image, ibuf, lock);
  return ok;
}

bool chat_ui_draw_image_fitted(Main *bmain,
                               const char *image_path,
                               int image_source,
                               const rctf *box,
                               rctf *r_drawn)
{
  if (r_drawn) {
    memset(r_drawn, 0, sizeof(*r_drawn));
  }
  Image *image = load_or_find_image(bmain, image_path, image_source);
  if (!image) {
    return false;
  }
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return false;
  }

  const float box_w = BLI_rctf_size_x(box);
  const float box_h = BLI_rctf_size_y(box);
  float display_width, display_height;
  chat_ui_calc_image_bounds(ibuf->x, ibuf->y, box_w, box_h, &display_width, &display_height);
  if (display_width <= 0.0f || display_height <= 0.0f) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return false;
  }

  /* Center inside the box (letterbox / pillarbox as the aspect demands). */
  const float draw_x = box->xmin + (box_w - display_width) * 0.5f;
  const float draw_y = box->ymin + (box_h - display_height) * 0.5f;

  /* Same raw-pixel upload as chat_ui_draw_image_attachment: the ImBuf path
   * keeps captures (already sRGB) from washing out. */
  PixelBitmapDrawer drawer(GPU_SHADER_3D_IMAGE);
  GPU_blend(GPU_BLEND_ALPHA_PREMULT);
  if (ibuf->float_buffer.data) {
    drawer.draw(draw_x, draw_y, ibuf->x, ibuf->y,
                blender::gpu::TextureFormat::SFLOAT_16_16_16_16, true,
                ibuf->float_buffer.data,
                display_width / float(ibuf->x), display_height / float(ibuf->y), nullptr);
  }
  else if (ibuf->byte_buffer.data) {
    drawer.draw(draw_x, draw_y, ibuf->x, ibuf->y,
                blender::gpu::TextureFormat::UNORM_8_8_8_8, false,
                ibuf->byte_buffer.data,
                display_width / float(ibuf->x), display_height / float(ibuf->y), nullptr);
  }
  GPU_blend(GPU_BLEND_NONE);
  BKE_image_release_ibuf(image, ibuf, lock);

  if (r_drawn) {
    r_drawn->xmin = draw_x;
    r_drawn->xmax = draw_x + display_width;
    r_drawn->ymin = draw_y;
    r_drawn->ymax = draw_y + display_height;
  }
  return true;
}

/** \} */

}  // namespace blender
