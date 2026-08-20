/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Thumbnail rendering for footer attachments.
 * Handles image loading, aspect-correct display, and border drawing.
 */

#include "BLI_fileops.h"
#include "BLI_listbase.h"
#include "BLI_path_utils.hh"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_image.hh"
#include "BKE_main.hh"

#include "DNA_ID.h"
#include "DNA_image_types.h"

#include "BIF_glutil.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "UI_interface.hh"

#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Image Loading
 * \{ */

/**
 * Load image by path and source type.
 * Source types: 0 = FILE (disk), 1 = BLEND_DATA (internal)
 *
 * \param bmain: Main database for image lookup
 * \param path: Image path (filepath or internal name)
 * \param source: Source type (0=FILE, 1=BLEND_DATA)
 * \return Loaded image or nullptr if not found
 */
Image *footer_thumbnails_load_image(Main *bmain, const char *path, int source)
{
  if (!bmain || !path || path[0] == '\0') {
    return nullptr;
  }

  if (source == 1) {
    /* BLEND_DATA - look up by name in main database */
    return static_cast<Image *>(BLI_findstring(&bmain->images, path, offsetof(ID, name) + 2));
  }
  else {
    /* FILE - load from disk with caching */
    const char *basename = BLI_path_basename(path);

    /* Check if already loaded to avoid redundant disk I/O */
    Image *existing = static_cast<Image *>(
        BLI_findstring(&bmain->images, basename, offsetof(ID, name) + 2));
    if (existing) {
      return existing;
    }

    /* Defensive: verify file exists before attempting to load */
    if (!BLI_exists(path)) {
      fprintf(stderr, "Mixie Chat: Image file not found: %s\n", path);
      return nullptr;
    }

    Image *img = BKE_image_load_exists(bmain, path);
    if (!img) {
      fprintf(stderr, "Mixie Chat: Failed to load image: %s\n", path);
      return nullptr;
    }
    /* File-based images (photos, screenshots) are virtually always
     * sRGB-encoded.  Without this tag Blender treats the byte data as
     * scene-linear, producing washed-out / shifted thumbnails. */
    STRNCPY(img->colorspace_settings.name, "sRGB");
    return img;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Thumbnail Drawing
 * \{ */

/**
 * Draw an image thumbnail at the specified position with aspect-correct scaling.
 * Centers the image within the thumbnail area and maintains aspect ratio.
 *
 * PERFORMANCE: GPU_blend already set by caller to avoid redundant state changes.
 *
 * \param bmain: Main database for image lookup
 * \param path: Image path
 * \param source: Source type (0=FILE, 1=BLEND_DATA)
 * \param x: Bottom-left X coordinate
 * \param y: Bottom-left Y coordinate
 * \param size: Thumbnail size (width and height)
 */
void footer_thumbnails_draw_image(Main *bmain,
                                   const char *path,
                                   int source,
                                   float x,
                                   float y,
                                   float size)
{
  /* Early return for invalid inputs */
  if (!bmain || !path || size <= 0.0f) {
    return;
  }

  /* Load image */
  Image *image = footer_thumbnails_load_image(bmain, path, source);
  if (!image) {
    return;
  }

  /* Acquire the raw image buffer directly instead of BKE_image_get_gpu_texture.
   * BKE_image_get_gpu_texture applies the image's colorspace conversion
   * (sRGB → Linear) when creating the GPU texture.  GPU_SHADER_3D_IMAGE then
   * outputs those linear values without an inverse transform, producing
   * washed-out thumbnails.  The ImBuf path uploads raw pixel data (already
   * sRGB-encoded for photos/screenshots) straight to the GPU — matching what
   * the moodboard renderer does for correct display colors. */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || (ibuf->x <= 0) || (ibuf->y <= 0)) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return;
  }

  /* Calculate aspect-correct dimensions */
  float aspect = float(ibuf->x) / float(ibuf->y);
  float draw_w, draw_h;
  if (aspect > 1.0f) {
    draw_w = size;
    draw_h = size / aspect;
  }
  else {
    draw_h = size;
    draw_w = size * aspect;
  }

  /* Center in thumbnail area */
  float draw_x = x + (size - draw_w) * 0.5f;
  float draw_y = y + (size - draw_h) * 0.5f;

  /* Draw using raw pixel upload — bypasses colorspace conversion. */
  IMMDrawPixelsTexState state = immDrawPixelsTexSetup(GPU_SHADER_3D_IMAGE);
  GPU_blend(GPU_BLEND_ALPHA_PREMULT);

  if (ibuf->float_buffer.data) {
    immDrawPixelsTexScaledFullSize(&state,
                                   draw_x,
                                   draw_y,
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::SFLOAT_16_16_16_16,
                                   true,
                                   ibuf->float_buffer.data,
                                   draw_w / float(ibuf->x),
                                   draw_h / float(ibuf->y),
                                   1.0f,
                                   1.0f,
                                   nullptr);
  }
  else if (ibuf->byte_buffer.data) {
    immDrawPixelsTexScaledFullSize(&state,
                                   draw_x,
                                   draw_y,
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                   false,
                                   ibuf->byte_buffer.data,
                                   draw_w / float(ibuf->x),
                                   draw_h / float(ibuf->y),
                                   1.0f,
                                   1.0f,
                                   nullptr);
  }

  GPU_blend(GPU_BLEND_NONE);
  BKE_image_release_ibuf(image, ibuf, lock);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Border Drawing
 * \{ */

/**
 * Draw a rounded border around a thumbnail.
 * Uses theme values for border radius and color.
 *
 * \param x: Bottom-left X coordinate
 * \param y: Bottom-left Y coordinate
 * \param size: Thumbnail size (width and height)
 * \param color: RGBA border color
 */
void footer_thumbnails_draw_border(float x, float y, float size, const float color[4])
{
  /* Get border radius from cached theme */
  const struct FooterThemeCache *theme = footer_cache_get_theme();
  const float border_radius = theme ? theme->border_radius : 8.0f;

  /* Setup rectangle */
  rctf rect;
  rect.xmin = x;
  rect.ymin = y;
  rect.xmax = x + size;
  rect.ymax = y + size;

  /* Set all corners to be rounded */
  ui::draw_roundbox_corner_set(ui::CNR_ALL);

  /* Draw unfilled rounded box (border only) */
  ui::draw_roundbox_4fv(&rect, false, border_radius, color);
}

/** \} */
}  // namespace blender
