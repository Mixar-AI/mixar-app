# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compile the actual Cocoa event repair with real NSEvent modifier snapshots.

The GHOST sink records events instead of driving a user's desktop. This covers
lost releases, genuinely held modifiers, two-window delivery and repeat input.
"""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
GHOST = ROOT / 'src/intern/ghost/intern'
COCOA = (GHOST / 'GHOST_SystemCocoa.mm').read_text()


def test_native_event_snapshot_recovers_screenshot_modifiers(tmp_path):
    if sys.platform != 'darwin':
        pytest.skip('Cocoa event snapshots require macOS')
    compiler = shutil.which('clang++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    start = COCOA.index('static bool mixar_cocoa_sync_modifiers(')
    end = COCOA.index('\nGHOST_TSuccess GHOST_SystemCocoa::handleMouseEvent', start)
    repair = COCOA[start:end]
    source = tmp_path / 'recovery.mm'
    source.write_text(r'''
#import <Cocoa/Cocoa.h>
#include <cassert>
#include <memory>
#include <vector>
#include "GHOST_MixarCocoaModifiers.hh"
struct GHOST_IWindow {};
enum GHOST_TEventType { GHOST_kEventKeyDown, GHOST_kEventKeyUp };
enum GHOST_TKey { GHOST_kKeyLeftShift, GHOST_kKeyLeftControl,
                  GHOST_kKeyLeftAlt, GHOST_kKeyLeftOS };
struct GHOST_EventKey {
  GHOST_TEventType type; GHOST_IWindow *window; GHOST_TKey key;
  GHOST_EventKey(double, GHOST_TEventType t, GHOST_IWindow *w, GHOST_TKey k, bool)
    : type(t), window(w), key(k) {}
};
struct GHOST_SystemCocoa {
  std::vector<std::unique_ptr<GHOST_EventKey>> events;
  void pushEvent(std::unique_ptr<GHOST_EventKey> e) { events.push_back(std::move(e)); }
};
''' + repair + r'''
int main() { @autoreleasepool {
  GHOST_SystemCocoa system;
  GHOST_IWindow chat, viewport;
  uint32_t stale = NSEventModifierFlagCommand | NSEventModifierFlagShift;
  NSEvent *move = [NSEvent mouseEventWithType:NSEventTypeMouseMoved
      location:NSMakePoint(30,40) modifierFlags:0 timestamp:1
      windowNumber:0 context:nil eventNumber:1 clickCount:0 pressure:0];
  assert(mixar_cocoa_sync_modifiers(system, &viewport, &chat, stale, move));
  assert(stale == 0 && system.events.size() == 4);
  for (int i=0; i<4; i++) {
    assert(system.events[i]->type == GHOST_kEventKeyUp);
    assert(system.events[i]->key == (i<2 ? GHOST_kKeyLeftShift : GHOST_kKeyLeftOS));
    assert(system.events[i]->window == (i%2 ? &chat : &viewport));
  }
  system.events.clear();
  assert(!mixar_cocoa_sync_modifiers(system, &viewport, &chat, stale, move));
  assert(system.events.empty()); // No repeated modifier events during a gesture.
  NSEvent *shift = [NSEvent mouseEventWithType:NSEventTypeMouseMoved
      location:NSMakePoint(30,40) modifierFlags:NSEventModifierFlagShift timestamp:2
      windowNumber:0 context:nil eventNumber:2 clickCount:0 pressure:0];
  assert(mixar_cocoa_sync_modifiers(system, &chat, &chat, stale, shift));
  assert(system.events.size() == 1); // Same target/key window never double-emits.
  assert(system.events[0]->type == GHOST_kEventKeyDown);
  system.events.clear();
  assert(!mixar_cocoa_sync_modifiers(system, &chat, &chat, stale, shift));
  assert(stale == NSEventModifierFlagShift); // Deliberately held Shift stays held.
  stale |= NSEventModifierFlagCommand;
  assert(mixar_cocoa_sync_modifiers(system, &chat, nullptr, stale, shift));
  assert(system.events.size() == 1 && system.events[0]->key == GHOST_kKeyLeftOS);
  assert(system.events[0]->type == GHOST_kEventKeyUp);
  return 0;
}}
''')
    binary = tmp_path / 'recovery'
    subprocess.run([compiler, '-std=c++17', '-framework', 'Cocoa', '-I', str(GHOST),
                    str(source), '-o', str(binary)], check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_mouse_and_keyboard_paths_recover_before_interpreting_input():
    for name in ('handleMouseEvent', 'handleKeyEvent'):
        body = COCOA.split('GHOST_TSuccess GHOST_SystemCocoa::' + name)[1]
        assert body.index('mixar_cocoa_sync_modifiers(') < body.index('switch (event.type)')
    assert 'cached = current;' in COCOA
