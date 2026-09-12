/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Mixar: DWM frost behind a GPU window. See `GHOST_MixarGlassWin32.cc`.
 * `hwnd` is an HWND; the type stays unmentioned so this header can be
 * included after `windows.h` without a conflicting typedef.
 */

#pragma once

#ifdef _WIN32

bool Mixar_Win32GlassSetEnabled(void *hwnd, bool enable);

#endif
