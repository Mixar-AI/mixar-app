# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute the native socket palette and sizing rules without a Blender process."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPACE = ROOT / "src/source/blender/editors/space_mixie"


def test_native_palette_and_zoom_bounds(tmp_path):
    compiler = next((shutil.which(c) for c in ("c++", "clang++", "g++")
                     if shutil.which(c)), None)
    if compiler is None:
        pytest.skip("Native socket contract requires a C++ compiler")
    source = tmp_path / "socket_style_test.cc"
    source.write_text(r'''
#include "mixie_moodboard_socket_style.hh"
#include <cassert>
using namespace blender::ed::mixie::socket_style;
int main() {
  assert(type_color("IMAGE") == IMAGE);
  assert(type_color("VIDEO") == VIDEO);
  assert(type_color("MESH") == MESH);
  assert(type_color("IMAGE,IMAGE") == IMAGE);
  for (const char *types : {"IMAGE,VIDEO", "IMAGE,MESH", "MESH,VIDEO",
                            "VIDEO,MESH,IMAGE", "MESH,IMAGE"}) {
    assert(type_color(types) == MIXED);
  }
  for (const char *types : {"", "CUSTOM", "CUSTOM_IMAGE", "MESHES", "IMAGE,",
                            ",IMAGE", "IMAGE,,VIDEO", "IMAGE,CUSTOM"}) {
    assert(type_color(types) == NEUTRAL);
  }
  // Distinct semantic hues: cyan image, violet video, mint mesh.
  assert(IMAGE[1] > IMAGE[0] && IMAGE[2] > IMAGE[0]);
  assert(VIDEO[0] > VIDEO[1] && VIDEO[2] > VIDEO[1]);
  assert(MESH[1] > MESH[0] && MESH[1] > MESH[2]);
  for (float scale : {0.75f, 1.0f, 1.5f, 2.0f, 3.0f}) {
    for (bool output : {false, true}) {
      float previous = 0;
      for (float zoom : {0.01f, 0.1f, 0.3f, 0.68f, 1.f, 2.f, 5.f, 20.f}) {
        const float radius = radius_px(zoom, scale, output);
        assert(radius >= (output ? 8 : 6) * scale);
        assert(radius <= (output ? 10 : 8) * scale);
        assert(radius >= previous);
        assert(hit_radius_px(zoom, scale, output) >= 12 * scale);
        assert(hit_radius_px(zoom, scale, output) >= radius + 4 * scale);
        previous = radius;
      }
    }
  }
}
''')
    executable = tmp_path / "socket_style_test"
    subprocess.run([compiler, "-std=c++17", "-I", str(SPACE), str(source),
                    "-o", str(executable)], check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
