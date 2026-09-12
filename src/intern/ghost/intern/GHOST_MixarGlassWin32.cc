/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Desktop Acrylic behind the island and pill on Windows 11 22621+.
 * Earlier systems keep the shared GPU material on an opaque, shaped bed.
 * DwmEnableBlurBehindWindow enables alpha composition on older DWM paths;
 * it has NOT produced a blur since Windows 8 and is not a frost fallback.
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
constexpr DWORD kDwmwaRedirectionBitmapAlpha = 39;
constexpr DWORD kDwmsbtNone = 1;
constexpr DWORD kDwmsbtTransientWindow = 3;

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
  const HRESULT material = mixar_set_dword_attr(
      hwnd, kDwmwaSystemBackdropType, kDwmsbtTransientWindow);
  const HRESULT alpha = mixar_set_bool_attr(hwnd, kDwmwaRedirectionBitmapAlpha, true);
  DWM_BLURBEHIND bb = {};
  bb.dwFlags = DWM_BB_ENABLE;
  bb.fEnable = TRUE;
  const HRESULT legacy_alpha = DwmEnableBlurBehindWindow(hwnd, &bb);

  /* Do not expose unblurred desktop text through a 20% wash if Acrylic was
   * rejected. The caller paints its opaque fallback after this rollback. */
  if (FAILED(frame) || FAILED(material) || (FAILED(alpha) && FAILED(legacy_alpha))) {
    mixar_disable_glass(hwnd);
    return false;
  }
  return true;
}

#endif
