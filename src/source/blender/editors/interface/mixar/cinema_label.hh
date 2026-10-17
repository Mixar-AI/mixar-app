/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

struct rcti;
struct rctf;

namespace blender::ui {
/** The bundled Clash Grotesk display face as a BLF font id, or -1 when the
 * datafile is missing. Resolved by path on every call so no stale id survives
 * a UI-font reload. The Cinema label's face; the AI Provider sheet draws in
 * the island's UI face instead (`interface_mixar_sheet.cc`). */
int mixar_clash_grotesk_font();
/** Shared Cinema capsule: one visible height, inset, radius, fill and border
 * in both hosts, independent of their native header hit-target heights. */
void mixar_cinema_background(const rctf &bounds, float selected, float emphasis);
/** Gradient label with an optional leading icon (start colour) and a small
 * rounded `mixar_chrome::cinema_stage_tag` label ("BETA", end colour); the three
 * are fitted together inside `bounds`. */
void mixar_cinema_label(const rcti &bounds,
                        const char *label,
                        float selected,
                        bool disabled = false,
                        int icon_id = 0);
}  // namespace blender::ui
