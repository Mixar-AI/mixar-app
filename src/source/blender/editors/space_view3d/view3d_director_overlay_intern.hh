/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Shared helpers between the Director overlay implementation files.
 * Not part of the space API.
 */

#pragma once

struct ARegion;
struct DirectorViewState;
struct bContext;
struct rctf;
struct uiBlock;
struct uiBut;

/** Flow-styled popup blocks (view3d_director_popup.cc); presentation only —
 * every row invokes the Python-owned `mixar.director_*` operators. */
uiBlock *view3d_director_lens_popup_create(bContext *C, ARegion *region, void *arg);
uiBlock *view3d_director_aspect_popup_create(bContext *C, ARegion *region, void *arg);
uiBlock *view3d_director_moves_popup_create(bContext *C, ARegion *region, void *arg);

/** Rounded Flow-style panel in the shared Director palette. */
void director_overlay_panel_draw(const rctf &rect, float radius);

/** Icon (+ optional label) button that invokes a Python-owned operator. */
uiBut *director_overlay_operator_button(uiBlock *block,
                                        const char *operator_id,
                                        int icon,
                                        const char *label,
                                        int x,
                                        int y,
                                        int width,
                                        int height,
                                        const char *tooltip);

void director_overlay_disable_button(uiBut *button, bool disabled);

/** Lens, navigation, aspect, and frame tools pinned to the camera gate. */
void view3d_director_frame_controls_draw(uiBlock *block,
                                         const bContext *C,
                                         const ARegion *region,
                                         const DirectorViewState &state,
                                         int unit,
                                         int gap);
