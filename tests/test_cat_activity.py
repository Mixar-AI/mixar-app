# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise production activity precedence and interrupted face transitions."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_activity_and_pose_contract(tmp_path):
    compiler = shutil.which('c++') or shutil.which('clang++')
    assert compiler
    source = tmp_path/'cat.cc'
    source.write_text(r'''
#include "agent_ui_cat_activity.hh"
#include <cassert>
#include <cmath>
using namespace blender;
float distance(const MixieCatPose &a, const MixieCatPose &b) {
  return std::abs(a.tilt-b.tilt)+std::abs(a.look_x-b.look_x)+
         std::abs(a.look_y-b.look_y)+std::abs(a.openness-b.openness)+
         std::abs(a.bounce-b.bounce)+std::abs(a.eye_scale-b.eye_scale);
}
int main() {
  MixieCatSignals s;
  assert(mixie_cat_activity(s)==MixieCatActivity::Idle);
  s.thinking=s.reading=s.working=s.responding=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Idle); // Historical slots cannot stay busy.
  s.generating=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Generating);
  s.busy=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Working);
  s.working=false;
  assert(mixie_cat_activity(s)==MixieCatActivity::Reading);
  s.reading=false;
  assert(mixie_cat_activity(s)==MixieCatActivity::Thinking);
  s.thinking=false;
  assert(mixie_cat_activity(s)==MixieCatActivity::Responding);
  s.offline=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Offline);
  s.waiting=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Waiting);
  assert(!mixie_cat_is_working(mixie_cat_activity(s)));
  s.listening=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Listening);
  MixieCatMotion a,b;
  a.sample(1, MixieCatActivity::Idle); b.sample(1, MixieCatActivity::Idle);
  a.sample(2, MixieCatActivity::Thinking); b.sample(2, MixieCatActivity::Thinking);
  for(int n=1;n<10;n++) a.sample(2+n*.01,MixieCatActivity::Thinking);
  assert(distance(a.at(2.10),b.at(2.10))<1e-5); // Same pose at any frame cadence.
  auto before=a.at(2.11);
  assert(distance(before,a.sample(2.11,MixieCatActivity::Working))<1e-5);
  before=a.at(2.16);
  assert(distance(before,a.sample(2.16,MixieCatActivity::Waiting))<1e-5);
  assert(distance(a.sample(20,MixieCatActivity::Waiting),
                  mixie_cat_activity_pose(20,MixieCatActivity::Waiting))<1e-5);
  for(int mode=0;mode<=int(MixieCatActivity::Connecting);mode++) {
    float energy=0;
    auto last=mixie_cat_activity_pose(0,MixieCatActivity(mode));
    for(int n=1;n<=3600;n++) {
      const auto pose=mixie_cat_activity_pose(n/60.0,MixieCatActivity(mode));
      assert(std::isfinite(pose.tilt));
      assert(std::abs(pose.look_x)<=.86 && std::abs(pose.look_y)<=.66);
      assert(pose.openness>=.079 && pose.openness<=1.001);
      assert(pose.eye_scale<=1.15 && std::abs(pose.bounce)<=.019);
      assert(std::abs(pose.tilt)<=12.01);
      energy+=distance(last,pose);last=pose;
    }
    assert(energy>10); // Every sustained activity remains alive.
  }
  auto think=mixie_cat_activity_pose(1.2,MixieCatActivity::Thinking);
  auto work=mixie_cat_activity_pose(1.2,MixieCatActivity::Working);
  auto wait=mixie_cat_activity_pose(1.2,MixieCatActivity::Waiting);
  assert(think.look_y>0.3 && work.look_y<0 && wait.tilt>8);
}
''')
    binary = tmp_path/'cat'
    subprocess.run([compiler, '-std=c++17', '-I', str(ROOT/'src/source/blender/editors/space_agent_bubble'),
                    str(source), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)


def test_activity_reads_live_native_slots_and_region_owns_transition():
    root = ROOT/'src/source/blender/editors/space_agent_bubble'
    state = (root/'agent_ui_state.cc').read_text()
    for prop in ('thinking_active', 'step_items', 'RUNNING', 'mixie_chat_voice_listening',
                 'AWAITING_INPUT', 'MODIFYING', 'mixie_queue'):
        assert prop in state
    assert 'cat.thinking = cat.reading = cat.working = cat.responding = false' in state
    motion = (root/'agent_ui_motion.cc').read_text()
    assert 'MixieCatMotion cat' in motion and 'motion.cat_scene != scene' in motion
    assert 'motion.cat = {}' in motion
