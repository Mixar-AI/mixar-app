/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar account card — action buttons.
 *
 * Split from the other element painters because composing the glyph and
 * label as one group, across four visual variants, is most of the card's
 * drawing code.
 */

#include <algorithm>

#include "BLI_rect.h"

#include "BLF_api.hh"

#include "DNA_userdef_types.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_icons.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_palette.hh"
#include "interface_mixar_profile_card.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

/* Buttons — background, glyph and label are all drawn here             */

/**
 * One card action button.
 *
 * The contents are composed here rather than handed to the generic
 * text/icon path because that path pins the icon to the far left slot
 * and centres the label independently, which opens a dead gap across the
 * middle of a wide button. Owning both lets the glyph and label travel
 * as one group.
 */
void UI_mixar_card_button_draw(Button *but,
                               rcti *rect,
                               const MixarCardElement element,
                               const bool is_hover,
                               const bool is_active)
{
  rctf box;
  mixar_card_rect_to_rctf(rect, &box);

  /* Inset so adjacent buttons in an aligned row read as separate cards
   * rather than one merged block. */
  const float inset = MIXAR_CARD_BUTTON_INSET * UI_SCALE_FAC;
  box.xmin += inset;
  box.xmax -= inset;
  box.ymin += inset;
  box.ymax -= inset;

  const float rad = MX_R_MD * UI_SCALE_FAC;

  GPU_blend(GPU_BLEND_ALPHA);

  const uchar *text_col = MX_FG_1;
  const uchar *icon_col = MX_FG_2;

  switch (element) {
    case MixarCardElement::AccentButton: {
      /* Reads as a filled button, not an outline: it is the one place on
       * the card asking for a decision, so it carries real weight. */
      mixar_card_fill_round(&box, rad, MX_ACCENT, is_hover ? 0.32f : 0.22f);
      mixar_card_outline_round(&box, rad, MX_ACCENT, is_hover ? 0.85f : 0.55f);
      text_col = MX_ACCENT;
      icon_col = MX_ACCENT;
      break;
    }
    case MixarCardElement::DangerButton: {
      /* Reporting a bug is not an error state. Tinted enough to be
       * legible as the destructive-ish corner of the grid, and no more —
       * at full danger weight it was the loudest thing on the card and
       * pulled the eye off Buy Credits. */
      mixar_card_fill_round(&box, rad, is_hover ? MX_GRAY_700 : MX_GRAY_800);
      mixar_card_fill_round(&box, rad, MX_DANGER, is_hover ? 0.18f : 0.12f);
      mixar_card_outline_round(&box, rad, MX_DANGER, is_hover ? 0.55f : 0.35f);
      icon_col = MX_DANGER;
      break;
    }
    case MixarCardElement::GhostButton: {
      /* Borderless until touched, so the logout strip stays quiet. */
      if (is_hover) {
        mixar_card_fill_round(&box, rad, MX_GRAY_800);
      }
      text_col = MX_FG_2;
      icon_col = MX_FG_4;
      break;
    }
    case MixarCardElement::CardButton:
    default: {
      mixar_card_fill_round(&box, rad, is_hover ? MX_GRAY_700 : MX_GRAY_800);
      mixar_card_outline_round(&box, rad, MX_BORDER_STRONG, 1.0f);
      break;
    }
  }

  if (is_active) {
    /* Blender has no press transform; approximate the dip with a wash. */
    const float dim[4] = {0.0f, 0.0f, 0.0f, 0.15f};
    draw_roundbox_corner_set(CNR_ALL);
    draw_roundbox_4fv(&box, true, rad, dim);
  }

  /* --- Contents --------------------------------------------------------- */
  const MixarCardIcon icon = MixarCardIcon(std::max(0, int(but->hardmax)));
  const uiFontStyle fs = mixar_card_font(1.0f, 0);
  fontstyle_set(&fs);

  const float label_w = but->drawstr.empty() ?
                            0.0f :
                            BLF_width(fs.uifont_id, but->drawstr.c_str(), but->drawstr.size());
  const float icon_size = MIXAR_CARD_BUTTON_ICON * UI_SCALE_FAC;
  const float icon_gap = MIXAR_CARD_BUTTON_ICON_GAP * UI_SCALE_FAC;
  const bool has_icon = icon != MixarCardIcon::None;

  /* The builder sizes each button around exactly this chrome
   * (#mixar_card_button_chrome), so the nominal padding normally fits.
   * When it cannot — a row whose width the layout capped, a translation
   * longer than the measurement, a tiny UI scale — spend the padding
   * down before the glyphs, because #fontstyle_draw clips without an
   * ellipsis and a silently shortened label reads as a wrong word. */
  const float box_w = box.xmax - box.xmin;
  const float content_w = label_w + (has_icon ? icon_size + icon_gap : 0.0f);
  float pad = MIXAR_CARD_BUTTON_PAD * UI_SCALE_FAC;
  if (content_w + pad * 2.0f > box_w) {
    pad = std::clamp((box_w - content_w) * 0.5f, 4.0f * UI_SCALE_FAC, pad);
  }

  const float cy = (box.ymin + box.ymax) * 0.5f;
  float x = box.xmin + pad;

  if (!has_icon || element == MixarCardElement::GhostButton) {
    /* The compact chip and the logout strip read as a single word, so
     * their content is centred rather than run along the left edge. */
    x = (box.xmin + box.xmax - content_w) * 0.5f;
  }

  if (has_icon) {
    UI_mixar_card_icon_draw(icon, x + icon_size * 0.5f, cy, icon_size, icon_col);
    x += icon_size + icon_gap;
  }

  GPU_blend(GPU_BLEND_NONE);

  if (!but->drawstr.empty()) {
    rcti text_rect;
    BLI_rcti_init(&text_rect,
                  int(x),
                  int(box.xmax - pad),
                  int(box.ymin),
                  int(box.ymax));
    mixar_card_draw_text(fs, &text_rect, but->drawstr.c_str(), text_col, UI_STYLE_TEXT_LEFT);
  }
}
}  // namespace blender::ui
