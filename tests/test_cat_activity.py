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
#include "mixie_attachment_motion.hh"
#include <algorithm>
#include <cassert>
#include <cmath>
using namespace blender;
using blender::ed::mixie::ATTACHMENT_FLIGHT_SECONDS;
float distance(const MixieCatPose &a, const MixieCatPose &b) {
  return std::abs(a.tilt-b.tilt)+std::abs(a.look_x-b.look_x)+
         std::abs(a.breathe-b.breathe)+std::abs(a.ear_l-b.ear_l)+
         std::abs(a.ear_r-b.ear_r)+std::abs(a.pupil_scale-b.pupil_scale)+
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
  s.offline=false;
  s.catching=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Catching); // Reflex beats voice and work.
  s.offline=true;
  s.listening=s.waiting=false;
  assert(mixie_cat_activity(s)==MixieCatActivity::Offline);
  s.offline=s.catching=s.listening=s.waiting=false;
  s.thinking=true;
  assert(mixie_cat_activity(s)==MixieCatActivity::Thinking);
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
  for(int mode=0;mode<=int(MixieCatActivity::Catching);mode++) {
    float energy=0;
    auto last=mixie_cat_activity_pose(0,MixieCatActivity(mode));
    for(int n=1;n<=3600;n++) {
      const auto pose=mixie_cat_activity_pose(n/60.0,MixieCatActivity(mode));
      assert(std::isfinite(pose.tilt));
      assert(std::abs(pose.look_x)<=.86 && std::abs(pose.look_y)<=.66);
      assert(pose.openness>=.079 && pose.openness<=1.001);
      assert(pose.lid_l==pose.lid_r); // All activities blink with a balanced pair of eyes.
      assert(pose.eye_scale<=1.23 && std::abs(pose.bounce)<=.041);
      assert(std::abs(pose.tilt)<=27.01);
      energy+=distance(last,pose);last=pose;
    }
    assert(energy>1); // Even the quiet offline/waiting states keep a visible blink.
  }
  auto think=mixie_cat_activity_pose(1.2,MixieCatActivity::Thinking);
  auto wait=mixie_cat_activity_pose(1.2,MixieCatActivity::Waiting);
  assert(think.look_y>0.3 && std::abs(12+wait.tilt)<=8);
  float work_max_x=0, work_max_y=0, work_min_x=0, work_min_y=0;
  bool work_open_seen=false, work_blink_seen=false;
  for(int n=0;n<=int(MIXIE_ROLL_PERIOD*60);n++) {
    auto working=mixie_cat_activity_pose(n/60.0,MixieCatActivity::Working);
    work_max_x=std::max(work_max_x,working.look_x);
    work_min_x=std::min(work_min_x,working.look_x);
    work_max_y=std::max(work_max_y,working.look_y);
    work_min_y=std::min(work_min_y,working.look_y);
    if(working.openness>.9f) work_open_seen=true;
    if(working.openness<.15f) work_blink_seen=true;
    assert(working.bounce==0);
    assert(working.eye_width<1.08f);
  }
  assert(work_open_seen && work_blink_seen);
  assert(work_max_x>0.35f && work_min_x<-0.35f);
  assert(work_max_y>0.35f && work_min_y<-0.25f);
  // The paused orbit joins the resting gaze without a one-frame eye jump.
  for(int cycle=-2;cycle<=2;cycle++) {
    for(float phase : {MIXIE_ROLL_START, MIXIE_ROLL_START+MIXIE_ROLL_SPAN}) {
      const double t=(cycle+double(phase))*MIXIE_ROLL_PERIOD;
      const auto before=mixie_cat_eye_roll(t-1e-5);
      const auto after=mixie_cat_eye_roll(t+1e-5);
      assert(std::abs(before.look_x-after.look_x)<1e-4);
      assert(std::abs(before.look_y-after.look_y)<1e-4);
    }
  }
  // Expression separation must survive a paused frame, not just phase offsets.
  for(int n=1;n<=240;n++) {
    const double t=n/60.0;
    auto reading=mixie_cat_activity_pose(t,MixieCatActivity::Reading);
    auto working=mixie_cat_activity_pose(t,MixieCatActivity::Working);
    auto thinking=mixie_cat_activity_pose(t,MixieCatActivity::Thinking);
    auto generating=mixie_cat_activity_pose(t,MixieCatActivity::Generating);
    auto responding=mixie_cat_activity_pose(t,MixieCatActivity::Responding);
    auto listening=mixie_cat_activity_pose(t,MixieCatActivity::Listening);
    auto catching=mixie_cat_activity_pose(t,MixieCatActivity::Catching);
    assert(thinking.lid_l==1.0f && thinking.lid_r==1.0f);
    assert(std::abs(12+thinking.tilt)<=4.01f);
    assert(std::abs(catching.look_x)>.5f); // Default catch aims, it does not stare ahead.
    assert(responding.smile>=.85f && generating.smile==0);
    assert(listening.pupil_scale-generating.pupil_scale>.45f);
    assert(reading.eye_width>working.eye_width);
    assert(generating.pupil_width<working.pupil_width);
    if(reading.openness>.5f && working.openness>.5f)
      assert(working.openness-reading.openness>.20f);
  }
  // All silhouette vertices stay inside the fixed chip, including transitions.
  // Painter uses 0.326 cheek radius, rounded ear corners and a -0.025 y offset.
  for(int mode=0;mode<=int(MixieCatActivity::Catching);mode++) {
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
  float prog[]={0.4f,0.55f,1.1f};
  double arrive[]={10.0,9.4,8.0};
  assert(mixie_cat_catch_pick(prog,arrive,3)==1); // Soonest landing still in flight.
  auto left=mixie_cat_catch_aim(0.5f,0,100,200,100);
  auto right=mixie_cat_catch_aim(0.5f,400,100,200,100);
  auto up=mixie_cat_catch_aim(0.5f,200,300,200,100);
  assert(left.look_x<0 && right.look_x>0 && up.look_y>0);
  const double start=4.0;
  const float land=float((start+ATTACHMENT_FLIGHT_SECONDS-start)/ATTACHMENT_FLIGHT_SECONDS);
  assert(land==1.0f);
  MixieCatCatch early{0.20f,-0.70f,0.40f}, snap{land,-0.70f,0.40f};
  auto early_pose=mixie_cat_catch_pose(5,early);
  auto snap_pose=mixie_cat_catch_pose(5,snap);
  assert(snap_pose.bounce>early_pose.bounce+0.008f); // Reach, not a blink.
  assert(std::abs(snap_pose.look_x-early_pose.look_x)<1e-5);
  MixieCatMotion catcher;
  catcher.sample(1,MixieCatActivity::Thinking);
  auto held=catcher.sample(2,MixieCatActivity::Catching,snap);
  assert(distance(held,catcher.sample(2,MixieCatActivity::Catching,snap))<1e-5);
  catcher.sample(2.13,MixieCatActivity::Thinking);
  assert(distance(catcher.sample(3,MixieCatActivity::Thinking),
                  mixie_cat_activity_pose(3,MixieCatActivity::Thinking))<1e-5);
  // Losing the flight replaces catch input with defaults. Capture the outgoing
  // pose first, both at landing and when another activity interrupts the blend.
  const MixieCatCatch aimed{0.99f,0.80f,-0.50f};
  for(double elapsed : {0.13,0.68}) {
    for(auto next : {MixieCatActivity::Idle, MixieCatActivity::Thinking,
                     MixieCatActivity::Offline}) {
      MixieCatMotion motion;
      motion.sample(4,MixieCatActivity::Thinking);
      motion.sample(5,MixieCatActivity::Catching,early);
      const double now=5+elapsed;
      const auto outgoing=motion.sample(now,MixieCatActivity::Catching,aimed);
      assert(distance(outgoing,motion.sample(now,next))<1e-5);
      assert(distance(motion.sample(now+.13,next),
                      mixie_cat_blend(outgoing,mixie_cat_activity_pose(now+.13,next),.5f))<1e-5);
      assert(distance(motion.sample(now+.26,next),
                      mixie_cat_activity_pose(now+.26,next))<1e-5);
    }
  }
  // First-frame catches and same-activity tracking must consume the new aim.
  MixieCatMotion fresh;
  assert(distance(fresh.sample(6,MixieCatActivity::Catching,aimed),
                  mixie_cat_activity_pose(6,MixieCatActivity::Catching,aimed))<1e-5);
  assert(distance(fresh.sample(6.1,MixieCatActivity::Catching,snap),
                  mixie_cat_activity_pose(6.1,MixieCatActivity::Catching,snap))<1e-5);
  for(float lx : {-0.85f,0.0f,0.85f}) {
    for(float ly : {-0.65f,0.0f,0.65f}) {
      auto pose=mixie_cat_catch_pose(1.2,MixieCatCatch{1.0f,lx,ly});
      const float angle=(12+pose.tilt)*3.14159265f/180;
      for(float side : {-1.f,1.f}) {
        float x=side*.285f, y=.375f*(side<0?pose.ear_height_l:pose.ear_height_r);
        const float tx=pose.breathe*(x*std::cos(angle)-y*std::sin(angle));
        const float ty=pose.breathe*(x*std::sin(angle)+y*std::cos(angle))+pose.bounce-.025f;
        assert(std::abs(tx)<.49f && std::abs(ty)<.49f);
      }
    }
  }
}
''')
    binary = tmp_path/'cat'
    subprocess.run([compiler, '-std=c++17',
                    '-I', str(ROOT/'src/source/blender/editors/space_agent_bubble'),
                    '-I', str(ROOT/'src/source/blender/editors/space_mixie'),
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
    assert 'ED_moodboard_attachment_incoming' in state
    assert 'cat.catching = true' in state
    flight = (ROOT/'src/source/blender/editors/space_mixie'/'mixie_attachment_flight.cc').read_text()
    assert 'ED_moodboard_attachment_incoming' in flight
    assert 'ATTACHMENT_FLIGHT_SECONDS' in flight
    assert 'progress(f) > 1' in flight
    assert flight.count('BLI_timer_register(') == 1
