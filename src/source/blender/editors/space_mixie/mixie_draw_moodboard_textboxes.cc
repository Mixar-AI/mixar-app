/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard textbox drawing for Mixie space
 */

#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Moodboard Text Boxes Drawing
 * \{ */

void mixie_draw_moodboard_textboxes(const bContext *C, View2D *v2d)
{
  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_textboxes");

  if (!prop) {
    return;
  }

  /* Pre-allocated buffer for text content to avoid malloc/free per textbox per frame.
   * 4KB should be sufficient for moodboard text. */
  char text_buffer[4096];

  /* Draw each text box at its position */
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, prop, &iter);

  /* Initialize property cache from first item */
  if (iter.valid) {
    init_textbox_property_cache(&iter.ptr);
  }

  while (iter.valid) {
    PointerRNA itemptr = iter.ptr;

    /* Use cached property pointers for faster access */
    if (g_tb_props.text && g_tb_props.position_x && g_tb_props.position_y && g_tb_props.width &&
        g_tb_props.height)
    {
      float pos_x = RNA_property_float_get(&itemptr, g_tb_props.position_x);
      float pos_y = RNA_property_float_get(&itemptr, g_tb_props.position_y);
      float width = RNA_property_float_get(&itemptr, g_tb_props.width);
      float height = RNA_property_float_get(&itemptr, g_tb_props.height);

      /* Early view frustum culling for textboxes */
      if (!is_rect_in_view(v2d, pos_x, pos_y, width, height)) {
        RNA_property_collection_next(&iter);
        continue;
      }

      /* Use stack buffer instead of allocating every frame */
      RNA_property_string_get(&itemptr, g_tb_props.text, text_buffer);

      int font_size = g_tb_props.font_size ? RNA_property_int_get(&itemptr, g_tb_props.font_size) :
                                             48;
      float rotation = g_tb_props.rotation ?
                           RNA_property_float_get(&itemptr, g_tb_props.rotation) :
                           0.0f;

      /* Get colors */
      float text_color[4] = {1.0f, 1.0f, 1.0f, 1.0f};
      float bg_color[4] = {0.0f, 0.0f, 0.0f, 0.5f};

      if (g_tb_props.text_color) {
        RNA_property_float_get_array(&itemptr, g_tb_props.text_color, text_color);
      }
      if (g_tb_props.background_color) {
        RNA_property_float_get_array(&itemptr, g_tb_props.background_color, bg_color);
      }

      /* Get alignment */
      int align = 0; /* LEFT */
      if (g_tb_props.align) {
        align = RNA_property_enum_get(&itemptr, g_tb_props.align);
      }

      GPU_matrix_push();

      /* Apply rotation around center */
      const float center_x = pos_x + width / 2.0f;
      const float center_y = pos_y + height / 2.0f;

      if (rotation != 0.0f) {
        GPU_matrix_translate_2f(center_x, center_y);
        GPU_matrix_rotate_2d(rotation);
        GPU_matrix_translate_2f(-center_x, -center_y);
      }

      /* Draw background rectangle */
      if (bg_color[3] > 0.0f) {
        GPUVertFormat *format = immVertexFormat();
        uint pos = GPU_vertformat_attr_add(
            format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

        immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
        immUniformColor4fv(bg_color);

        GPU_blend(GPU_BLEND_ALPHA);

        immBegin(GPU_PRIM_TRI_FAN, 4);
        immVertex2f(pos, pos_x, pos_y);
        immVertex2f(pos, pos_x + width, pos_y);
        immVertex2f(pos, pos_x + width, pos_y + height);
        immVertex2f(pos, pos_x, pos_y + height);
        immEnd();

        immUnbindProgram();
        GPU_blend(GPU_BLEND_NONE);
      }

      /* Draw text */
      size_t text_len = strlen(text_buffer);
      if (text_len > 0) {
        const int font_id = BLF_default();

        /* Enable bold/italic styling */
        bool is_bold = g_tb_props.bold ? RNA_property_boolean_get(&itemptr, g_tb_props.bold) :
                                         false;
        bool is_italic = g_tb_props.italic ?
                             RNA_property_boolean_get(&itemptr, g_tb_props.italic) :
                             false;

        if (is_bold) {
          BLF_enable(font_id, BLF_BOLD);
        }
        if (is_italic) {
          BLF_enable(font_id, BLF_ITALIC);
        }

        BLF_enable(font_id, BLF_WORD_WRAP);
        BLF_wordwrap(font_id, width - 20.0f); /* 10px padding on each side */
        BLF_size(font_id, font_size);
        BLF_color4fv(font_id, text_color);

        /* Calculate text position based on alignment */
        float text_x = pos_x + 10.0f; /* 10px left padding */
        float text_y = pos_y + height - 10.0f - font_size; /* Top aligned with padding */

        /* Get text dimensions for alignment */
        if (align != 0) { /* Not LEFT */
          rcti bbox;
          BLF_boundbox(font_id, text_buffer, text_len, &bbox);
          float text_width_calc = BLI_rcti_size_x(&bbox);

          if (align == 1) { /* CENTER */
            text_x = pos_x + (width - text_width_calc) / 2.0f;
          }
          else if (align == 2) { /* RIGHT */
            text_x = pos_x + width - text_width_calc - 10.0f; /* 10px right padding */
          }
        }

        BLF_position(font_id, text_x, text_y, 0.0f);
        BLF_draw(font_id, text_buffer, text_len);

        BLF_disable(font_id, BLF_WORD_WRAP);
        if (is_bold) {
          BLF_disable(font_id, BLF_BOLD);
        }
        if (is_italic) {
          BLF_disable(font_id, BLF_ITALIC);
        }
      }

      /* Draw selection overlay if selected */
      bool is_selected = g_tb_props.selected ?
                             RNA_property_boolean_get(&itemptr, g_tb_props.selected) :
                             false;

      if (is_selected) {
        mixie_draw_moodboard_selection_overlay(v2d, pos_x, pos_y, width, height);
      }

      GPU_matrix_pop();
    }

    RNA_property_collection_next(&iter);
  }

  RNA_property_collection_end(&iter);
}

/** \} */

}  // namespace blender::ed::mixie
