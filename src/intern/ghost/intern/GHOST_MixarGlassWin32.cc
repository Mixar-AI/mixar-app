/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Per-pixel alpha behind the island and pill on Windows.
 * `DWMSBT_TRANSIENTWINDOW` Acrylic cannot sample the parent Mixar viewport
 * (the island is an owned always-on-top HWND) and fills a gray slab instead.
 * Frame extension plus redirection/legacy alpha lets the GPU wash show
 * the scene through the card. DwmEnableBlurBehindWindow has not produced a
 * blur since Windows 8; it is an alpha path, not a frost fallback.
 */

#include "GHOST_MixarGlassWin32.hh"

#ifdef _WIN32

#  include <windows.h>
#  include <dwmapi.h>

namespace {

/* Numeric constants also compile with the older SDK used by release builds.
 * HRESULTs, rather than OS-version guesses, decide whether frost is usable. */
constexpr DWORD kDwmwaUseImmersiveDarkMode = 20;
constexpr DWORD kDwmwaSystemBackdropType = 38;
/* DWMWA_REDIRECTIONBITMAP_ALPHA, supported since Windows 11 build 26100.
 * Older SDKs end the enum at 39 (DWMWA_LAST); older runtimes reject this
 * request. Keep the numeric value so release builds need no newer SDK.
 * https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute */
constexpr DWORD kDwmwaRedirectionBitmapAlpha = 39;
constexpr DWORD kDwmsbtNone = 1;

HRESULT mixar_set_dword_attr(HWND hwnd, DWORD attr, DWORD value)
{
  return DwmSetWindowAttribute(hwnd, attr, &value, sizeof(value));
}

HRESULT mixar_set_bool_attr(HWND hwnd, DWORD attr, bool value)
{
  const BOOL flag = value ? TRUE : FALSE;
  return DwmSetWindowAttribute(hwnd, attr, &flag, sizeof(flag));
}

void mixar_disable_glass(HWND hwnd)
{
  mixar_set_dword_attr(hwnd, kDwmwaSystemBackdropType, kDwmsbtNone);
  mixar_set_bool_attr(hwnd, kDwmwaRedirectionBitmapAlpha, false);
  const MARGINS margins = {0, 0, 0, 0};
  DwmExtendFrameIntoClientArea(hwnd, &margins);
  DWM_BLURBEHIND bb = {};
  bb.dwFlags = DWM_BB_ENABLE;
  bb.fEnable = FALSE;
  DwmEnableBlurBehindWindow(hwnd, &bb);
}

}  // namespace

bool Mixar_Win32GlassSetEnabled(void *hwnd_handle, const bool enable)
{
  HWND hwnd = static_cast<HWND>(hwnd_handle);
  if (hwnd == nullptr) {
    return false;
  }
  BOOL composition = FALSE;
  HIGHCONTRASTW contrast = {};
  contrast.cbSize = sizeof(contrast);
  const bool high_contrast = SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof(contrast),
                                                  &contrast, 0) &&
                             (contrast.dwFlags & HCF_HIGHCONTRASTON);
  if (!enable || high_contrast || FAILED(DwmIsCompositionEnabled(&composition)) || !composition) {
    mixar_disable_glass(hwnd);
    return !enable;
  }

  mixar_set_bool_attr(hwnd, kDwmwaUseImmersiveDarkMode, true);
  const MARGINS margins = {-1, -1, -1, -1};
  const HRESULT frame = DwmExtendFrameIntoClientArea(hwnd, &margins);
  /* Explicitly clear any leftover Acrylic so a previous enable cannot keep
   * the gray slab. Failure here is ignored: None is the DWM default. */
  mixar_set_dword_attr(hwnd, kDwmwaSystemBackdropType, kDwmsbtNone);
  const HRESULT alpha = mixar_set_bool_attr(hwnd, kDwmwaRedirectionBitmapAlpha, true);
  DWM_BLURBEHIND bb = {};
  bb.dwFlags = DWM_BB_ENABLE;
  bb.fEnable = TRUE;
  const HRESULT legacy_alpha = DwmEnableBlurBehindWindow(hwnd, &bb);

  if (FAILED(frame) || (FAILED(alpha) && FAILED(legacy_alpha))) {
    mixar_disable_glass(hwnd);
    return false;
  }
  return true;
}

#endif
