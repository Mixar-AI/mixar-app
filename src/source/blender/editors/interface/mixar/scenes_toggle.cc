/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "scenes_toggle.hh"
#include "../interface_intern.hh"
#include "../interface_mixar_card_paint.hh"
#include "BLI_string.h"
#include "DNA_screen_types.h"
#include "UI_mixar_motion.hh"
#include "UI_mixar_theme.hh"
#include "WM_types.hh"

#include <algorithm>

namespace blender::ui {

/** Rest width of the toggle: the icon capsule alone, from the button height.
 * Shared by the layout pass and the painter so the click rectangle and the
 * drawn capsule / label reveal can never disagree. */
static float collapsed_width(const float height)
{
  return height * 34.0f / 28.0f;
}

bool mixar_scenes_toggle_is_button(const Button &button)
{
  return button.mixar_style.component == MixarComponent::Toolbar && button.optype &&
         STREQ(button.optype->idname, "VIEW3D_OT_scenes_drawer_toggle");
}

void mixar_scenes_toggle_layout(ARegion *region, Block *block)
{
  if (!region || region->regiontype != RGN_TYPE_HEADER) {
    return;
  }
  float shift = 0.0f;
  bool left_lane = false;
  for (Button &button : block->buttons()) {
    if (mixar_scenes_toggle_is_button(button)) {
      mixar_button_motion_update(button, region);
      const float expanded = BLI_rctf_size_x(&button.rect);
      const float collapsed = std::min(expanded, collapsed_width(BLI_rctf_size_y(&button.rect)));
      shift = (expanded - collapsed) * (1.0f - mixar_button_motion(button).hover);
      button.rect.xmax -= shift;
      left_lane = true;
    }
    else if (left_lane) {
      if (button.type == ButtonType::SeprSpacer) {
        /* The left lane ends at its own flexible spacer (`layout.separator_spacer()`
         * in `view3d_header_filter.py`), which absorbs the contraction. Shading
         * and the right lane keep their fixed native positions. Keyed on the
         * layout itself, never on a neighbouring operator that may be absent
         * (deferred registration placeholders, a reordered toolbar). */
        break;
      }
      BLI_rctf_translate(&button.rect, -shift, 0.0f);
    }
  }
}

void mixar_scenes_toggle_draw(const Button &button, const rcti &bounds)
{
  const auto motion = mixar_button_motion(button);
  const float u = UI_SCALE_FAC;
  const float collapsed = collapsed_width(BLI_rcti_size_y(&bounds));
  rctf body;
  BLI_rctf_rcti_copy(&body, &bounds);
  const auto *ink = mixar_theme_color_ptr(MixarThemeSlot::ToolbarText);
  mixar_card_fill_round(&body, 9.0f * u, mixar_theme_color_ptr(MixarThemeSlot::Canvas));
  mixar_card_fill_round(&body, 9.0f * u, ink, motion.hover * 0.035f + motion.press * 0.04f);

  /* Three vector capsules stay sharp on every display. Their center never
   * moves while the button and its native click rectangle expand rightward. */
  const float center_x = body.xmin + std::min(collapsed, BLI_rctf_size_x(&body)) * 0.5f;
  const float center_y = BLI_rctf_cent_y(&body);
  for (int i = -1; i <= 1; i++) {
    const float y = center_y + i * 5.0f * u;
    rctf bar = {center_x - 7.5f * u, center_x + 7.5f * u, y - u, y + u};
    mixar_card_fill_round(&bar, u, ink);
  }
  if (motion.selected > 0.0f) {
    rctf mark = {center_x - 5.0f * u, center_x + 5.0f * u,
                 body.ymin + 2.0f * u, body.ymin + 3.5f * u};
    mixar_card_fill_round(&mark, u, mixar_theme_color_ptr(MixarThemeSlot::ToolbarPrimary),
                          motion.selected);
  }
  const float reveal = std::clamp((motion.hover - 0.15f) / 0.85f, 0.0f, 1.0f);
  if (reveal > 0.0f) {
    rcti text = bounds;
    text.xmin = int(body.xmin + collapsed + 6.0f * u * (1.0f - reveal));
    text.xmax -= int(7.0f * u);
    if (text.xmax > text.xmin) {
      uchar color[4] = {ink[0], ink[1], ink[2], uchar(ink[3] * reveal)};
      uiFontStyle font = mixar_card_font(0.95f, 0);
      mixar_card_draw_text(font, &text, button.str.c_str(), color, UI_STYLE_TEXT_LEFT);
    }
  }
}
}  // namespace blender::ui
