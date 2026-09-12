# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute native glass request caching independently of the compositor."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / 'src/source/blender/editors/space_agent_bubble'


def test_setup_is_deferred_cached_and_reset_on_window_recreation(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if compiler is None:
        pytest.skip('C++ compiler unavailable')
    source = tmp_path / 'lifecycle.cc'
    source.write_text(r'''
#include <cassert>
#include "agent_bubble_glass.hh"
using blender::AgentBubbleGlassState;
int main()
{
  AgentBubbleGlassState island, pill;
  int calls = 0;
  bool supported = true;
  int first, second;
  auto apply = [&](void *) { ++calls; return supported; };
  assert(!island.transparent);
  assert(!island.request(nullptr));
  assert(island.request(&first));
  assert(!island.transparent && calls == 0); // Request never calls the OS.
  assert(!island.request(&first)); // Repeated redraws cannot queue more work.
  assert(!island.apply(&second, apply)); // Another window's notifier is inert.
  assert(island.apply(&first, apply));
  assert(island.transparent && calls == 1);
  for (int frame = 0; frame < 100; ++frame) {
    assert(!island.request(&first));
    assert(!island.apply(&first, apply));
  }
  assert(calls == 1);
  supported = false;
  assert(pill.request(&second));
  assert(pill.apply(&second, apply));
  assert(!pill.transparent && island.transparent && calls == 2);
  for (int frame = 0; frame < 100; ++frame) {
    assert(!pill.request(&second));
    assert(!pill.apply(&second, apply));
  }
  assert(calls == 2); // Unsupported systems also stop requesting native setup.
  island.reset(&second); // Freeing an unrelated window leaves the latch intact.
  assert(island.transparent);
  island.reset(&first);
  assert(!island.transparent);
  assert(island.request(&first)); // A freed pointer may be reused.
  assert(island.apply(&first, apply));
  assert(!island.transparent && calls == 3); // No stale successful capability.
  island.reset(nullptr);
  assert(island.request(&second));
  island.reset(&second); // Close before the queued notifier arrives.
  assert(!island.apply(&second, apply) && calls == 3);
  supported = true;
  pill.reset(&second); // Explicit repair retries after delayed native setup.
  assert(pill.request(&second));
  assert(pill.apply(&second, apply));
  assert(pill.transparent && calls == 4);
}
''')
    binary = tmp_path / 'lifecycle'
    subprocess.run([compiler, '-std=c++17', '-I', str(EDITOR), str(source),
                    '-o', str(binary)], check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_close_and_free_invalidate_even_pending_native_requests():
    source = (EDITOR / 'space_agent_bubble.cc').read_text()
    for signature, reset in (
        ('void ED_agent_bubble_windows_closed()', 'agent_bubble_glass_reset();'),
        ('void ED_agent_bubble_window_freed(', 'agent_bubble_glass_reset(ghostwin);'),
    ):
        start = source.index(signature)
        body = source[start:source.index('\n}\n', start)]
        assert reset in body
