/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Message-bubble image attachments are drawn as View2D-space quads so the
 * thumbnail shares the GPU matrix (and left inset) of the message text.
 * Never blit those with PixelBitmapDrawer / immDrawPixelsTex — that path is
 * pixel-space and clips a tall sheet to a sliver once View2D ortho is on.
 * The fitted tiles and lightbox below are pixel-space by design (they are
 * drawn in the window overlay pass) and keep the raw-pixel blit.
 */

#include <cstring>

#include "BLI_listbase.h"
#include "BLI_path_utils.hh"
#include "BLI_rect.h"
#include "BLI_string.h"

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
  if (!bmain || !path || !path[0]) {
    return nullptr;
  }

  if (source == 1) {
    /* BLEND_DATA - look up by name */
    return find_image_by_name(bmain, path);
  }

  /* FILE - load from disk. First check if already loaded by basename. */
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

/** Cap the thumbnail to the bubble's text column when that is narrower. */
static float attachment_max_width(const ChatImageStyle *style, float available_width)
{
  float max_w = style->max_width;
  if (available_width > 0.0f && available_width < max_w) {
    max_w = available_width;
  }
  return max_w;
}

static ImBuf *acquire_attachment_ibuf(Image *image, void **r_lock)
{
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, r_lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, *r_lock);
    *r_lock = nullptr;
    return nullptr;
  }
  if (ibuf->byte_buffer.data == nullptr && ibuf->float_buffer.data != nullptr) {
    IMB_byte_from_float(ibuf);
  }
  return ibuf;
}

static gpu::Texture *upload_attachment_texture(const ImBuf *ibuf)
{
  if (!ibuf->byte_buffer.data) {
    return nullptr;
  }
  gpu::Texture *tex = GPU_texture_create_2d("mixie_chat_attachment",
                                            ibuf->x,
                                            ibuf->y,
                                            1,
                                            gpu::TextureFormat::UNORM_8_8_8_8,
                                            GPU_TEXTURE_USAGE_GENERAL,
                                            nullptr);
  if (tex) {
    GPU_texture_update(tex, GPU_DATA_UBYTE, ibuf->byte_buffer.data);
  }
  return tex;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Image Attachment Widget
 * \{ */

float chat_ui_calc_image_attachment_height(Main *bmain,
                                           const char *image_path,
                                           int image_source,
                                           const ChatImageStyle *style,
                                           float available_width)
{
  Image *image = load_or_find_image(bmain, image_path, image_source);
  if (!image) {
    return 0.0f;
  }

  void *lock = nullptr;
  ImBuf *ibuf = acquire_attachment_ibuf(image, &lock);
  if (!ibuf) {
    return 0.0f;
  }

  float display_width, display_height;
  chat_ui_calc_image_bounds(ibuf->x,
                            ibuf->y,
                            attachment_max_width(style, available_width),
                            style->max_height,
                            &display_width,
                            &display_height);

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

  /* Acquire the raw image buffer instead of BKE_image_get_gpu_texture.
   * That helper applies colorspace conversion (sRGB → Linear) when creating
   * the GPU texture; GPU_SHADER_3D_IMAGE then outputs those linear values
   * without an inverse transform, producing washed-out images. The ImBuf
   * path uploads raw sRGB bytes so display colors match the source. */
  void *lock = nullptr;
  ImBuf *ibuf = acquire_attachment_ibuf(image, &lock);
  if (!ibuf) {
    return 0.0f;
  }

  float display_width, display_height;
  chat_ui_calc_image_bounds(ibuf->x,
                            ibuf->y,
                            attachment_max_width(style, max_width),
                            style->max_height,
                            &display_width,
                            &display_height);

  /* `x` is the left edge of the thumbnail — same inset as the bubble text.
   * `y` is the top of the attachment slot; `style->margin` is vertical only. */
  rctf rect;
  rect.xmin = x;
  rect.xmax = x + display_width;
  rect.ymax = y - style->margin;
  rect.ymin = rect.ymax - display_height;

  gpu::Texture *tex = upload_attachment_texture(ibuf);
  if (tex) {
    GPU_blend(GPU_BLEND_ALPHA);
    chat_ui_draw_image(tex, &rect, style->corner_radius);
    GPU_blend(GPU_BLEND_NONE);
    GPU_texture_free(tex);
  }

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
