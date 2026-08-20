/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar design-system palette (--mx-* tokens).
 *
 * Shared by every `widget_mixar_*` draw function and by the profile card
 * so the whole app speaks one visual language (global design system).
 * Values are the exact hex tokens from the Mixar design spec — this
 * header is the single source of truth; never re-hardcode them per
 * widget.
 */

#pragma once

#include "BLI_sys_types.h"

/* [[maybe_unused]]: the full palette is defined up front as the single
 * source of truth; individual tokens land as each widget phase uses them. */
[[maybe_unused]] inline constexpr uchar MX_BG[4]            = {20, 20, 20, 255};   /* #141414 raised/panel   */
[[maybe_unused]] inline constexpr uchar MX_BG_SUNKEN[4]     = {15, 15, 15, 255};   /* #0f0f0f sunken card    */
[[maybe_unused]] inline constexpr uchar MX_GRAY_800[4]      = {31, 31, 31, 255};   /* #1f1f1f input/select   */
[[maybe_unused]] inline constexpr uchar MX_GRAY_700[4]      = {42, 42, 42, 255};   /* #2a2a2a toggle-off     */
[[maybe_unused]] inline constexpr uchar MX_BORDER[4]        = {38, 38, 38, 255};   /* #262626                */
[[maybe_unused]] inline constexpr uchar MX_BORDER_STRONG[4] = {46, 46, 46, 255};   /* #2e2e2e                */
[[maybe_unused]] inline constexpr uchar MX_ACCENT[4]        = {0, 192, 199, 255};  /* #00C0C7 brand accent   */
[[maybe_unused]] inline constexpr uchar MX_TOGGLE_ON[4]     = {0, 192, 199, 255};  /* #00C0C7 toggle ON      */
[[maybe_unused]] inline constexpr uchar MX_WARNING[4]       = {224, 160, 48, 255}; /* amber semantic         */
[[maybe_unused]] inline constexpr uchar MX_DANGER[4]        = {224, 72, 72, 255};  /* red semantic           */
[[maybe_unused]] inline constexpr uchar MX_INK[4]           = {10, 10, 10, 255};   /* near-black on gradient  */
[[maybe_unused]] inline constexpr uchar MX_FG_1[4]          = {230, 230, 230, 255};
[[maybe_unused]] inline constexpr uchar MX_FG_2[4]          = {200, 200, 200, 255}; /* #c8c8c8 label         */
[[maybe_unused]] inline constexpr uchar MX_FG_3[4]          = {140, 140, 140, 255}; /* #8c8c8c section label */
[[maybe_unused]] inline constexpr uchar MX_FG_4[4]          = {90, 90, 90, 255};   /* #5a5a5a muted glyph    */

/* --mx-gradient: the ONE gradient in the app (Generate button), 90deg
 * lime -> green -> teal -> cyan. Stops are evenly spaced. */
[[maybe_unused]] inline constexpr uchar MX_GRADIENT[4][4] = {
    {106, 163, 18, 255},  /* lime  #6aa312 (dimmed ~80%) */
    {27, 158, 75, 255},   /* green #1b9e4b (dimmed ~80%) */
    {34, 150, 122, 255},  /* teal  #22967a (dimmed ~80%) */
    {5, 146, 170, 255},   /* cyan  #0592aa (dimmed ~80%) */
};

/* Corner radii in px @ 1x DPI (scaled by UI_SCALE_FAC at draw time). */
[[maybe_unused]] inline constexpr float MX_R_SM = 4.0f; /* --mx-r-sm: inputs / selects */
[[maybe_unused]] inline constexpr float MX_R_MD = 8.0f; /* --mx-r-md: grouped cards    */
[[maybe_unused]] inline constexpr float MX_R_PILL = 999.0f; /* fully rounded; clamped to h/2 */
