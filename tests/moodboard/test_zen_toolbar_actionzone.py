# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the real native edge policy; a covered fixed toolbar must not resize."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_zen_fixed_toolbar_has_no_resize_sash(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    source = (ROOT / 'src/source/blender/editors/screen/area.cc').read_text()
    start = source.index('static bool region_azone_edge_poll(')
    end = source.index('\nstatic void region_azone_edge_init(', start)
    policy = source[start:end]
    program = r'''
#include <cassert>
#define ELEM(v,a,b) ((v)==(a)||(v)==(b))
enum {RGN_FLAG_POLL_FAILED=1, RGN_FLAG_HIDDEN=2, RGN_FLAG_TOO_SMALL=4};
enum {RGN_SPLIT_PREV=1, RGN_ALIGN_HIDE_WITH_PREV=2};
enum {RGN_TYPE_WINDOW, RGN_TYPE_TOOLS, RGN_TYPE_HEADER, RGN_TYPE_TOOL_HEADER,
      RGN_TYPE_NAV_BAR, RGN_TYPE_TOOL_PROPS, RGN_TYPE_CHANNELS, RGN_TYPE_UI,
      VIEW3D_SCENES_DRAWER_REGION_TYPE};
enum {SPACE_VIEW3D, SPACE_PROPERTIES};
enum {USER_APP_HIDE_REGION_TOGGLE=1, USER_APP_LOCK_EDGE_RESIZE=2};
struct ARegion {
  int flag=0,alignment=0,regiontype=RGN_TYPE_TOOLS;
  ARegion *prev=nullptr;
  bool overlap=true;
};
struct ScrArea {
  int winy=600,spacetype=SPACE_VIEW3D;
  bool zen=true;
  ARegion *drawer=nullptr;
};
struct {int app_flag=0;} U;
bool (*g_mixar_area_chromeless)(const ScrArea *)=nullptr;
int ED_area_headersize(){return 20;}
ARegion *BKE_area_find_region_type(ScrArea *a,int){return a->drawer;}
namespace ui {
bool mixar_area_floats_viewport_chrome(const ScrArea *a){
  return a->spacetype==SPACE_VIEW3D && a->zen;
}
}
''' + policy + r'''
int main(){
  ScrArea area; ARegion tools;
  assert(!region_azone_edge_poll(&area,&tools,false));
  area.zen=false;
  assert(region_azone_edge_poll(&area,&tools,false)); // Engine still resizes.
  area.zen=true; tools.flag=RGN_FLAG_HIDDEN;
  assert(region_azone_edge_poll(&area,&tools,false)); // Hidden T reveal remains.
  tools.flag=0; tools.overlap=false;
  assert(region_azone_edge_poll(&area,&tools,false)); // Ordinary dock unchanged.
  tools.overlap=true; area.spacetype=SPACE_PROPERTIES;
  assert(region_azone_edge_poll(&area,&tools,false));
  area.spacetype=SPACE_VIEW3D; tools.regiontype=RGN_TYPE_UI;
  assert(region_azone_edge_poll(&area,&tools,false)); // Visible N panel unchanged.
  tools.regiontype=RGN_TYPE_TOOL_PROPS;
  assert(!region_azone_edge_poll(&area,&tools,false)); // Drawer owns its own sash.
}
'''
    path = tmp_path / 'edge_policy.cc'
    path.write_text(program)
    executable = tmp_path / 'edge_policy'
    subprocess.run([compiler, '-std=c++17', str(path), '-o', str(executable)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
