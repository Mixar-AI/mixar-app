/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Mixie3D mode drawing for Mixie space
 */

#include <algorithm>

#include "BLF_api.hh"

#include "BKE_context.hh"
#include "BKE_image.hh"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "BIF_glutil.hh"

#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"

#include "mixie_intern.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Mixie3D Preview Thumbnail Drawing
 * \{ */

void mixie_draw_sam3d_preview_thumbnail(Image *image,
                                        int x,
                                        int y,
                                        int width,
                                        int height,
                                        bool is_selected)
{
  if (!image) {
    return;
  }

  /* Skip viewer images */
  if (image->source == IMA_SRC_VIEWER) {
    return;
  }

  /* Get image buffer */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);

  if (!ibuf) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return;
  }

  /* Check if we have pixel data */
  if (!ibuf->float_buffer.data && !ibuf->byte_buffer.data) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return;
  }

  /* Draw selection border if selected */
  if (is_selected) {
    GPUVertFormat *format = immVertexFormat();
    uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);

    GPU_blend(GPU_BLEND_ALPHA);
    immUniformColor4f(0.3f, 0.6f, 1.0f, 0.8f);

    /* Draw thicker border */
    const int border = SAM3D_SELECTION_BORDER;
    immRectf(pos,
             float(x - border),
             float(y - border),
             float(x + width + border),
             float(y + height + border));

    GPU_blend(GPU_BLEND_NONE);
    immUnbindProgram();
  }

  /* Set up image drawing.
   * Use GPU_SHADER_3D_IMAGE to display without color management transformations. */
  IMMDrawPixelsTexState state = immDrawPixelsTexSetup(GPU_SHADER_3D_IMAGE);

  GPU_blend(GPU_BLEND_ALPHA_PREMULT);

  /* Choose the appropriate buffer */
  if (ibuf->float_buffer.data) {
    /* Draw float buffer */
    immDrawPixelsTexScaledFullSize(&state,
                                   float(x),
                                   float(y),
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::SFLOAT_16_16_16_16,
                                   true,
                                   ibuf->float_buffer.data,
                                   float(width) / float(ibuf->x),
                                   float(height) / float(ibuf->y),
                                   1.0f,
                                   1.0f,
                                   nullptr);
  }
  else if (ibuf->byte_buffer.data) {
    /* Draw byte buffer */
    immDrawPixelsTexScaledFullSize(&state,
                                   float(x),
                                   float(y),
                                   ibuf->x,
                                   ibuf->y,
                                   blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                   false,
                                   ibuf->byte_buffer.data,
                                   float(width) / float(ibuf->x),
                                   float(height) / float(ibuf->y),
                                   1.0f,
                                   1.0f,
                                   nullptr);
  }

  GPU_blend(GPU_BLEND_NONE);

  BKE_image_release_ibuf(image, ibuf, lock);

  /* Draw delete button (X) in top-right corner */
  const int delete_btn_size = SAM3D_DELETE_BTN_SIZE;
  const int delete_btn_margin = SAM3D_DELETE_BTN_MARGIN;
  const int delete_btn_x = x + width - delete_btn_size - delete_btn_margin;
  const int delete_btn_y = y + height - delete_btn_size - delete_btn_margin;

  GPUVertFormat *del_format = immVertexFormat();
  uint del_pos = GPU_vertformat_attr_add(del_format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);

  GPU_blend(GPU_BLEND_ALPHA);

  /* Draw button background (semi-transparent red) */
  immUniformColor4f(0.8f, 0.2f, 0.2f, 0.8f);
  immRectf(del_pos,
           float(delete_btn_x),
           float(delete_btn_y),
           float(delete_btn_x + delete_btn_size),
           float(delete_btn_y + delete_btn_size));

  /* Draw X (two diagonal lines) */
  immUniformColor4f(1.0f, 1.0f, 1.0f, 1.0f);
  GPU_line_width(2.0f);
  const int x_margin = SAM3D_DELETE_X_MARGIN;

  immBegin(GPU_PRIM_LINES, 4);
  /* Line from top-left to bottom-right */
  immVertex2f(
      del_pos, float(delete_btn_x + x_margin), float(delete_btn_y + delete_btn_size - x_margin));
  immVertex2f(
      del_pos, float(delete_btn_x + delete_btn_size - x_margin), float(delete_btn_y + x_margin));
  /* Line from top-right to bottom-left */
  immVertex2f(del_pos,
              float(delete_btn_x + delete_btn_size - x_margin),
              float(delete_btn_y + delete_btn_size - x_margin));
  immVertex2f(del_pos, float(delete_btn_x + x_margin), float(delete_btn_y + x_margin));
  immEnd();

  GPU_line_width(1.0f);
  GPU_blend(GPU_BLEND_NONE);
  immUnbindProgram();
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Mixie3D Mode Drawing
 * \{ */

void mixie_draw_sam3d_mode(const bContext *C, ARegion *region)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }

  float region_width = float(region->winx);
  float region_height = float(region->winy);

  /* Define layout constants using values from mixie_intern.hh */
  const int PREVIEW_HEIGHT = int(region_height * SAM3D_PREVIEW_HEIGHT_RATIO);
  const int PREVIEW_PADDING = SAM3D_PREVIEW_PADDING;
  const int PREVIEW_GAP = SAM3D_PREVIEW_GAP;
  const int PREVIEW_THUMB_HEIGHT = PREVIEW_HEIGHT - (2 * PREVIEW_PADDING);

  /* Calculate areas */
  float main_area_height = region_height - PREVIEW_HEIGHT;

  /* Get the selected image from scene property */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *image_prop = RNA_struct_find_property(&scene_ptr, "mixie_sam3d_image");

  if (!image_prop) {
    /* Draw placeholder if property doesn't exist */
    GPUVertFormat *format = immVertexFormat();
    uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    immUniformColor4f(0.2f, 0.2f, 0.2f, 1.0f);
    immRectf(pos, 0.0f, PREVIEW_HEIGHT, region_width, region_height);
    immUnbindProgram();

    /* Draw preview area background */
    format = immVertexFormat();
    pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    immUniformColor4f(0.15f, 0.15f, 0.15f, 1.0f);
    immRectf(pos, 0.0f, 0.0f, region_width, float(PREVIEW_HEIGHT));
    immUnbindProgram();
    return;
  }

  PointerRNA image_ptr = RNA_property_pointer_get(&scene_ptr, image_prop);
  Image *image = (Image *)image_ptr.data;

  /* ===== DRAW MAIN IMAGE AREA (TOP) ===== */
  if (image && image->source != IMA_SRC_VIEWER) {
    /* Get image buffer */
    void *lock;
    ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);

    if (ibuf && (ibuf->float_buffer.data || ibuf->byte_buffer.data)) {
      /* Calculate image display size and position (centered in main area) */
      float img_width = float(ibuf->x);
      float img_height = float(ibuf->y);

      /* Calculate scale to fit image in main area */
      float scale_x = region_width / img_width;
      float scale_y = main_area_height / img_height;
      float scale = std::min(scale_x, scale_y) * 0.9f; /* 90% to leave some margin */

      float display_width = img_width * scale;
      float display_height = img_height * scale;
      float display_x = (region_width - display_width) / 2.0f;
      float display_y = PREVIEW_HEIGHT + (main_area_height - display_height) / 2.0f;

      /* Set up image drawing.
       * Use GPU_SHADER_3D_IMAGE to display without color management transformations. */
      IMMDrawPixelsTexState state = immDrawPixelsTexSetup(GPU_SHADER_3D_IMAGE);

      GPU_blend(GPU_BLEND_ALPHA_PREMULT);

      /* Choose the appropriate buffer */
      if (ibuf->float_buffer.data) {
        /* Draw float buffer */
        immDrawPixelsTexScaledFullSize(&state,
                                       display_x,
                                       display_y,
                                       ibuf->x,
                                       ibuf->y,
                                       blender::gpu::TextureFormat::SFLOAT_16_16_16_16,
                                       true,
                                       ibuf->float_buffer.data,
                                       display_width / img_width,
                                       display_height / img_height,
                                       1.0f,
                                       1.0f,
                                       nullptr);
      }
      else if (ibuf->byte_buffer.data) {
        /* Draw byte buffer */
        immDrawPixelsTexScaledFullSize(&state,
                                       display_x,
                                       display_y,
                                       ibuf->x,
                                       ibuf->y,
                                       blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                       false,
                                       ibuf->byte_buffer.data,
                                       display_width / img_width,
                                       display_height / img_height,
                                       1.0f,
                                       1.0f,
                                       nullptr);
      }

      GPU_blend(GPU_BLEND_NONE);

      /* --- Draw Segmentation Box --- */
      PropertyRNA *box_visible_prop = RNA_struct_find_property(&scene_ptr,
                                                               "mixie_sam3d_box_visible");
      if (box_visible_prop && RNA_property_boolean_get(&scene_ptr, box_visible_prop)) {
        PropertyRNA *min_x_prop = RNA_struct_find_property(&scene_ptr, "mixie_sam3d_box_min_x");
        PropertyRNA *min_y_prop = RNA_struct_find_property(&scene_ptr, "mixie_sam3d_box_min_y");
        PropertyRNA *max_x_prop = RNA_struct_find_property(&scene_ptr, "mixie_sam3d_box_max_x");
        PropertyRNA *max_y_prop = RNA_struct_find_property(&scene_ptr, "mixie_sam3d_box_max_y");

        if (min_x_prop && min_y_prop && max_x_prop && max_y_prop) {
          float min_x = RNA_property_float_get(&scene_ptr, min_x_prop);
          float min_y = RNA_property_float_get(&scene_ptr, min_y_prop);
          float max_x = RNA_property_float_get(&scene_ptr, max_x_prop);
          float max_y = RNA_property_float_get(&scene_ptr, max_y_prop);

          /* Convert normalized coordinates back to screen space */
          float box_x1 = display_x + (min_x * display_width);
          float box_y1 = display_y + (min_y * display_height);
          float box_x2 = display_x + (max_x * display_width);
          float box_y2 = display_y + (max_y * display_height);

          GPU_blend(GPU_BLEND_ALPHA);

          GPUVertFormat *format = immVertexFormat();
          uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
          immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);

          /* Draw fill (Blue 20%) */
          immUniformColor4f(0.2f, 0.4f, 1.0f, 0.2f);
          immRectf(pos, box_x1, box_y1, box_x2, box_y2);

          /* Draw border (Blue 100%) */
          immUniformColor4f(0.2f, 0.4f, 1.0f, 1.0f);

          /* Manually draw 4 lines for border */
          immBegin(GPU_PRIM_LINE_LOOP, 4);
          immVertex2f(pos, box_x1, box_y1);
          immVertex2f(pos, box_x2, box_y1);
          immVertex2f(pos, box_x2, box_y2);
          immVertex2f(pos, box_x1, box_y2);
          immEnd();

          immUnbindProgram();
          GPU_blend(GPU_BLEND_NONE);
        }
      }

      BKE_image_release_ibuf(image, ibuf, lock);
    }
  }
  else {
    /* Draw placeholder if no image selected */
    GPUVertFormat *format = immVertexFormat();
    uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    immUniformColor4f(0.2f, 0.2f, 0.2f, 1.0f);
    immRectf(pos, 0.0f, PREVIEW_HEIGHT, region_width, region_height);
    immUnbindProgram();
  }

  /* ===== DRAW SEPARATOR LINE ===== */
  {
    GPUVertFormat *format = immVertexFormat();
    uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    immUniformColor4f(0.4f, 0.4f, 0.4f, 1.0f);
    immRectf(pos, 0.0f, float(PREVIEW_HEIGHT - 2), region_width, float(PREVIEW_HEIGHT));
    immUnbindProgram();
  }

  /* ===== DRAW PREVIEW AREA (BOTTOM) ===== */
  {
    /* Draw preview background */
    GPUVertFormat *format = immVertexFormat();
    uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    immUniformColor4f(0.15f, 0.15f, 0.15f, 1.0f);
    immRectf(pos, 0.0f, 0.0f, region_width, float(PREVIEW_HEIGHT));
    immUnbindProgram();

    /* Get segmented history */
    PropertyRNA *history_prop = RNA_struct_find_property(&scene_ptr, "mixie_segmented_history");

    if (history_prop) {
      const int history_count = RNA_property_collection_length(&scene_ptr, history_prop);

      if (history_count > 0) {
        /* Draw thumbnails from left to right */
        int current_x = PREVIEW_PADDING;
        int current_y = PREVIEW_PADDING;

        RNA_PROP_BEGIN (&scene_ptr, itemptr, history_prop) {
          /* Get image from history item */
          PropertyRNA *history_image_prop = RNA_struct_find_property(&itemptr, "image");
          if (!history_image_prop) {
            continue;
          }

          PointerRNA history_image_ptr = RNA_property_pointer_get(&itemptr, history_image_prop);
          Image *history_image = (Image *)history_image_ptr.data;

          if (!history_image) {
            continue;
          }

          /* Calculate thumbnail dimensions maintaining aspect ratio */
          void *lock;
          ImBuf *ibuf = BKE_image_acquire_ibuf(history_image, nullptr, &lock);
          int thumb_width = PREVIEW_THUMB_HEIGHT; /* Default to square */

          if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
            /* Maintain aspect ratio, fit to height */
            float aspect_ratio = float(ibuf->x) / float(ibuf->y);
            thumb_width = int(PREVIEW_THUMB_HEIGHT * aspect_ratio);
          }
          BKE_image_release_ibuf(history_image, ibuf, lock);

          /* Check if we have space for this thumbnail */
          if (current_x + thumb_width > region_width - PREVIEW_PADDING) {
            break; /* No more space */
          }

          /* Draw the thumbnail (not selected for now - can add selection later) */
          mixie_draw_sam3d_preview_thumbnail(
              history_image, current_x, current_y, thumb_width, PREVIEW_THUMB_HEIGHT, false);

          /* Move to next position */
          current_x += thumb_width + PREVIEW_GAP;
        }
        RNA_PROP_END;
      }
      else {
        /* Draw "No segmented images yet" message */
        const int font_id = 0;
        BLF_size(font_id, 14.0f);
        BLF_color4f(font_id, 0.5f, 0.5f, 0.5f, 1.0f);
        BLF_position(font_id, PREVIEW_PADDING, PREVIEW_HEIGHT / 2.0f, 0);
        BLF_draw(font_id,
                 "No segmented images yet. Draw a box and segment to see results here.",
                 75);
      }
    }
  }
}

/** \} */

}  // namespace blender::ed::mixie
