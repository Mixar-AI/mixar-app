/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup sptexturesets
 *
 * Texture Sets Space - Main region drawing (placeholder).
 */

#include "BKE_context.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "GPU_immediate.hh"

#include "BLF_api.hh"

#include "texture_sets_intern.hh"

namespace blender::ed::texture_sets {

void texture_sets_draw_main_region(const bContext * /*C*/, ARegion *region)
{
  /* Clear background with theme color */
  ui::theme::frame_buffer_clear(TH_BACK);

  /* Draw placeholder text in center */
  const int center_x = region->winx / 2;
  const int center_y = region->winy / 2;

  /* Use default font */
  const int font_id = BLF_default();
  BLF_size(font_id, 16.0f);

  /* Set text color */
  float text_color[4];
  ui::theme::get_color_4fv(TH_TEXT, text_color);
  BLF_color4fv(font_id, text_color);

  /* Draw centered placeholder text */
  const char *placeholder_text = "Texture Sets Space";
  float text_width = BLF_width(font_id, placeholder_text, strlen(placeholder_text));

  BLF_position(font_id, center_x - text_width / 2, center_y, 0.0f);
  BLF_draw(font_id, placeholder_text, strlen(placeholder_text));

  /* Draw subtitle */
  const char *subtitle = "Use the sidebar panels to manage texture sets";
  BLF_size(font_id, 12.0f);
  text_width = BLF_width(font_id, subtitle, strlen(subtitle));

  float subtitle_color[4];
  ui::theme::get_color_4fv(TH_TEXT_HI, subtitle_color);
  subtitle_color[3] = 0.6f;
  BLF_color4fv(font_id, subtitle_color);

  BLF_position(font_id, center_x - text_width / 2, center_y - 30, 0.0f);
  BLF_draw(font_id, subtitle, strlen(subtitle));
}

}  // namespace blender::ed::texture_sets
