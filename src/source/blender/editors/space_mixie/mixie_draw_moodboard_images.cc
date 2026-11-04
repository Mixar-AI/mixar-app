/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard image drawing for Mixie space
 */

#include "mixie_draw_moodboard_intern.hh"

#include "GPU_immediate_util.hh"

namespace blender::ed::mixie {


/* -------------------------------------------------------------------- */
/** \name GPU Texture Drawing Helper
 * \{ */

/* Draw the shared texture as an image quad. */
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

void mixie_draw_moodboard_media_preview(Image *image, const rctf &bounds)
{
  if (!image) return;
  ImageUser movie_user{};
  ImageUser *image_user = nullptr;
  if (image->source == IMA_SRC_MOVIE) {
    bool is_playing = false;
    BKE_imageuser_default(&movie_user);
    movie_user.framenr = moodboard_video_playback_frame(image, &is_playing);
    image_user = &movie_user;
  }
  blender::gpu::Texture *texture = mixie_moodboard_srgb_texture(image, image_user);
  if (!texture) return;
  const float source_w = float(GPU_texture_width(texture)), source_h = float(GPU_texture_height(texture));
  const float scale_x = BLI_rctf_size_x(&bounds) / std::max(source_w, 1.0f);
  const float scale_y = BLI_rctf_size_y(&bounds) / std::max(source_h, 1.0f);
  const float scale = std::min(scale_x, scale_y);
  const float width = source_w * scale, height = source_h * scale;
  const float x = BLI_rctf_cent_x(&bounds) - width * 0.5f, y = BLI_rctf_cent_y(&bounds) - height * 0.5f;
  draw_gpu_texture_quad(texture, x, y, width, height);
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

  mixie_moodboard_texture_cache_frame_begin();

  /* Draw each moodboard image at its position with scale */
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, prop, &iter);

  /* Initialize property cache from first item */
  if (iter.valid) {
    init_image_property_cache(&iter.ptr);
  }

  while (iter.valid) {
    PointerRNA itemptr = iter.ptr;

    if (g_img_props.embedded_node_id &&
        RNA_property_string_length(&itemptr, g_img_props.embedded_node_id) > 0)
    {
      RNA_property_collection_next(&iter);
      continue;
    }

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
        ImageUser movie_user{};
        ImageUser *image_user = nullptr;
        bool video_is_playing = false;
        if (image->source == IMA_SRC_MOVIE) {
          BKE_imageuser_default(&movie_user);
          movie_user.framenr = moodboard_video_playback_frame(image, &video_is_playing);
          image_user = &movie_user;
        }

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
        const bool is_selected = g_img_props.selected &&
                                 RNA_property_boolean_get(&itemptr, g_img_props.selected);

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
        if (is_srgb_image || image->source == IMA_SRC_MOVIE) {
          gpu_tex = mixie_moodboard_srgb_texture(image, image_user);
        }
        else {
          gpu_tex = BKE_image_get_gpu_texture(image, image_user);
        }

        bool media_drawn = false;
        float drawn_width = 0.0f;
        float drawn_height = 0.0f;

        if (gpu_tex) {
          /* Use cached GPU texture - much faster than recreating texture every frame */
          int tex_w = GPU_texture_width(gpu_tex);
          int tex_h = GPU_texture_height(gpu_tex);

          /* Calculate display size from texture dimensions */
          const float display_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
          const float display_height =
              (MOODBOARD_IMAGE_BASE_SIZE * float(tex_h) / float(tex_w)) * scale;
          drawn_width = display_width;
          drawn_height = display_height;

          /* Apply transforms (rotation and flips) */
          const float center_x = pos_x + display_width / 2.0f;
          const float center_y = pos_y + display_height / 2.0f;

          GPU_matrix_push();

          /* Translate to center for rotation/flip */
          GPU_matrix_translate_2f(center_x, center_y);

          /* GPU_matrix_rotate_2d and the moodboard RNA property both use degrees. */
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

          mixie_draw_moodboard_media_frame(pos_x, pos_y, display_width, display_height, is_selected);

          /* Draw using cached GPU texture */
          GPU_blend(GPU_BLEND_ALPHA_PREMULT);
          GPU_texture_filter_mode(gpu_tex, true);
          draw_gpu_texture_quad(gpu_tex, pos_x, pos_y, display_width, display_height);
          GPU_blend(GPU_BLEND_NONE);

          mixie_draw_moodboard_annotations(
              &itemptr, v2d, pos_x, pos_y, display_width, display_height, scale);

          /* Draw selection overlay if selected */
          if (is_selected) {
            mixie_draw_moodboard_selection_overlay(v2d, pos_x, pos_y, display_width, display_height);
          }

          GPU_matrix_pop();
          media_drawn = true;
        }
        else {
          /* Fallback: acquire image buffer and draw with immediate mode (slower path)
           * This handles cases where GPU texture cache isn't available */
          void *lock;
          ImBuf *ibuf = BKE_image_acquire_ibuf(image, image_user, &lock);

          if (ibuf) {
            /* Calculate display size */
            const float display_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
            const float display_height =
                (MOODBOARD_IMAGE_BASE_SIZE * float(ibuf->y) / float(ibuf->x)) * scale;
            drawn_width = display_width;
            drawn_height = display_height;

            /* Apply transforms (rotation and flips) */
            const float center_x = pos_x + display_width / 2.0f;
            const float center_y = pos_y + display_height / 2.0f;

            GPU_matrix_push();

            /* Translate to center for rotation/flip */
            GPU_matrix_translate_2f(center_x, center_y);

            /* GPU_matrix_rotate_2d and the moodboard RNA property both use degrees. */
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

            mixie_draw_moodboard_media_frame(pos_x, pos_y, display_width, display_height, is_selected);

            /* Draw image using immediate mode (fallback).
             * Use GPU_SHADER_3D_IMAGE to display without color management transformations. */
            PixelBitmapDrawer drawer(GPU_SHADER_3D_IMAGE);
            GPU_blend(GPU_BLEND_ALPHA_PREMULT);

            if (ibuf->float_buffer.data) {
              drawer.draw(pos_x,
                                             pos_y,
                                             ibuf->x,
                                             ibuf->y,
                                             blender::gpu::TextureFormat::SFLOAT_16_16_16_16,
                                             true,
                                             ibuf->float_buffer.data,
                                             display_width / float(ibuf->x),
                                             display_height / float(ibuf->y), nullptr);
            }
            else if (ibuf->byte_buffer.data) {
              drawer.draw(pos_x,
                                             pos_y,
                                             ibuf->x,
                                             ibuf->y,
                                             blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                             false,
                                             ibuf->byte_buffer.data,
                                             display_width / float(ibuf->x),
                                             display_height / float(ibuf->y), nullptr);
            }

            GPU_blend(GPU_BLEND_NONE);

            mixie_draw_moodboard_annotations(
                &itemptr, v2d, pos_x, pos_y, display_width, display_height, scale);

            /* Draw selection overlay if selected */
            if (is_selected) {
              mixie_draw_moodboard_selection_overlay(
                  v2d, pos_x, pos_y, display_width, display_height);
            }

            GPU_matrix_pop();
            media_drawn = true;

            BKE_image_release_ibuf(image, ibuf, lock);
          }
        }

        if (media_drawn && image->source == IMA_SRC_MOVIE) {
          const rctf media_rect = {pos_x, pos_x + drawn_width, pos_y, pos_y + drawn_height};
          /* A board tile is keyed by its own graph id, so hover survives reorders. */
          char media_key[MIXIE_GRAPH_ID_BUF];
          mixie_rna_string_get_clamped(&itemptr, "node_id", media_key, sizeof(media_key));
          const bool hovered = moodboard_video_card_register(
              CTX_wm_region(C), media_key, media_rect);
          mixie_draw_moodboard_video_overlay(
              v2d, media_rect, hovered, video_is_playing, moodboard_video_is_muted(image));
        }
      }
    }

    RNA_property_collection_next(&iter);
  }

  RNA_property_collection_end(&iter);

  mixie_moodboard_texture_cache_frame_end();
}

/** \} */

}  // namespace blender::ed::mixie
