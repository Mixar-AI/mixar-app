# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Library pane: every control is its label plus padding, at any window size.

`agent_ui_generations_layout.hh` is Blender-free so this can execute the
production resolver. Typography stays fixed while the window scales, which is
what used to ellipsize captions and collapse chip boxes under the font.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

CPP = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_agent_bubble"


def test_painters_consume_the_resolved_frame():
    layout_cc = (CPP / "agent_ui_generations_layout.cc").read_text(encoding="utf-8")
    grid = (CPP / "agent_ui_generations_grid.cc").read_text(encoding="utf-8")
    detail = (CPP / "agent_ui_generations_detail.cc").read_text(encoding="utf-8")
    nav = (CPP / "agent_ui_generations_navigation.cc").read_text(encoding="utf-8")
    cmake = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "agent_ui_generations_resolve" in layout_cc
    assert "pane_text_width" in layout_cc
    assert "m.cols" in grid and "grid.cols" in grid
    # The name used to share its line with the age, so every caption ellipsized.
    assert "grid.tile - age_w" not in grid
    assert "avail - caption" in grid
    assert "panel.ymin + GEN_DETAIL_FOOT * u" in detail
    assert "frame.rail_div_x" in nav
    assert "agent_ui_generations_layout.cc" in cmake
    assert "agent_ui_generations_layout.hh" in cmake


def _cxx():
    """Prefer a compiler that can see the C++ standard library.

    This image's clang is wired to a GCC 14 include path that is not
    installed, so `clang++` exists and still cannot compile `<algorithm>`.
    """
    for name in ("g++", "clang++"):
        path = shutil.which(name)
        if not path:
            continue
        probe = subprocess.run(
            [path, "-std=c++17", "-x", "c++", "-fsyntax-only", "-"],
            input=b"#include <algorithm>\nint main(){return 0;}\n",
            capture_output=True,
        )
        if probe.returncode == 0:
            return path
    return None


def test_padding_survives_resize_and_large_type(tmp_path):
    compiler = _cxx()
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source = tmp_path / "layout.cc"
    source.write_text(r'''#include <cstdio>
#include <cstring>
#include "agent_ui_generations_layout.hh"
using namespace blender;

static float text_px(const char *s, float font) {
  return font * 0.52f * float(std::strlen(s));
}

static int fails = 0;
#define CHECK(cond) do { \
  if (!(cond)) { \
    std::fprintf(stderr, "fail %d: %s\n", __LINE__, #cond); \
    fails++; \
  } \
} while (0)

static bool overlap(const GenBox &a, const GenBox &b) {
  return a.xmin < b.xmax - 0.5f && b.xmin < a.xmax - 0.5f &&
         a.ymin < b.ymax - 0.5f && b.ymin < a.ymax - 0.5f;
}

static GenFrame layout(float xmin, float xmax, float ymin, float ymax, float u,
                       float font_chip, float font_cap, float font_action) {
  GenResolveInput in{};
  in.panel_xmin = xmin;
  in.panel_xmax = xmax;
  in.panel_ymin = ymin;
  in.panel_ymax = ymax;
  in.u = u;
  in.font_chip = font_chip;
  in.font_cap = font_cap;
  in.font_title = font_chip * 1.4f;
  in.font_meta = font_chip * 0.85f;
  in.font_desc = font_chip * 0.95f;
  in.font_action = font_action;
  in.font_lib = font_cap;
  for (int i = 0; i < GEN_LAYOUT_RAIL_COUNT; i++) {
    in.rail_label[i] = text_px(GEN_RAIL_LABELS[i], font_chip);
  }
  for (int i = 0; i < GEN_LAYOUT_CHIP_COUNT; i++) {
    in.chip_label[i] = text_px(GEN_FILTER_LABELS[i], font_chip);
  }
  for (int i = 0; i < GEN_ACTION_PRIMARY_COUNT; i++) {
    in.action_primary = std::max(in.action_primary, text_px(GEN_ACTION_PRIMARY[i], font_action));
  }
  for (int i = 0; i < GEN_ACTION_SECONDARY_COUNT; i++) {
    in.action_secondary = std::max(in.action_secondary,
                                   text_px(GEN_ACTION_SECONDARY[i], font_action));
  }
  in.rail_w_design = 198.0f * u;
  in.rail_h_design = 47.0f * u;
  in.chip_h_design = 0.0f;
  in.tile_design = 146.0f * u;
  in.preview_design = 316.0f * u;
  in.sort_w_design = 56.0f * u;
  in.action_h_design = 0.0f;
  in.foot_design = 28.0f * u;
  in.cap_gap_design = 10.0f * u;
  in.row_gap_design = 20.0f * u;
  in.lib_row_design = 38.0f * u;
  in.max_cols = 4;
  return agent_ui_generations_resolve(in);
}

static void check_frame(const GenFrame &f, const GenResolveInput &probe, float panel_w) {
  const float pad = gen_pad_px(probe.u, probe.font_chip);
  const float gap = gen_gap_px(probe.u, probe.font_chip);
  CHECK(f.pad + 0.01f >= pad);
  CHECK(f.gap + 0.01f >= gap);
  CHECK(f.chip_h + 0.01f >= gen_control_h(probe.font_chip, f.pad));
  const float action_pad = gen_pad_px(probe.u, probe.font_action);
  CHECK(f.action_h + 0.01f >= gen_control_h(probe.font_action, action_pad));
  CHECK(f.chip_pad_x + 0.05f >= f.pad * GEN_PAD_SHRINK);
  CHECK(f.cols >= 1 && f.cols <= probe.max_cols);
  CHECK(f.tile >= 1.0f);
  CHECK(f.rail[0].xmin + 0.01f >= probe.panel_xmin + f.pad);
  CHECK(f.detail_x + f.detail_w <= probe.panel_xmax - f.pad + 0.05f);
  CHECK(f.grid_bottom + 0.01f >= probe.panel_ymin + f.pad);
  CHECK(f.rail[0].xmax > f.rail[0].xmin);
  CHECK(f.rail[0].ymax > f.rail[0].ymin);
  CHECK(f.action_w0 > 0.0f && f.action_w1 > 0.0f);
      const float each = gen_control_w(std::max(probe.action_primary, probe.action_secondary), action_pad);
      /* Rail ellipsizes before an action loses the padding around its label.
       * Only a panel too small for one padded button plus a stub rail clamps. */
      const float rail_stub = 2.0f * f.pad + f.gap + f.rail_dot_r * 2.0f;
      if (panel_w + 0.5f >= each + rail_stub + 2.0f * f.pad) {
        CHECK(f.action_w0 + 0.5f >= each);
        CHECK(f.actions_stacked || f.action_w1 + 0.5f >= each);
      }
  float prev_right = f.grid_x;
  int row = 0;
  for (int i = 0; i < GEN_LAYOUT_CHIP_COUNT; i++) {
    const GenBox &c = f.chip[i];
    CHECK(c.xmax > c.xmin && c.ymax > c.ymin);
    CHECK(c.xmax - c.xmin + 0.5f >= gen_control_w(probe.chip_label[i], f.chip_pad_x));
    CHECK(c.ymax - c.ymin + 0.01f >= f.chip_h);
    if (i > 0 && c.ymax > f.chip[i - 1].ymin - 0.5f && c.ymin < f.chip[i - 1].ymax - 0.5f) {
      CHECK(c.xmin + 0.5f >= prev_right + f.gap);
    }
    else if (i > 0) {
      row++;
      CHECK(c.xmin + 0.5f >= f.grid_x);
    }
    prev_right = c.xmax;
    if (overlap(c, f.sort)) {
      std::fprintf(stderr, "chip %d overlaps sort\n", i);
      fails++;
    }
    for (int j = 0; j < i; j++) {
      if (overlap(c, f.chip[j])) {
        std::fprintf(stderr, "chip %d overlaps %d\n", i, j);
        fails++;
      }
    }
  }
      CHECK(f.chip_rows >= 1 && f.chip_rows <= GEN_LAYOUT_CHIP_COUNT + 1);
      CHECK(f.grid_x + 0.5f >= f.rail_div_x);
  if (panel_w >= 900.0f) {
    CHECK(f.grid_right + 0.5f <= f.detail_div_x);
    CHECK(f.detail_div_x + 0.5f <= f.detail_x);
    const float grid_w = f.grid_right - f.grid_x;
    const float used = f.tile * float(f.cols) + f.tile_gap * float(f.cols - 1);
    CHECK(used <= grid_w + 0.5f);
    CHECK(f.tile + 0.01f >= std::min(gen_min_tile(probe.font_cap, probe.u), grid_w));
  }
  (void)row;
}

int main() {
  /* Default island: four columns, actions side by side, padding on every edge. */
  {
    const float u = 1.0f;
    GenFrame f = layout(6, 1304, 0, 360, u, 18, 16, 15);
    CHECK(f.cols == 4);
    CHECK(!f.actions_stacked);
    CHECK(f.chip_rows == 1);
    CHECK(f.pad + 0.01f >= GEN_PAD_FLOOR * u);
    CHECK(f.gap + 0.01f >= GEN_GAP_FLOOR * u);
    GenResolveInput probe{};
    probe.u = u;
    probe.font_chip = 18;
    probe.font_cap = 16;
    probe.font_action = 15;
    probe.panel_xmin = 6;
    probe.panel_xmax = 1304;
    probe.panel_ymin = 0;
    probe.max_cols = 4;
    for (int i = 0; i < GEN_LAYOUT_CHIP_COUNT; i++) {
      probe.chip_label[i] = text_px(GEN_FILTER_LABELS[i], 18);
    }
    probe.action_primary = 0;
    probe.action_secondary = 0;
    for (int i = 0; i < GEN_ACTION_PRIMARY_COUNT; i++) {
      probe.action_primary = std::max(probe.action_primary, text_px(GEN_ACTION_PRIMARY[i], 15));
    }
    for (int i = 0; i < GEN_ACTION_SECONDARY_COUNT; i++) {
      probe.action_secondary = std::max(probe.action_secondary, text_px(GEN_ACTION_SECONDARY[i], 15));
    }
    check_frame(f, probe, 1298);
  }

  /* Narrow window, same font: drop columns and stack the actions. */
  {
    GenFrame f = layout(0, 640, 0, 300, 0.5f, 18, 16, 15);
    CHECK(f.cols < 4);
    CHECK(f.actions_stacked);
    CHECK(f.pad + 0.01f >= GEN_PAD_EM * 18.0f);
  }

  /* Large type at the design width: boxes grow with the font, not the artboard. */
  {
    const float font = 32.0f;
    GenFrame f = layout(6, 1304, 0, 480, 1.0f, font, 28, 26);
    CHECK(f.chip_h + 0.01f >= font + 2.0f * gen_pad_px(1.0f, font));
    CHECK(f.action_h + 0.01f >= 26.0f + 2.0f * gen_pad_px(1.0f, 26.0f));
    CHECK(f.cols >= 1);
  }

  for (float w = 480.0f; w <= 1600.0f; w += 80.0f) {
    for (float h = 240.0f; h <= 520.0f; h += 70.0f) {
      for (float font : {12.0f, 18.0f, 28.0f}) {
        const float u = w / 1310.0f;
        GenFrame f = layout(0, w, 0, h, u, font, font * 0.9f, font * 0.85f);
        GenResolveInput probe{};
        probe.u = u;
        probe.font_chip = font;
        probe.font_cap = font * 0.9f;
        probe.font_action = font * 0.85f;
        probe.panel_xmin = 0;
        probe.panel_xmax = w;
        probe.panel_ymin = 0;
        probe.max_cols = 4;
        for (int i = 0; i < GEN_LAYOUT_CHIP_COUNT; i++) {
          probe.chip_label[i] = text_px(GEN_FILTER_LABELS[i], font);
        }
        for (int i = 0; i < GEN_ACTION_PRIMARY_COUNT; i++) {
          probe.action_primary = std::max(probe.action_primary,
                                          text_px(GEN_ACTION_PRIMARY[i], probe.font_action));
        }
        for (int i = 0; i < GEN_ACTION_SECONDARY_COUNT; i++) {
          probe.action_secondary = std::max(probe.action_secondary,
                                            text_px(GEN_ACTION_SECONDARY[i], probe.font_action));
        }
        check_frame(f, probe, w);
      }
    }
  }
  return fails ? 1 : 0;
}
''')
    binary = tmp_path / "layout"
    subprocess.run(
        [compiler, "-std=c++17", "-I", str(CPP), str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
