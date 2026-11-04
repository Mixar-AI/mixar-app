# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the production rounded painter with and without the Windows guard."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/source/blender/editors/space_mixie_chat/mixie_chat_ui_rounded_rect.cc'

STUB = r'''
#pragma once
#include <cassert>
#include <vector>
using uint = unsigned int;
struct rctf { float xmin, xmax, ymin, ymax; };
inline float BLI_rctf_size_x(const rctf *r) { return r->xmax-r->xmin; }
inline float BLI_rctf_size_y(const rctf *r) { return r->ymax-r->ymin; }
inline void BLI_rctf_pad(rctf *r, float p, float q) {
  r->xmin-=p; r->xmax+=p; r->ymin-=q; r->ymax+=q;
}
enum GPUBlend { GPU_BLEND_NONE, GPU_BLEND_ALPHA, GPU_BLEND_ALPHA_PREMULT };
inline GPUBlend state=GPU_BLEND_NONE;
inline int blend_changes=0, draws=0;
inline std::vector<GPUBlend> drawn_states;
inline GPUBlend GPU_blend_get() { return state; }
inline void GPU_blend(GPUBlend s) { state=s; blend_changes++; }
struct GPUVertFormat {};
namespace blender::gpu { enum class VertAttrType { SFLOAT_32_32 }; }
inline GPUVertFormat *immVertexFormat() { static GPUVertFormat f; return &f; }
inline uint GPU_vertformat_attr_add(GPUVertFormat*,const char*,blender::gpu::VertAttrType) { return 0; }
constexpr int GPU_SHADER_3D_UNIFORM_COLOR=0, GPU_PRIM_LINE_STRIP=1, GPU_PRIM_TRI_FAN=2;
inline void immBindBuiltinProgram(int) {}
inline void immUniformColor4fv(const float*) {}
inline void GPU_line_width(float) {}
inline void immBegin(int,int) { draws++; drawn_states.push_back(state); }
inline void immVertex2f(uint,float,float) {}
inline void immRectf(uint,float,float,float,float) { draws++; drawn_states.push_back(state); }
inline void immEnd() {}
inline void immUnbindProgram() {}
'''

MAIN = r'''
int main() {
  rctf rect{0,100,0,60};
  for (GPUBlend initial : {GPU_BLEND_NONE,GPU_BLEND_ALPHA,GPU_BLEND_ALPHA_PREMULT}) {
    for (float alpha : {0.0f,0.3f,1.0f}) {
      for (bool outline : {false,true}) {
        state=initial; blend_changes=draws=0; drawn_states.clear();
        float color[4]={.1f,.2f,.3f,alpha};
        if (outline) blender::chat_ui_draw_rounded_rect_outline(&rect,8,color,1);
        else blender::chat_ui_draw_rounded_rect(&rect,8,color);
        assert(state==initial);
#ifdef WIN32
        assert(blend_changes==(alpha==0 ? 0 : 2));
        assert((draws==0)==(alpha==0));
        for(auto mode:drawn_states) assert(mode==GPU_BLEND_ALPHA);
#else
        // Preserve the existing macOS path, including zero-alpha draws and
        // caller-owned blending. This code is compiled with WIN32 undefined.
        assert(blend_changes==0);
        assert(draws==(outline ? 1 : 7));
        for(auto mode:drawn_states) assert(mode==initial);
#endif
      }
    }
  }
}
'''


@pytest.mark.parametrize('windows', [False, True], ids=['macos-path', 'windows-path'])
def test_platform_blending(tmp_path, windows):
    compiler = shutil.which('clang++') or shutil.which('c++')
    assert compiler, 'C++ compiler required for native painter regression'
    for name in ('BLI_rect.h', 'GPU_immediate.hh', 'GPU_state.hh'):
        (tmp_path / name).write_text('#include "stub.hh"\n', encoding='utf-8')
    (tmp_path / 'stub.hh').write_text(STUB, encoding='utf-8')
    source = tmp_path / 'probe.cc'
    source.write_text(SOURCE.read_text(encoding='utf-8') + MAIN, encoding='utf-8')
    binary = tmp_path / 'probe.exe'
    subprocess.run([compiler, '-std=c++17', '-I', str(tmp_path),
                    '-DWIN32' if windows else '-UWIN32', str(source),
                    '-o', str(binary)], check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True)
