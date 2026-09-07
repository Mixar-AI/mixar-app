/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Cinema Mode popup rows. The Director dropdown popups (aspect, lens,
 * output, interpolation, moves, shots) are native block popups built from
 * plain operator buttons; tagged as #MixarCardElement::CinemaRow they paint
 * as the surface's own row class — the graded chip for the live choice,
 * plain dim text for the rest — so a list looks like the value block it
 * opened from and like the Template Style / My Cameras lists beside it.
 *
 * The tokens MIRROR `view3d_director_cinema.hh` (CINEMA_ROW_RADIUS,
 * CINEMA_COL_ROW_TOP/BOTTOM, CINEMA_COL_VALUE/DIM); a pin test keeps them in
 * step, since this translation unit cannot reach into space_view3d.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_profile_card.hh"
#include "interface_mixar_section.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace {

/* Design px @1x — see view3d_director_cinema.hh. */
constexpr float ROW_RADIUS = 14.0f;
constexpr float TEXT_PAD = 12.0f;

const uchar ROW_TOP[4] = {0x58, 0x58, 0x58, 255};    /* CINEMA_COL_ROW_TOP */
const uchar ROW_BOTTOM[4] = {0x24, 0x24, 0x24, 255}; /* CINEMA_COL_ROW_BOTTOM */
const uchar HOVER[4] = {0x2E, 0x2E, 0x2E, 255};
const uchar TEXT_ON[4] = {255, 255, 255, 255};       /* CINEMA_COL_VALUE */
const uchar TEXT_OFF[4] = {0xB4, 0xB4, 0xB4, 255};   /* readable on the popup back */
const uchar TEXT_DISABLED[4] = {0x63, 0x63, 0x63, 255}; /* CINEMA_COL_DIM */

}  // namespace

void UI_mixar_cinema_row_tag(Button *but, const MixarCinemaRowKind kind)
{
  if (but == nullptr) {
    return;
  }
  UI_BUT2_MIXAR_CARD_SET(but);
  but->hardmin = float(int(MixarCardElement::CinemaRow));
  /* A Row (enum / flag toggle) button keeps ITS VALUE in `hardmax`; the
   * painter reads such a row's state from UI_SELECT instead, so the payload
   * must not touch it. Only free-standing rows carry the kind there. */
  if (but->type != ButtonType::Row) {
    but->hardmax = float(int(kind));
  }
}

void UI_mixar_cinema_row_draw(Button *but,
                              const rcti *rect,
                              const bool is_hover,
                              const bool is_active)
{
  /* A Row button (an enum / flag toggle) carries its state in UI_SELECT and
   * its value in `hardmax` (see the tag); for operator rows UI_SELECT is
   * only "held down" and `hardmax` is the kind. */
  const bool is_toggle = but->type == ButtonType::Row;
  const auto kind = is_toggle ? MixarCinemaRowKind::Option :
                                MixarCinemaRowKind(int(but->hardmax + 0.5f));
  const bool lit = kind == MixarCinemaRowKind::Active ||
                   (is_toggle && (but->flag & UI_SELECT) != 0);
  const bool disabled = (but->flag & BUT_DISABLED) != 0;
  const bool pressed = is_active || (!is_toggle && (but->flag & UI_SELECT) != 0);

  rctf row;
  mixar_card_rect_to_rctf(rect, &row);
  const float inset = 1.0f * UI_SCALE_FAC;
  BLI_rctf_pad(&row, -inset, -inset);
  const float rad = std::min(ROW_RADIUS * UI_SCALE_FAC, BLI_rctf_size_y(&row) * 0.5f);

  GPU_blend(GPU_BLEND_ALPHA);
  if (lit) {
    float top[4], bottom[4];
    mixar_card_to_float(ROW_TOP, top);
    mixar_card_to_float(ROW_BOTTOM, bottom);
    draw_roundbox_corner_set(CNR_ALL);
    draw_roundbox_4fv_ex(&row, top, bottom, 1.0f, nullptr, 0.0f, rad);
  }
  else if ((is_hover || pressed) && !disabled) {
    mixar_card_fill_round(&row, rad, HOVER, pressed ? 1.0f : 0.9f);
  }

  const uchar *col = disabled ? TEXT_DISABLED :
                                (lit || kind == MixarCinemaRowKind::Action ? TEXT_ON : TEXT_OFF);
  rcti text = *rect;
  text.xmin += int(TEXT_PAD * UI_SCALE_FAC);
  text.xmax -= int(TEXT_PAD * UI_SCALE_FAC);
  const uiFontStyle fs = mixar_card_font(0.95f, 0);
  /* The FULL label: Blender clips `drawstr` for its own stock layout (icon
   * space plus padding it will never draw here), which turned "Beauty" into
   * "Be" in a three-up row. This painter lays the row out itself. */
  const char *label = but->str.empty() ? but->drawstr.c_str() : but->str.c_str();
  const float label_w = fontstyle_string_width(&fs, label);
  if (but->icon != ICON_NONE) {
    /* The stock 16px glyph, vertically centred, then the label after it —
     * unless the cell cannot hold both, when the label wins. */
    const float icon_size = ICON_DEFAULT_HEIGHT * UI_SCALE_FAC;
    const float icon_gap = 6.0f * UI_SCALE_FAC;
    if (icon_size + icon_gap + label_w <= float(BLI_rcti_size_x(&text))) {
      const float icon_y = float(rect->ymin) + (float(BLI_rcti_size_y(rect)) - icon_size) * 0.5f;
      icon_draw_alpha(float(text.xmin), icon_y, but->icon, disabled ? 0.4f : 0.9f);
      text.xmin += int(icon_size + icon_gap);
    }
  }
  mixar_card_draw_text(fs, &text, label, col, UI_STYLE_TEXT_LEFT);
}

}  // namespace blender::ui
