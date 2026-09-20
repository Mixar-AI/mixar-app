# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute the native ribbon geometry and selection-to-animation boundary."""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_native_flight_endpoints_and_bounded_ribbon(tmp_path):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler required')
    source = tmp_path / 'flight.cc'
    source.write_text(r'''
#include "mixie_attachment_motion.hh"
#include <cassert>
using namespace blender::ed::mixie;
int main() {
  FlightQuad source{{{600,400},{840,400},{840,560},{600,560}}};
  FlightQuad target{{{140,40},{172,40},{172,72},{140,72}}};
  for (int x=0; x<2; ++x) {
    for (int row=0; row<=32; ++row) {
      float y=float(row)/32;
      auto first=attachment_flight_vertex(source,target,x,y,0);
      auto last=attachment_flight_vertex(source,target,x,y,1);
      assert(std::abs(first[0]-(600+240*x))<.001f);
      assert(std::abs(first[1]-(400+160*y))<.001f);
      assert(std::abs(last[0]-(140+32*x))<.001f);
      assert(std::abs(last[1]-(40+32*y))<.001f);
      for (int frame=0; frame<=240; ++frame) {
        float t=float(frame)/240;
        auto p=attachment_flight_vertex(source,target,x,y,t);
        assert(std::isfinite(p[0]) && std::isfinite(p[1]));
        assert(p[0]>=140-.001 && p[0]<=840+.001);
        assert(p[1]>=40-.001 && p[1]<=632+.001);
        assert(attachment_flight_alpha(t)>=0 && attachment_flight_alpha(t)<=1);
      }
    }
  }
  // Bottom edge leads; the sheet visibly tapers instead of translating rigidly.
  auto left=attachment_flight_vertex(source,target,0,0,.5);
  auto right=attachment_flight_vertex(source,target,1,0,.5);
  auto top_left=attachment_flight_vertex(source,target,0,1,.5);
  auto top_right=attachment_flight_vertex(source,target,1,1,.5);
  assert(right[0]-left[0] < top_right[0]-top_left[0]);
  assert(attachment_flight_alpha(0)==1 && attachment_flight_alpha(1)==0);
  // Missed frames clamp to the final pose; no replay of intermediate frames.
  assert(attachment_flight_vertex(source,target,0,0,2)==target[0]);
}
''')
    binary = tmp_path / 'flight'
    subprocess.run([compiler, '-std=c++17', '-I', str(ROOT/'src/source/blender/editors/space_mixie'),
                    str(source), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)


class Attachments(list):
    def add(self):
        item = SimpleNamespace(image_path='', image_source='', is_moodboard=False)
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


def test_only_committed_new_attachments_animate(monkeypatch):
    from mixar.modules.moodboard.core import attachment_motion, chat_sync
    attachments = Attachments()
    scene = SimpleNamespace(mixie_chat_pending_attachments=attachments)
    animate = Mock()
    monkeypatch.setattr(attachment_motion, 'animate_attachments', animate)
    monkeypatch.setattr(chat_sync, '_redraw_chat_areas', lambda: None)
    monkeypatch.setattr(chat_sync, 'board_image_is_attached', lambda name, names, paths: name in names)
    chat_sync._reconcile_attachments(scene, ['b', 'a'], animate=True)
    animate.assert_called_once_with(scene, ['a', 'b'])
    animate.reset_mock()
    chat_sync._reconcile_attachments(scene, ['a', 'b'], animate=True)
    animate.assert_not_called()
    chat_sync._reconcile_attachments(scene, list('abcdefghijkl'), animate=True)
    animate.assert_called_once_with(scene, list('cdefghij'))
    assert len(attachments) == 10
    animate.reset_mock()
    chat_sync._reconcile_attachments(scene, [], animate=True)
    animate.assert_not_called()
    assert len(attachments) == 0


def test_load_and_attachment_drift_do_not_replay_motion(monkeypatch):
    from mixar.modules.moodboard.core import chat_sync
    scene = SimpleNamespace(name='motion scene')
    # Patch the module's binding: other suites install independent bpy stubs.
    monkeypatch.setattr(chat_sync, 'bpy', SimpleNamespace(context=SimpleNamespace(scene=scene)))
    monkeypatch.setattr(chat_sync, '_last_signatures', {})
    monkeypatch.setattr(chat_sync, '_ensure_graph_node_ids', lambda _: None)
    signature = [0, ('a',)]
    monkeypatch.setattr(chat_sync, '_compute_selection_signature', lambda _: tuple(signature))
    reconcile = Mock()
    monkeypatch.setattr(chat_sync, '_reconcile_attachments', reconcile)
    chat_sync._poll_tick()
    reconcile.assert_called_with(scene, ('a',), animate=False)
    signature[0] = 1
    chat_sync._poll_tick()
    reconcile.assert_called_with(scene, ('a',), animate=False)
    signature[1] = ('b',)
    chat_sync._poll_tick()
    reconcile.assert_called_with(scene, ('b',), animate=True)
    chat_sync._on_file_load_post()
    chat_sync._poll_tick()
    reconcile.assert_called_with(scene, ('b',), animate=False)
