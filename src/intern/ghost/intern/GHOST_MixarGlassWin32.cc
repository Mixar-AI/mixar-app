/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Native frost behind Mixar's island / pill windows on Windows.
 *
 * macOS uses Regular `NSGlassEffectView`. Win32's equivalent is DWM
 * Desktop Acrylic (Win11 22621+) plus a full-window blur-behind so
 * older builds still frost what sits under the HWND. The old 1×1
 * blur region only opted the window into per-pixel alpha — it was
 * deliberately not glass.
 *
 * The GPU still paints a REPLACE wash and opaque chrome. DWM composites
 * that alpha over the frost. Never wrap the GL content HWND.
 */

#include "GHOST_MixarGlassWin32.hh"

#ifdef _WIN32

#  include <dwmapi.h>
#  include <windows.h>

namespace {

/* SDK headers in this pin predate these attributes. The numbers are
 * stable; DwmSetWindowAttribute fails closed on an older OS. */
constexpr DWORD kDwmwaUseImmersiveDarkMode = 20;
constexpr DWORD kDwmwaSystemBackdropType = 38;
constexpr DWORD kDwmwaRedirectionBitmapAlpha = 39;
constexpr DWORD kDwmsbtNone = 1;
constexpr DWORD kDwmsbtTransientWindow = 3; /* Desktop Acrylic */

void mixar_set_dword_attr(HWND hwnd, DWORD attr, DWORD value)
{
  DwmSetWindowAttribute(hwnd, attr, &value, sizeof(value));
}

void mixar_set_bool_attr(HWND hwnd, DWORD attr, bool value)
{
  const BOOL flag = value ? TRUE : FALSE;
  DwmSetWindowAttribute(hwnd, attr, &flag, sizeof(flag));
}

}  // namespace

void Mixar_Win32GlassSetEnabled(void *hwnd_handle, const bool enable)
{
  HWND hwnd = static_cast<HWND>(hwnd_handle);
  if (hwnd == nullptr) {
    return;
  }

  /* Whole client participates in DWM composition. */
  const MARGINS margins = enable ? MARGINS{-1, -1, -1, -1} : MARGINS{0, 0, 0, 0};
  DwmExtendFrameIntoClientArea(hwnd, &margins);

  /* Win11 26100+ ignores client alpha unless this is on, and then
   * wants premultiplied pixels. Chrome is A=1 (already premul); the
   * 0.20 wash is close enough that frost still reads. */
  mixar_set_bool_attr(hwnd, kDwmwaRedirectionBitmapAlpha, enable);
  mixar_set_bool_attr(hwnd, kDwmwaUseImmersiveDarkMode, enable);
  mixar_set_dword_attr(
      hwnd, kDwmwaSystemBackdropType, enable ? kDwmsbtTransientWindow : kDwmsbtNone);

  /* Full window, not a 1×1 hole: fEnable with no blur-region is the
   * entire client. That is the Win10 frost; Acrylic sits on top of it
   * where the OS supports it. */
  DWM_BLURBEHIND bb = {};
  bb.dwFlags = DWM_BB_ENABLE;
  bb.fEnable = enable ? TRUE : FALSE;
  bb.hRgnBlur = nullptr;
  DwmEnableBlurBehindWindow(hwnd, &bb);
}

#endif
