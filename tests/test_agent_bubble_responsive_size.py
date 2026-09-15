# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute the production size policy against host and display constraints."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_logical_sizes_fit_host_and_preserve_manual_sizes(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    include = Path(__file__).resolve().parents[1] / 'src/source/blender/editors/space_agent_bubble'
    source = tmp_path / 'size.cc'
    source.write_text(r'''#include <cassert>
#include "agent_bubble_size.hh"
using namespace blender;
int main() {
  for (auto host : {AgentBubbleSize{1440,900}, {1920,1080}, {3840,2160}}) {
    auto normal = agent_bubble_fit_size({678,407},host);
    assert(normal.width == 678 && normal.height == 407);
    auto manual = agent_bubble_fit_size({760,480},host);
    assert(manual.width == 760 && manual.height == 480);
  }
  auto narrow = agent_bubble_fit_size({760,480},{620,650});
  assert(narrow.width == 572 && narrow.height == 480);
  for (int w=320;w<2000;w+=37) {
    for (int h=240;h<1200;h+=41) {
      auto size = agent_bubble_fit_size({760,700},{w,h});
      assert(size.width > 0 && size.height > 0);
      assert(size.width <= w-48 && size.height <= h-112);
      assert(size.width <= size.height*3); // composer remains drawable
      auto twice = agent_bubble_fit_size(size,{w,h});
      assert(twice.width == size.width && twice.height == size.height);
    }
  }
  auto missing = agent_bubble_fit_size({678,407},{0,0});
  assert(missing.width == 678 && missing.height == 407);
}
''')
    binary = tmp_path / 'size'
    subprocess.run([compiler, '-std=c++17', '-I', str(include), str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
