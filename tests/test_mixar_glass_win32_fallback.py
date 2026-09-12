# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute the Win32 glass policy with a controllable DWM implementation.

This validates HRESULT handling and rollback on non-Windows CI. Native Acrylic
appearance is separately exercised by the GUI harness on a Windows machine.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_dwm_failures_roll_back_to_an_opaque_shaped_window(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if compiler is None:
        pytest.skip('C++ compiler unavailable')
    (tmp_path / 'windows.h').write_text(r'''
#pragma once
#include <cstdint>
using DWORD = uint32_t;
using BOOL = int;
using HRESULT = int32_t;
using HWND = void *;
constexpr BOOL TRUE = 1, FALSE = 0;
constexpr DWORD SPI_GETHIGHCONTRAST = 0x42, HCF_HIGHCONTRASTON = 1;
struct HIGHCONTRASTW { uint32_t cbSize, dwFlags; void *lpszDefaultScheme; };
#define FAILED(hr) ((hr) < 0)
BOOL SystemParametersInfoW(DWORD, uint32_t, void *, DWORD);
''')
    (tmp_path / 'dwmapi.h').write_text(r'''
#pragma once
#include "windows.h"
struct MARGINS { int left, right, top, bottom; };
struct DWM_BLURBEHIND { DWORD dwFlags; BOOL fEnable; void *hRgnBlur; BOOL fTransitionOnMaximized; };
constexpr DWORD DWM_BB_ENABLE = 1;
HRESULT DwmSetWindowAttribute(HWND, DWORD, const void *, DWORD);
HRESULT DwmExtendFrameIntoClientArea(HWND, const MARGINS *);
HRESULT DwmEnableBlurBehindWindow(HWND, const DWM_BLURBEHIND *);
HRESULT DwmIsCompositionEnabled(BOOL *);
''')
    source = ROOT / 'src/intern/ghost/intern/GHOST_MixarGlassWin32.cc'
    (tmp_path / 'main.cc').write_text(r'''
#include <cassert>
#include "dwmapi.h"
static bool contrast, composition, material_supported, alpha_supported, legacy_supported, frame_supported;
static DWORD build;
static bool alpha, legacy, extended;
static DWORD material;
static int calls;
BOOL SystemParametersInfoW(DWORD, uint32_t, void *out, DWORD)
{
  static_cast<HIGHCONTRASTW *>(out)->dwFlags = contrast ? HCF_HIGHCONTRASTON : 0;
  return TRUE;
}
HRESULT DwmSetWindowAttribute(HWND, DWORD attr, const void *value, DWORD)
{
  ++calls;
  const DWORD v = *static_cast<const DWORD *>(value);
  if (attr == 38) {
    if (v == 3 && !material_supported) return -1;
    material = v;
  }
  if (attr == 39) { // DWMWA_REDIRECTIONBITMAP_ALPHA since build 26100.
    if (build < 26100) return -1; // Older SDKs called this slot DWMWA_LAST.
    if (v && !alpha_supported) return -1;
    alpha = v;
  }
  if (attr != 20 && attr != 38 && attr != 39) return -1;
  return 0;
}
HRESULT DwmExtendFrameIntoClientArea(HWND, const MARGINS *m)
{
  ++calls;
  if (m->left == -1 && !frame_supported) return -1;
  extended = m->left == -1;
  return 0;
}
HRESULT DwmEnableBlurBehindWindow(HWND, const DWM_BLURBEHIND *b)
{
  ++calls;
  if (b->fEnable && !legacy_supported) return -1;
  legacy = b->fEnable;
  return 0;
}
HRESULT DwmIsCompositionEnabled(BOOL *out) { *out = composition; return 0; }
bool Mixar_Win32GlassSetEnabled(void *, bool);
static void reset()
{
  composition = material_supported = alpha_supported = legacy_supported = frame_supported = true;
  contrast = alpha = legacy = extended = false;
  material = 1;
  build = 26100;
  calls = 0;
}
static void opaque() { assert(!alpha && !legacy && !extended && material == 1); }
int main()
{
  void *window = reinterpret_cast<void *>(1);
  reset();
  assert(!Mixar_Win32GlassSetEnabled(nullptr, true)); assert(calls == 0);
  assert(Mixar_Win32GlassSetEnabled(window, true));
  assert(alpha && legacy && extended && material == 3);
  assert(Mixar_Win32GlassSetEnabled(window, false)); opaque();
  // Windows 10: legacy alpha succeeds but provides NO material.
  reset(); build = 19045; material_supported = false;
  assert(!Mixar_Win32GlassSetEnabled(window, true)); opaque();
  // Windows 11 22621: Acrylic exists, but attribute 39 is rejected.
  reset(); build = 22621;
  assert(Mixar_Win32GlassSetEnabled(window, true)); assert(legacy && material == 3);
  assert(!alpha);
  // Windows 11 26100: the documented attribute is sufficient for alpha.
  reset(); legacy_supported = false;
  assert(Mixar_Win32GlassSetEnabled(window, true)); assert(alpha && !legacy && material == 3);
  // Inject failures of both alpha APIs; this is fault coverage, not an OS version.
  reset(); alpha_supported = legacy_supported = false;
  assert(!Mixar_Win32GlassSetEnabled(window, true)); opaque();
  reset(); frame_supported = false;
  assert(!Mixar_Win32GlassSetEnabled(window, true)); opaque();
  reset(); contrast = true;
  assert(!Mixar_Win32GlassSetEnabled(window, true)); opaque();
  reset(); composition = false;
  assert(!Mixar_Win32GlassSetEnabled(window, true)); opaque();
  // A settings change after success must remove every active effect.
  reset(); assert(Mixar_Win32GlassSetEnabled(window, true)); contrast = true;
  assert(!Mixar_Win32GlassSetEnabled(window, true)); opaque();
}
''')
    executable = tmp_path / 'glass_policy'
    subprocess.run([compiler, '-std=c++17', '-D_WIN32', '-I', str(tmp_path),
                    str(source), str(tmp_path / 'main.cc'), '-o', str(executable)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
