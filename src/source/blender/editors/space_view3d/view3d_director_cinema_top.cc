/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the top strip — branding chip, keyboard hints, and the
 * phone hand-off button.
 *
 * Painting only; see `view3d_director_cinema_paint.cc` for the primitives.
 */

#include "BLI_rect.h"

#include "DNA_screen_types.h"

#include "UI_interface.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"

/* -------------------------------------------------------------------- */
/** \name Top strip
 * \{ */

void cinema_draw_top_strip(uiBlock *block,
                           const ARegion *region,
                           const DirectorViewState &state)
{
  const float u = cinema_unit();

  /* Branding chip. */
  const rctf chip = cinema_design_rect(region, cinema_margin(region), 152.0f, CINEMA_PANEL_W, CINEMA_CHIP_H);
  const float brand_top[4] = CINEMA_COL_BRAND_TOP;
  const float brand_bottom[4] = CINEMA_COL_BRAND_BOTTOM;
  cinema_panel(chip, 18.0f * u, brand_top, brand_bottom);
  const float title[4] = {0.93f, 0.93f, 0.93f, 1.0f};
  const float version[4] = CINEMA_COL_LABEL;
  cinema_text_left("Cinema Mode",
                   chip.xmin + 22.0f * u,
                   BLI_rctf_cent_y(&chip),
                   CINEMA_FONT_TITLE * u,
                   title);
  cinema_text_right("V1", chip.xmax - 20.0f * u, BLI_rctf_cent_y(&chip), 13.0f * u, version);

  /* Shortcut hints. The keys are what the Director keymap actually binds:
   * capture is F (`director/ui/keymap.py`), so the hint says F — a design
   * label of "I" would be a lie about a live binding. */
  struct Hint {
    float x;
    const char *keys[4];
    int key_count;
    const char *label;
    bool stacked; /* WASD draws W above ASD. */
  };
  const Hint hints[] = {
      {332.0f, {"O"}, 1, "Navigate", false},
      {450.0f, {"F"}, 1, "Insert keyframe", false},
      {616.0f, {"W", "A", "S", "D"}, 4, "Move around", true},
      {831.0f, {"Q", "E"}, 2, "Z-axis", false},
  };
  const float hint_col[4] = CINEMA_COL_LABEL;
  for (const Hint &hint : hints) {
    /* A hint clipped in half reads as a rendering bug; drop the whole group. */
    const float need = hint.x + float(hint.stacked ? 3 : hint.key_count) *
                                    (CINEMA_KEYCAP_W + 2.0f) +
                       8.0f + cinema_text_width(hint.label, CINEMA_FONT_LABEL * u) / u;
    if (need * u > float(region->winx)) {
      continue;
    }
    float x = hint.x * u;
    const float row_y = cinema_design_rect(region, 0.0f, 168.0f, 0.0f, CINEMA_KEYCAP_H).ymin;
    if (hint.stacked) {
      /* W sits above the middle of A S D, as in the design. */
      cinema_keycap(x + (CINEMA_KEYCAP_W + 2.0f) * u, cinema_design_rect(region, 0.0f, 145.0f, 0.0f, CINEMA_KEYCAP_H).ymin, "W");
      for (int index = 1; index < hint.key_count; index++) {
        cinema_keycap(x, row_y, hint.keys[index]);
        x += (CINEMA_KEYCAP_W + 2.0f) * u;
      }
    }
    else {
      for (int index = 0; index < hint.key_count; index++) {
        cinema_keycap(x, row_y, hint.keys[index]);
        x += (CINEMA_KEYCAP_W + 2.0f) * u;
      }
    }
    cinema_text_left(hint.label,
                     x + 8.0f * u,
                     row_y + CINEMA_KEYCAP_H * u * 0.5f,
                     CINEMA_FONT_LABEL * u,
                     hint_col);
  }

  /* Phone hand-off. Painted per the design but INERT: nothing on the backend
   * (checked `origin/develop`) drives a camera from a phone, and a button
   * that silently does nothing is worse than one that says so. */
  const rctf phone = cinema_design_rect(region, 1174.0f, 159.0f, CINEMA_PHONE_W, CINEMA_PHONE_H);
  if (phone.xmax < float(region->winx)) {
    const float phone_bg[4] = CINEMA_COL_PHONE;
    const float phone_text[4] = {0.957f, 0.957f, 0.957f, 0.55f};
    cinema_fill(phone, 18.0f * u, phone_bg);
    cinema_text_center("Drive camera from your phone",
                       BLI_rctf_cent_x(&phone),
                       BLI_rctf_cent_y(&phone),
                       CINEMA_FONT_VALUE * u,
                       phone_text);
  }
  UNUSED_VARS(state);
}

/** \} */

