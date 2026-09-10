/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once
#include "BLI_sys_types.h"
#include "UI_mixar_types.hh"

namespace blender::ui::mixar_tokens {
/* [[maybe_unused]]: the full palette is defined up front as the single
 * source of truth; individual tokens land as each widget phase uses them. */
inline constexpr uchar MX_BG[4] = {20, 20, 20, 255};            /* #141414 raised/panel */
inline constexpr uchar MX_BG_SUNKEN[4] = {15, 15, 15, 255};     /* #0f0f0f sunken card    */
inline constexpr uchar MX_GRAY_800[4] = {31, 31, 31, 255};      /* #1f1f1f input/select   */
inline constexpr uchar MX_GRAY_700[4] = {42, 42, 42, 255};      /* #2a2a2a toggle-off     */
inline constexpr uchar MX_BORDER[4] = {38, 38, 38, 255};        /* #262626        */
inline constexpr uchar MX_BORDER_STRONG[4] = {46, 46, 46, 255}; /* #2e2e2e */
inline constexpr uchar MX_ACCENT[4] = {0, 192, 199, 255};       /* #00C0C7 brand accent   */
inline constexpr uchar MX_TOGGLE_ON[4] = {0, 192, 199, 255};    /* #00C0C7 toggle ON      */
inline constexpr uchar MX_WARNING[4] = {224, 160, 48, 255};     /* amber semantic */
inline constexpr uchar MX_DANGER[4] = {224, 72, 72, 255};       /* red semantic   */
inline constexpr uchar MX_INK[4] = {10, 10, 10, 255};           /* near-black on gradient  */
inline constexpr uchar MX_FG_1[4] = {230, 230, 230, 255};
inline constexpr uchar MX_FG_2[4] = {200, 200, 200, 255}; /* #c8c8c8 label */
inline constexpr uchar MX_FG_3[4] = {140, 140, 140, 255}; /* #8c8c8c section label */
inline constexpr uchar MX_FG_4[4] = {90, 90, 90, 255};    /* #5a5a5a muted glyph */

/* --mx-gradient: the ONE gradient in the app (Generate button), 90deg
 * lime -> green -> teal -> cyan. Stops are evenly spaced. */
inline constexpr uchar MX_GRADIENT[4][4] = {
    {106, 163, 18, 255}, /* lime  #6aa312 (dimmed ~80%) */
    {27, 158, 75, 255},  /* green #1b9e4b (dimmed ~80%) */
    {34, 150, 122, 255}, /* teal  #22967a (dimmed ~80%) */
    {5, 146, 170, 255},  /* cyan  #0592aa (dimmed ~80%) */
};

/* Corner radii in px @ 1x DPI (scaled by UI_SCALE_FAC at draw time). */
inline constexpr float MX_R_SM = 4.0f;     /* --mx-r-sm: inputs / selects */
inline constexpr float MX_R_MD = 8.0f;     /* --mx-r-md: grouped cards    */
inline constexpr float MX_R_PILL = 999.0f; /* fully rounded; clamped to h/2 */

struct Palette {
  float canvas[4], panel[4], input[4], control[4], selected[4];
  float text[4], strong[4], secondary[4], border[4], focus[4];
  float primary[4], danger[4], warning[4], action[4];
};
inline constexpr Palette zen = {{0.071f, 0.071f, 0.071f, 1},
                                {0.176f, 0.176f, 0.176f, 1},
                                {0.071f, 0.071f, 0.071f, 1},
                                {0.192f, 0.192f, 0.192f, 1},
                                {0.282f, 0.282f, 0.282f, 1},
                                {0.886f, 0.886f, 0.886f, 1},
                                {1, 1, 1, 1},
                                {0.459f, 0.459f, 0.459f, 1},
                                {0.255f, 0.255f, 0.255f, 1},
                                {0, 1, 0.549f, 1},
                                {0.102f, 0.251f, 0.149f, 1},
                                {0.804f, 0.361f, 0.361f, 1},
                                {0.898f, 0.694f, 0.298f, 1},
                                {0.114f, 0.114f, 0.114f, 1}};
/** Island design units; hosts resolve them exactly once. */
inline constexpr float control_height = 44.0f;
inline constexpr float radius = 14.0f;
inline constexpr float font = 18.0f;
inline constexpr float caption_font = 15.0f;
inline constexpr float prompt_font = 24.0f;
inline constexpr float padding = 20.0f;
inline constexpr float gap = 12.0f;
inline constexpr float icon = 18.0f;
inline constexpr float icon_gap = 8.0f;
}  // namespace blender::ui::mixar_tokens
