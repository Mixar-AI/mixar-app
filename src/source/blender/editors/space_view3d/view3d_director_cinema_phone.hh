/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode's phone hand-off — the Virtual Camera's whole UI.
 *
 * `modules/virtual_camera/core/wm_mirror.py` publishes the session on the
 * WindowManager mirror this surface reads; the `mixar.virtual_camera_*`
 * operators own every behaviour. Its own header rather than a section of
 * `view3d_director_cinema.hh`, which is at the module size limit.
 */

#pragma once

#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/** What the strip's button paints, read cheaply on every Cinema draw. */
struct CinemaPhoneStatus {
  bool running = false;
  bool connected = false;
};

CinemaPhoneStatus cinema_phone_status(const bContext *C);

/**
 * The top strip's phone hand-off button: paints its three states (off,
 * waiting, connected) and drives `mixar.virtual_camera_toggle`. Collapses to
 * the glyph alone when \a rect cannot hold the label.
 */
void cinema_draw_phone_button(ui::Block *block,
                              const bContext *C,
                              const ARegion *region,
                              const rctf &rect);

/**
 * The pairing card over the stage, while the server is up and no phone has
 * answered: the QR painted from its modules, the link, and Copy / New Code /
 * Cancel. Silent in every other state.
 */
void cinema_draw_phone_card(ui::Block *block, const bContext *C, const ARegion *region);

}  // namespace blender
