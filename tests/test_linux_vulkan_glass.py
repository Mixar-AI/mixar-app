# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the actual Linux window request block for both GPU backends."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_linux_agent_window_requests_rgba_on_both_backends(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    source = (ROOT/'src/source/blender/windowmanager/intern/wm_window.cc').read_text()
    begin = source.index('  GPUBackendType gpu_backend = GPU_backend_type_selection_get();',
                         source.index('static void wm_window_ghostwindow_add('))
    end = source.index('  gpu_settings.context_type =', begin)
    block = source[begin:end]
    program = r'''
#include <cassert>
#include <cstring>
#include <vector>
#define __linux__ 1
#define STREQ(a,b) (std::strcmp(a,b)==0)
constexpr int SPACE_AGENT_BUBBLE=1, GHOST_gpuTransparent=4;
enum GPUBackendType {GPU_BACKEND_OPENGL, GPU_BACKEND_VULKAN};
GPUBackendType selected;
GPUBackendType GPU_backend_type_selection_get(){return selected;}
const char *platform="X11";
const char *WM_ghost_backend(){return platform;}
struct ScrArea{int spacetype;};
struct bScreen{std::vector<ScrArea> areabase;};
struct Window{Window *parent; bScreen *screen;};
struct Settings{int flags=0;};
bScreen *WM_window_get_active_screen(Window *w){return w->screen;}
int decoration_requests=0;
void Mixar_GHOST_RequestNextWindowCustomDecoration(){++decoration_requests;}
Settings request(Window *win){Settings gpu_settings;
''' + block + r'''
return gpu_settings;}
int main(){
 bScreen agent{{{SPACE_AGENT_BUBBLE}}}, ordinary{{{2}}};
 Window parent{nullptr,&ordinary}, island{&parent,&agent};
 for(auto backend:{GPU_BACKEND_OPENGL,GPU_BACKEND_VULKAN}){
  selected=backend;decoration_requests=0;
  assert(request(&island).flags&GHOST_gpuTransparent);
  assert(decoration_requests==1);
  assert(request(&parent).flags==0);
  Window other{&parent,&ordinary};assert(request(&other).flags==0);
  Window orphan{nullptr,&agent};assert(request(&orphan).flags==0);
 }
 platform="WAYLAND";
 selected=GPU_BACKEND_VULKAN;assert(request(&island).flags==0);
 selected=GPU_BACKEND_OPENGL;assert(request(&island).flags&GHOST_gpuTransparent);
}
'''
    path = tmp_path/'request.cc'
    path.write_text(program)
    executable = tmp_path/'request'
    subprocess.run([compiler,'-std=c++17',str(path),'-o',str(executable)],
                   check=True,capture_output=True,text=True)
    subprocess.run([str(executable)],check=True,capture_output=True,text=True)
