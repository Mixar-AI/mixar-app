# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compile the production density resolver independently of Blender."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ROOT / "src/source/blender/editors/include"


def test_tokens_and_surface_alias_named_density():
    tokens = (INCLUDE / "UI_mixar_tokens.hh").read_text(encoding="utf-8")
    assert "mixar_density_unscaled(MixarDensity::Default)" in tokens
    assert "mixar_density_unscaled(MixarDensity::Compact)" in tokens
    rna = (ROOT / "src/source/blender/makesrna/intern/rna_ui_api.cc").read_text(
        encoding="utf-8"
    )
    assert 'RNA_def_enum(func, "density", mixar_density_items' in rna
    gallery = (
        ROOT / "src/scripts/mixar/modules/common/ui/panels/ui_gallery_panel.py"
    ).read_text(encoding="utf-8")
    assert "density=fixture.density" in gallery


def test_densities_preserve_default_and_scale_exactly_once(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = tmp_path / "density.cc"
    source.write_text(
        r'''
#include "UI_mixar_density.hh"
#include <cassert>
#include <initializer_list>
#include <type_traits>
using namespace blender::ui;
static_assert(!std::is_convertible_v<MixarDensityMetrics, float>);
int main() {
  const MixarDensityMetrics expected_default{44, 20, 12, 18, 8, 14};
  const MixarDensityMetrics expected_compact{32, 12, 8, 16, 6, 10};
  for (float unit : {0.5f, 1.0f, 1.5f, 2.0f}) {
    const auto def = mixar_density_metrics(MixarDensity::Default, unit);
    const auto compact = mixar_density_metrics(MixarDensity::Compact, unit);
    assert(def.control_height == expected_default.control_height * unit);
    assert(def.padding == expected_default.padding * unit);
    assert(def.padding == 20.0f * unit);
    assert(compact.control_height == expected_compact.control_height * unit);
    assert(compact.padding == expected_compact.padding * unit);
    assert(compact.gap == expected_compact.gap * unit);
    assert(compact.control_height < def.control_height);
    assert(compact.padding < def.padding);
    assert(compact.gap < def.gap);
    assert(mixar_density_scale(MixarDensity::Default) == 1.0f);
    assert(mixar_density_scale(MixarDensity::Compact) ==
           expected_compact.control_height / expected_default.control_height);
  }
  const auto raw = mixar_density_unscaled(MixarDensity::Default);
  assert(raw.control_height == 44.0f && raw.radius == 14.0f);
}
'''
    )
    binary = tmp_path / "density"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-I",
            str(INCLUDE),
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True)
