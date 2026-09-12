/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Mixar: GHOST-owned macOS glass behind a GPU window. See
 * `GHOST_MixarGlassCocoa.mm` for the retained Metal content-view lifecycle.
 */

#pragma once

#ifdef __OBJC__

@class NSWindow;
@class NSView;

bool Mixar_CocoaGlassSetEnabled(NSWindow *win, bool enable);
void Mixar_CocoaGlassSyncRadius(NSWindow *win, float radius);
/** Flip this view's CAMetalLayer so WindowServer honours per-pixel alpha. */
void Mixar_CocoaGlassAllowMetalAlpha(NSView *host);

#endif
