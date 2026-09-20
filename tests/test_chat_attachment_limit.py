# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Python and C++ chat attachment caps stay in lockstep; thumbnails wrap."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mixar.modules.space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE

ROOT = Path(__file__).resolve().parents[1]
FOOTER_CONSTANTS = (
    ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_footer_constants.hh"
)


def test_python_and_native_caps_are_ten():
    assert MAX_ATTACHMENTS_PER_MESSAGE == 10
    text = FOOTER_CONSTANTS.read_text(encoding="utf-8")
    match = re.search(r"#define FOOTER_MAX_ATTACHMENTS (\d+)", text)
    assert match and int(match.group(1)) == MAX_ATTACHMENTS_PER_MESSAGE
    assert "footer_attachment_columns" in text
    assert "footer_attachment_rows" in text


def test_native_thumbnail_wrap_fits_ten_in_a_narrow_footer(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    source = tmp_path / "wrap.cc"
    source.write_text(
        r"""
#include "mixie_chat_footer_constants.hh"
#include <cassert>
using namespace blender;
int main() {
  static_assert(FOOTER_MAX_ATTACHMENTS == 10);
  assert(footer_attachment_columns(264, 48, 6, 10) == 5);
  assert(footer_attachment_rows(10, 5) == 2);
  assert(footer_attachment_columns(534, 48, 6, 10) == 10);
  assert(footer_attachment_rows(10, 10) == 1);
  assert(footer_attachment_columns(40, 48, 6, 10) == 1);
  assert(footer_attachment_rows(10, 1) == 10);
  assert(footer_attachment_rows(0, 5) == 0);
  return 0;
}
"""
    )
    binary = tmp_path / "wrap"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-I",
            str(FOOTER_CONSTANTS.parent),
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True)
