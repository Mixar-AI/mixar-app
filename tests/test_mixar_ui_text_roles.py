# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compile the production text-role resolver independently of Blender."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_roles_preserve_hierarchy_and_scale_exactly_once(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('A C++ compiler is required')
    source = tmp_path / 'text_roles.cc'
    source.write_text(r'''
#include "UI_mixar_text.hh"
#include <cassert>
#include <initializer_list>
#include <type_traits>
using namespace blender::ui;
static_assert(!std::is_convertible_v<MixarTextStyle, float>);
int main() {
  using R = MixarTextRole;
  const R roles[] = {R::Body, R::Caption, R::Heading, R::Prompt, R::ListTitle, R::ListMeta};
  // Existing visual contract: migrating roles must not silently resize text.
  const float expected[] = {18, 15, 25, 24, 23, 19};
  for (int i = 0; i < 6; i++) {
    for (float unit : {0.5f, 1.0f, 1.5f, 2.0f}) {
      const auto resolved = mixar_text_style(roles[i], unit);
      assert(resolved.size == expected[i] * unit);
      const auto copy = resolved;
      assert(copy.size == resolved.size);
    }
  }
  assert(mixar_text_role_size(R::Heading) > mixar_text_role_size(R::Body));
  assert(mixar_text_role_size(R::Body) > mixar_text_role_size(R::Caption));
  assert(mixar_text_role_size(R::ListTitle) > mixar_text_role_size(R::Body));
  assert(mixar_text_role_size(R::ListMeta) > mixar_text_role_size(R::Caption));
}
''')
    binary = tmp_path / 'text_roles'
    subprocess.run([compiler, '-std=c++17', '-I', str(ROOT/'src/source/blender/editors/include'),
                    str(source), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)
