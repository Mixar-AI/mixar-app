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
         std::abs(a.bounce-b.bounce)+std::abs(a.eye_scale-b.eye_scale)+
         std::abs(a.eye_width-b.eye_width)+std::abs(a.lid_l-b.lid_l)+
         std::abs(a.lid_r-b.lid_r)+std::abs(a.pupil_width-b.pupil_width)+
         std::abs(a.smile-b.smile)+std::abs(a.ear_height_l-b.ear_height_l)+
         std::abs(a.ear_height_r-b.ear_height_r);
}
int main() {
  MixieCatSignals s;
  assert(mixie_cat_activity(s)==MixieCatActivity::Idle);
  s.thinking=s.reading=s.working=s.responding=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Idle); // Historical slots cannot stay busy.
  s.finishing=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Responding);
  s.finishing=false;
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
      assert(pose.eye_scale<=1.23 && std::abs(pose.bounce)<=.041);
      assert(std::abs(pose.tilt)<=27.01);
      energy+=distance(last,pose);last=pose;
    }
    assert(energy>1); // Even the quiet offline/waiting states keep a visible blink.
  }
  auto think=mixie_cat_activity_pose(1.2,MixieCatActivity::Thinking);
  auto work=mixie_cat_activity_pose(1.2,MixieCatActivity::Working);
  auto wait=mixie_cat_activity_pose(1.2,MixieCatActivity::Waiting);
  assert(think.look_y>0.3 && work.look_y<0 && wait.tilt>8);
  // Expression separation must survive a paused frame, not just phase offsets.
  for(int n=1;n<=240;n++) {
    const double t=n/60.0;
    auto reading=mixie_cat_activity_pose(t,MixieCatActivity::Reading);
    auto working=mixie_cat_activity_pose(t,MixieCatActivity::Working);
    auto thinking=mixie_cat_activity_pose(t,MixieCatActivity::Thinking);
    auto generating=mixie_cat_activity_pose(t,MixieCatActivity::Generating);
    auto responding=mixie_cat_activity_pose(t,MixieCatActivity::Responding);
    auto listening=mixie_cat_activity_pose(t,MixieCatActivity::Listening);
    assert(thinking.lid_r-thinking.lid_l>.5f);
    assert(responding.smile>=.85f && generating.smile==0);
    assert(listening.pupil_scale-generating.pupil_scale>.45f);
    assert(reading.eye_width>working.eye_width && working.look_x==0);
    if(reading.openness>.5f) assert(reading.openness-working.openness>.20f);
  }
  // All silhouette vertices stay inside the fixed chip, including transitions.
  // Painter uses 0.326 cheek radius, rounded ear corners and a -0.025 y offset.
  for(int mode=0;mode<=int(MixieCatActivity::Connecting);mode++) {
    for(int n=0;n<3600;n++) {
      auto p=mixie_cat_activity_pose(n/60.0,MixieCatActivity(mode));
      const float angle=(12+p.tilt)*3.14159265f/180;
      for(float side : {-1.f,1.f}) {
        float x=side*.285f, y=.375f*(side<0?p.ear_height_l:p.ear_height_r);
        const float tx=p.breathe*(x*std::cos(angle)-y*std::sin(angle));
        const float ty=p.breathe*(x*std::sin(angle)+y*std::cos(angle))+p.bounce-.025f;
        assert(std::abs(tx)<.49f && std::abs(ty)<.49f);
      }
    }
  }
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
