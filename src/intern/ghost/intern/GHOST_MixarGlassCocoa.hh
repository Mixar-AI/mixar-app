/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Mixar: GHOST-owned macOS glass behind a GPU window. See
 * `GHOST_MixarGlassCocoa.mm` for why the frost is a sibling of the Metal
 * view and never its parent.
 */

#pragma once

#ifdef __OBJC__

@class NSWindow;
@class NSView;

void Mixar_CocoaGlassSetEnabled(NSWindow *win, bool enable);
void Mixar_CocoaGlassSyncRadius(NSWindow *win, float radius);
/** Flip this view's CAMetalLayer so WindowServer honours per-pixel alpha. */
void Mixar_CocoaGlassAllowMetalAlpha(NSView *host);

#endif
