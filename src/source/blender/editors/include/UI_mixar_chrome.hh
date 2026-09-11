/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "UI_mixar_types.hh"

namespace blender::ui::mixar_chrome {

/** Chrome hosts use Compact density. Control sizes stay on the UI.svg and
 * `card_row_*` recipes: Compact's 32-unit height does not match the 28px
 * header track or the 1.9 profile grid that keeps `MX_R_MD` a rounded
 * rect. Island tokens remain Default. */
inline constexpr MixarDensity density = MixarDensity::Compact;

/** Widget-font scales for topbar, viewport shading pills and Cinema popup
 * rows. Chrome uses Blender `UI_SCALE_FAC`, not the island artboard unit. */
inline constexpr float label_scale = 0.95f;
inline constexpr float caption_scale = 0.90f;

/** Thumb inset inside the Zen/Engine track, px @1x. */
inline constexpr float slider_thumb_inset = 2.0f;
/** Inactive Solid/Rendered pill opacity. */
inline constexpr float viewport_pill_dim = 0.49f;

inline constexpr unsigned char slider_track[4] = {0x1D, 0x1D, 0x1D, 255};
inline constexpr unsigned char slider_thumb[4] = {0x39, 0x39, 0x39, 255};
inline constexpr unsigned char slider_thumb_hover[4] = {0x46, 0x46, 0x46, 255};
inline constexpr unsigned char slider_label[4] = {255, 255, 255, 255};

inline constexpr unsigned char cinema_pill_fill[4] = {0x0E, 0x0E, 0x0E, 255};
inline constexpr unsigned char cinema_pill_border[4] = {0x3F, 0x3F, 0x3F, 255};
inline constexpr unsigned char cinema_pill_fill_on_a[4] = {0x20, 0x58, 0x36, 255};
inline constexpr unsigned char cinema_pill_fill_on_b[4] = {0x3A, 0x84, 0x57, 255};
inline constexpr unsigned char cinema_pill_border_on[4] = {0x57, 0xB0, 0x7C, 255};
inline constexpr unsigned char cinema_pill_label_a[4] = {0x50, 0x50, 0x50, 255};
inline constexpr unsigned char cinema_pill_label_b[4] = {255, 255, 255, 255};

inline constexpr unsigned char viewport_pill_fill[4] = {0x05, 0x05, 0x05, 255};
inline constexpr unsigned char viewport_pill_border[4] = {0x67, 0x67, 0x67, 255};
inline constexpr unsigned char viewport_pill_label[4] = {0x73, 0x73, 0x73, 255};
inline constexpr unsigned char viewport_pill_label_on[4] = {0xDE, 0xDE, 0xDE, 255};

inline constexpr unsigned char profile_fill[4] = {0x1B, 0x1B, 0x1B, 255};
inline constexpr unsigned char profile_label[4] = {0xEC, 0xEC, 0xEC, 255};
inline constexpr unsigned char profile_avatar[4] = {0x3C, 0x3C, 0x3C, 255};
inline constexpr unsigned char profile_glyph[4] = {0xD2, 0xD2, 0xD2, 255};

/** Profile-card and shared-dialog action recipes. Fills still use the
 * shared `MX_*` palette; these are the existing alpha/scale compositions.
 * Inset/pad/icon geometry stays in `interface_mixar_card_paint.hh`
 * because the builder must measure the same numbers the painter spends. */
inline constexpr float card_action_label_scale = 1.0f;
inline constexpr float card_accent_fill = 0.22f;
inline constexpr float card_accent_fill_hover = 0.32f;
inline constexpr float card_accent_outline = 0.55f;
inline constexpr float card_accent_outline_hover = 0.85f;
inline constexpr float card_danger_fill = 0.12f;
inline constexpr float card_danger_fill_hover = 0.18f;
inline constexpr float card_danger_outline = 0.35f;
inline constexpr float card_danger_outline_hover = 0.55f;
inline constexpr float card_outline = 1.0f;
inline constexpr float card_press_wash = 0.15f;

/** Profile-card and shared-dialog heading / plan-chip / divider / field /
 * footer / grid-action recipes. Pill pad/height stay in
 * `interface_mixar_card_paint.hh` so the builder measures the same
 * numbers the painter spends. Row scales are UI-unit `scale_y` values
 * shared with Python dialogs. Footer actions use `card_row_cta`; the
 * profile 2x2 uses `card_row_action`. */
inline constexpr float card_heading_scale = 1.45f;
inline constexpr int card_heading_weight = 700;
inline constexpr float card_pill_radius = 0.35f;
inline constexpr float card_row_heading = 1.6f;
inline constexpr float card_row_divider = 0.6f;
inline constexpr float card_row_field = 1.45f;
inline constexpr float card_row_cta = 1.7f;
inline constexpr float card_row_action = 1.9f;

/** Cinema popup-row recipe. Values mirror `CINEMA_ROW_RADIUS` and
 * `CINEMA_COL_*` in `view3d_director_cinema.hh`; the popup kit cannot
 * include that header. Director gate/timeline/map stay feature-owned. */
inline constexpr float cinema_row_radius = 14.0f;
inline constexpr float cinema_row_text_pad = 12.0f;
inline constexpr float cinema_row_text_pad_min = 4.0f;
inline constexpr float cinema_row_segment_min_w = 28.0f;
inline constexpr float cinema_row_inset = 1.0f;
inline constexpr float cinema_row_icon_gap = 6.0f;

inline constexpr unsigned char cinema_row_top[4] = {0x58, 0x58, 0x58, 255};
inline constexpr unsigned char cinema_row_bottom[4] = {0x24, 0x24, 0x24, 255};
inline constexpr unsigned char cinema_row_hover[4] = {0x2E, 0x2E, 0x2E, 255};
inline constexpr unsigned char cinema_row_track[4] = {0x26, 0x26, 0x26, 255};
inline constexpr unsigned char cinema_row_text_on[4] = {255, 255, 255, 255};
inline constexpr unsigned char cinema_row_text_off[4] = {0xB4, 0xB4, 0xB4, 255};
inline constexpr unsigned char cinema_row_text_disabled[4] = {0x63, 0x63, 0x63, 255};
inline constexpr unsigned char cinema_row_caption[4] = {102, 102, 102, 217};
inline constexpr unsigned char cinema_row_slider_on[4] = {42, 121, 73, 255};

}  // namespace blender::ui::mixar_chrome
