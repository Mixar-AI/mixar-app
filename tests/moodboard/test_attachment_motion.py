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


def _run_native(tmp_path, body):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler required')
    source = tmp_path / 'flight.cc'
    source.write_text('#include "mixie_attachment_motion.hh"\n#include <cassert>\n#include <cstdio>\n'
                      'using namespace blender::ed::mixie;\n' + body)
    binary = tmp_path / 'flight'
    subprocess.run([compiler, '-std=c++17', '-I', str(ROOT/'src/source/blender/editors/space_mixie'),
                    str(source), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)


def test_native_flight_endpoints_and_bounded_ribbon(tmp_path):
    _run_native(tmp_path, r"""
static float cross(FlightPoint a, FlightPoint b, FlightPoint c) {
  return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]);
}
static float len(FlightPoint a, FlightPoint b) { return std::hypot(b[0]-a[0], b[1]-a[1]); }
int main() {
  const FlightQuad source{{{1180,180},{1420,180},{1420,340},{1180,340}}};
  // Up-left (the composer above a card once folded the sheet flat), left,
  // right, straight down and down-left into the pill.
  const FlightQuad targets[5] = {
      {{{470,796},{566,796},{566,860},{470,860}}}, {{{470,416},{566,416},{566,480},{470,480}}},
      {{{2000,200},{2096,200},{2096,264},{2000,264}}}, {{{1289,-400},{1311,-400},{1311,-385},{1289,-385}}},
      {{{789,-300},{811,-300},{811,-285},{789,-285}}}};
  const int N = ATTACHMENT_FLIGHT_GRID;
  for (const FlightQuad &target : targets) {
    for (FlightLanding landing : {FlightLanding::Handoff, FlightLanding::Dissolve}) {
      const FlightPath path = attachment_flight_path(source, target, landing);
      const float bow = std::hypot(path.bow[0], path.bow[1]);
      assert(bow <= ATTACHMENT_FLIGHT_BOW_MAX + .001f);
      float lo[2] = {1e9f, 1e9f}, hi[2] = {-1e9f, -1e9f};
      for (const FlightQuad *q : {&source, &target}) {
        for (const FlightPoint &c : *q) {
          for (int a = 0; a < 2; a++) { lo[a] = std::min(lo[a], c[a]); hi[a] = std::max(hi[a], c[a]); }
        }
      }
      for (int j = 0; j <= N; j++) {
        for (int i = 0; i <= N; i++) {
          const float x = float(i)/N, y = float(j)/N;
          // Exact source and destination poses; missed frames clamp to landing.
          const FlightPoint a = flight_quad_point(source, x, y), b = flight_quad_point(target, x, y);
          const FlightPoint first = attachment_flight_vertex(path, x, y, 0);
          assert(std::abs(first[0]-a[0]) < .01f && std::abs(first[1]-a[1]) < .01f);
          assert(attachment_flight_vertex(path, x, y, 1) == b);
          assert(attachment_flight_vertex(path, x, y, 2) == b);
          for (int frame = 0; frame <= 120; frame++) {
            const FlightPoint p = attachment_flight_vertex(path, x, y, frame/120.0f);
            for (int k = 0; k < 2; k++) {
              assert(std::isfinite(p[k]) && p[k] >= lo[k]-bow-.01f && p[k] <= hi[k]+bow+.01f);
            }
          }
        }
      }
      // The corner facing the destination lands first; the far one pours in last.
      float landed = 0, pouring = 1;
      for (float x : {0.f, 1.f}) {
        for (float y : {0.f, 1.f}) {
          const float t = attachment_flight_point_progress(path, x, y, 1.0f - ATTACHMENT_FLIGHT_LAG);
          landed = std::max(landed, t);
          pouring = std::min(pouring, t);
        }
      }
      assert(std::abs(landed - 1.0f) < 1e-4f && pouring < 0.999f);
      for (int frame = 0; frame <= 120; frame++) {
        const float t = frame/120.0f;
        // Never folds or crushes: every cell keeps its winding, and the sheet
        // keeps at least half the area its own edge lengths span.
        float area = 0, w = 0, h = 0;
        for (int j = 0; j < N; j++) {
          for (int i = 0; i < N; i++) {
            const auto p00 = attachment_flight_vertex(path, float(i)/N, float(j)/N, t);
            const auto p10 = attachment_flight_vertex(path, float(i+1)/N, float(j)/N, t);
            const auto p11 = attachment_flight_vertex(path, float(i+1)/N, float(j+1)/N, t);
            const auto p01 = attachment_flight_vertex(path, float(i)/N, float(j+1)/N, t);
            assert(cross(p00, p10, p11) > 0 && cross(p00, p11, p01) > 0);
            area += (cross(p00, p10, p11) + cross(p00, p11, p01)) / 2;
          }
        }
        for (int k = 0; k <= 8; k++) {
          const float c = k/8.0f;
          w += len(attachment_flight_vertex(path, 0, c, t), attachment_flight_vertex(path, 1, c, t)) / 9;
          h += len(attachment_flight_vertex(path, c, 0, t), attachment_flight_vertex(path, c, 1, t)) / 9;
        }
        assert(area > 0.5f * w * h);
        const float alpha = attachment_flight_alpha(path, t);
        assert(alpha >= 0 && alpha <= 1);
      }
      if (landing == FlightLanding::Handoff) {
        // Opaque through the held landing pose; the thumbnail takes over.
        assert(attachment_flight_alpha(path, 0) == 1 && attachment_flight_alpha(path, 1.2f) == 1);
      }
      else {
        assert(attachment_flight_alpha(path, 0) == 1 && attachment_flight_alpha(path, 1) == 0);
      }
    }
  }
  // Straight vertical travel does not bow; sideways travel arcs upward.
  assert(attachment_flight_path(source, targets[3], FlightLanding::Dissolve).bow[0] == 0);
  assert(attachment_flight_path(source, targets[1], FlightLanding::Handoff).bow[1] > 0);
  // Down-left leads with the bottom-left corner, up-left with the top-left.
  const FlightPath pill = attachment_flight_path(source, targets[4], FlightLanding::Dissolve);
  assert(attachment_flight_point_progress(pill, 0, 0, .4f) > attachment_flight_point_progress(pill, 1, 1, .4f));
  const FlightPath above = attachment_flight_path(source, targets[0], FlightLanding::Handoff);
  assert(attachment_flight_point_progress(above, 0, 1, .4f) > attachment_flight_point_progress(above, 1, 0, .4f));
  // Easing: exact ends, monotonic, still at rest on arrival.
  float previous = 0;
  for (int i = 0; i <= 1000; i++) {
    const float e = flight_ease(i/1000.0f);
    assert(e >= previous - 1e-6f);
    previous = e;
  }
  assert(flight_ease(0) == 0 && std::abs(flight_ease(1) - 1) < 1e-6f);
  assert(flight_ease(1) - flight_ease(.99f) < .001f);
  // Aspect-fit like the thumbnail painter: wide fills width, tall fills height.
  const FlightQuad wide = flight_fit_quad(160.0f/240.0f, 0, 96, 0, 96);
  assert(std::abs(wide[1][0]-wide[0][0] - 96) < .001f && std::abs(wide[3][1]-wide[0][1] - 64) < .001f);
  assert(std::abs(wide[0][1] - 16) < .001f);
  const FlightQuad tall = flight_fit_quad(2.0f, 0, 96, 0, 96);
  assert(std::abs(tall[2][1]-tall[1][1] - 96) < .001f && std::abs(tall[1][0]-tall[0][0] - 48) < .001f);
  assert(std::abs(flight_quad_aspect(source) - 160.0f/240.0f) < 1e-5f);
}
""")


def test_composer_hands_the_picture_over_on_landing():
    flight = (ROOT/'src/source/blender/editors/space_mixie/mixie_attachment_flight.cc').read_text()
    painter = (ROOT/'src/source/blender/editors/space_agent_bubble/agent_bubble_references.cc').read_text()
    # The slot is published before painting and stays empty while inbound.
    assert painter.index('ED_moodboard_attachment_target(C, region, path.c_str(), image, g.view)') < \
        painter.index('ED_moodboard_attachment_arriving(') < painter.index('footer_thumbnails_draw_image(\n')
    assert 'if (!arriving &&' in painter
    # Landed ribbons hold their final pose until the tick retires them, and the
    # retire repaints the island in the same pass -- no frame shows neither.
    assert 'std::min(t, 1.0f)' in flight and 't >= 2.0f' in flight
    assert 'redraw_destination(f);' in flight
    assert 'f.landing = FlightLanding::Handoff;' in flight
    assert 'f.landing = FlightLanding::Dissolve;' in flight
    assert 'attachment_flight_path(f.source, f.target, f.landing)' in flight


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
