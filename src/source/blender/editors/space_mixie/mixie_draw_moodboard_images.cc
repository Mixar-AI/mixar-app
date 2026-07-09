/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard image drawing for Mixie space
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
  uint64_t last_used_frame;
};

static std::unordered_map<Image *, CachedImageTex> s_srgb_tex_cache;
static uint64_t s_cache_frame = 0;

/**
 * Return (or create) a cached UNORM GPU texture for \a image.
 * The texture stores the raw byte pixels without any color-space conversion
 * so that GPU_SHADER_3D_IMAGE displays the original sRGB values.
 */
static blender::gpu::Texture *get_cached_srgb_texture(Image *image)
{
  auto it = s_srgb_tex_cache.find(image);

  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return nullptr;
  }

  /* Return cached texture if dimensions still match. */
  if (it != s_srgb_tex_cache.end()) {
    if (ibuf->x == it->second.width && ibuf->y == it->second.height) {
      it->second.last_used_frame = s_cache_frame;
      BKE_image_release_ibuf(image, ibuf, lock);
      return it->second.tex;
    }
    /* Stale (e.g. after crop) — recreate. */
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
      s_srgb_tex_cache[image] = {tex, ibuf->x, ibuf->y, s_cache_frame};
    }
  }

  BKE_image_release_ibuf(image, ibuf, lock);
  return tex;
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

/* -------------------------------------------------------------------- */
/** \name GPU Texture Drawing Helper
 * \{ */

/**
 * Draw a GPU texture as a quad at the given position and size.
 * Helper function to avoid code duplication between cached and fallback paths.
 */
static void draw_gpu_texture_quad(blender::gpu::Texture *tex,
                                  float pos_x,
                                  float pos_y,
                                  float draw_width,
                                  float draw_height)
{
  GPU_texture_bind(tex, 0);

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  uint texcoord = GPU_vertformat_attr_add(
      format, "texCoord", blender::gpu::VertAttrType::SFLOAT_32_32);

  /* Use GPU_SHADER_3D_IMAGE to display images without color management transformations.
   * Images are already in sRGB color space and should be displayed as-is. */
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);

  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr2f(texcoord, 0.0f, 0.0f);
  immVertex2f(pos, pos_x, pos_y);
  immAttr2f(texcoord, 1.0f, 0.0f);
  immVertex2f(pos, pos_x + draw_width, pos_y);
  immAttr2f(texcoord, 1.0f, 1.0f);
  immVertex2f(pos, pos_x + draw_width, pos_y + draw_height);
  immAttr2f(texcoord, 0.0f, 1.0f);
  immVertex2f(pos, pos_x, pos_y + draw_height);
  immEnd();

  immUnbindProgram();
  GPU_texture_unbind(tex);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Images Drawing
 * \{ */

void mixie_draw_moodboard_images(const bContext *C, View2D *v2d)
{
  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");

  if (!prop) {
    return;
  }

  s_cache_frame++;

  /* Draw each moodboard image at its position with scale */
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, prop, &iter);

  /* Initialize property cache from first item */
  if (iter.valid) {
    init_image_property_cache(&iter.ptr);
  }

  while (iter.valid) {
    PointerRNA itemptr = iter.ptr;

    /* Use cached property pointers for faster access */
    if (g_img_props.image && g_img_props.position_x && g_img_props.position_y &&
        g_img_props.scale)
    {
      /* Check for display_image first (segment overlay), fallback to original image */
      Image *image = nullptr;
      if (g_img_props.display_image) {
        PointerRNA display_ptr = RNA_property_pointer_get(&itemptr, g_img_props.display_image);
        image = (Image *)display_ptr.data;
      }
      if (!image) {
        PointerRNA image_ptr = RNA_property_pointer_get(&itemptr, g_img_props.image);
        image = (Image *)image_ptr.data;
      }

      if (image) {
        float pos_x = RNA_property_float_get(&itemptr, g_img_props.position_x);
        float pos_y = RNA_property_float_get(&itemptr, g_img_props.position_y);
        float scale = RNA_property_float_get(&itemptr, g_img_props.scale);
        float rotation = g_img_props.rotation ?
                             RNA_property_float_get(&itemptr, g_img_props.rotation) :
                             0.0f;
        bool flip_horizontal = g_img_props.flip_horizontal ?
                                   RNA_property_boolean_get(&itemptr, g_img_props.flip_horizontal) :
                                   false;
        bool flip_vertical = g_img_props.flip_vertical ?
                                 RNA_property_boolean_get(&itemptr, g_img_props.flip_vertical) :
                                 false;

        /* Skip images that can't be drawn (like Render Result without data) */
        if (image->source == IMA_SRC_VIEWER) {
          RNA_property_collection_next(&iter);
          continue;
        }

        /* Early view frustum culling - estimate size before acquiring buffer.
         * Use a conservative estimate based on scale to avoid expensive buffer acquisition
         * for images that are definitely outside the viewport. */
        const float estimated_size = MOODBOARD_IMAGE_BASE_SIZE * scale;
        if (!is_rect_in_view(v2d, pos_x, pos_y, estimated_size, estimated_size)) {
          RNA_property_collection_next(&iter);
          continue;
        }

        /* Get GPU texture. Non-Color images use Blender's built-in GPU cache.
         * sRGB images use our own UNORM cache to preserve raw byte colours AND
         * avoid per-frame temporary texture creation that crashes Metal on macOS. */
        const char *data_colorspace = IMB_colormanagement_role_colorspace_name_get(COLOR_ROLE_DATA);
        bool is_srgb_image = (data_colorspace &&
                              strcmp(image->colorspace_settings.name, data_colorspace) != 0);

        blender::gpu::Texture *gpu_tex = nullptr;
        if (is_srgb_image) {
          gpu_tex = get_cached_srgb_texture(image);
        }
        else {
          gpu_tex = BKE_image_get_gpu_texture(image, nullptr);
        }

        if (gpu_tex) {
          /* Use cached GPU texture - much faster than recreating texture every frame */
          int tex_w = GPU_texture_width(gpu_tex);
          int tex_h = GPU_texture_height(gpu_tex);

          /* Calculate display size from texture dimensions */
          const float display_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
          const float display_height =
              (MOODBOARD_IMAGE_BASE_SIZE * float(tex_h) / float(tex_w)) * scale;

          /* Apply transforms (rotation and flips) */
          const float center_x = pos_x + display_width / 2.0f;
          const float center_y = pos_y + display_height / 2.0f;

          GPU_matrix_push();

          /* Translate to center for rotation/flip */
          GPU_matrix_translate_2f(center_x, center_y);

          /* Apply rotation (value is already in radians from RNA ANGLE property) */
          if (rotation != 0.0f) {
            GPU_matrix_rotate_2d(rotation);
          }

          /* Apply flips as negative scale */
          float flip_scale_x = flip_horizontal ? -1.0f : 1.0f;
          float flip_scale_y = flip_vertical ? -1.0f : 1.0f;
          if (flip_scale_x != 1.0f || flip_scale_y != 1.0f) {
            GPU_matrix_scale_2f(flip_scale_x, flip_scale_y);
          }

          /* Translate back from center */
          GPU_matrix_translate_2f(-center_x, -center_y);

          /* Draw using cached GPU texture */
          GPU_blend(GPU_BLEND_ALPHA_PREMULT);
          GPU_texture_filter_mode(gpu_tex, true);
          draw_gpu_texture_quad(gpu_tex, pos_x, pos_y, display_width, display_height);
          GPU_blend(GPU_BLEND_NONE);

          /* Draw selection overlay if selected */
          bool is_selected = g_img_props.selected ?
                                 RNA_property_boolean_get(&itemptr, g_img_props.selected) :
                                 false;
          if (is_selected) {
            mixie_draw_moodboard_selection_overlay(v2d, pos_x, pos_y, display_width, display_height);
          }

          GPU_matrix_pop();
        }
        else {
          /* Fallback: acquire image buffer and draw with immediate mode (slower path)
           * This handles cases where GPU texture cache isn't available */
          void *lock;
          ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);

          if (ibuf) {
            /* Calculate display size */
            const float display_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
            const float display_height =
                (MOODBOARD_IMAGE_BASE_SIZE * float(ibuf->y) / float(ibuf->x)) * scale;

            /* Apply transforms (rotation and flips) */
            const float center_x = pos_x + display_width / 2.0f;
            const float center_y = pos_y + display_height / 2.0f;

            GPU_matrix_push();

            /* Translate to center for rotation/flip */
            GPU_matrix_translate_2f(center_x, center_y);

            /* Apply rotation (value is already in radians from RNA ANGLE property) */
            if (rotation != 0.0f) {
              GPU_matrix_rotate_2d(rotation);
            }

            /* Apply flips as negative scale */
            float flip_scale_x = flip_horizontal ? -1.0f : 1.0f;
            float flip_scale_y = flip_vertical ? -1.0f : 1.0f;
            if (flip_scale_x != 1.0f || flip_scale_y != 1.0f) {
              GPU_matrix_scale_2f(flip_scale_x, flip_scale_y);
            }

            /* Translate back from center */
            GPU_matrix_translate_2f(-center_x, -center_y);

            /* Draw image using immediate mode (fallback).
             * Use GPU_SHADER_3D_IMAGE to display without color management transformations. */
            IMMDrawPixelsTexState state = immDrawPixelsTexSetup(GPU_SHADER_3D_IMAGE);
            GPU_blend(GPU_BLEND_ALPHA_PREMULT);

            if (ibuf->float_buffer.data) {
              immDrawPixelsTexScaledFullSize(&state,
                                             pos_x,
                                             pos_y,
                                             ibuf->x,
                                             ibuf->y,
                                             blender::gpu::TextureFormat::SFLOAT_16_16_16_16,
                                             true,
                                             ibuf->float_buffer.data,
                                             display_width / float(ibuf->x),
                                             display_height / float(ibuf->y),
                                             1.0f,
                                             1.0f,
                                             nullptr);
            }
            else if (ibuf->byte_buffer.data) {
              immDrawPixelsTexScaledFullSize(&state,
                                             pos_x,
                                             pos_y,
                                             ibuf->x,
                                             ibuf->y,
                                             blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                             false,
                                             ibuf->byte_buffer.data,
                                             display_width / float(ibuf->x),
                                             display_height / float(ibuf->y),
                                             1.0f,
                                             1.0f,
                                             nullptr);
            }

            GPU_blend(GPU_BLEND_NONE);

            /* Draw selection overlay if selected */
            bool is_selected = g_img_props.selected ?
                                   RNA_property_boolean_get(&itemptr, g_img_props.selected) :
                                   false;
            if (is_selected) {
              mixie_draw_moodboard_selection_overlay(
                  v2d, pos_x, pos_y, display_width, display_height);
            }

            GPU_matrix_pop();

            BKE_image_release_ibuf(image, ibuf, lock);
          }
        }
      }
    }

    RNA_property_collection_next(&iter);
  }

  RNA_property_collection_end(&iter);

  /* Evict sRGB cache entries not used this frame (image removed / deleted). */
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

/** \} */

}  // namespace blender::ed::mixie
