# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the production schedule against the production continuous poses."""

from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_quiet_poses_skip_subpixel_frames_without_skipping_blinks(tmp_path):
    source = tmp_path/'cadence.cc'
    source.write_text(r'''
#include "agent_ui_cat_cadence.hh"
#include <cassert>
#include <iostream>
using namespace blender;
int main() {
  for(float pixels : {34.f,70.f,142.f}) {
    for(auto activity : {MixieCatActivity::Idle, MixieCatActivity::Waiting,
                        MixieCatActivity::Offline, MixieCatActivity::Listening}) {
      MixieCatMotion motion;
      motion.sample(0,activity);
      double t=0, max_sleep=0;
      int frames=0, blink_frames=0;
      while(t<90) {
        const double delay=mixie_cat_next_frame(motion,t,pixels);
        assert(delay>=1.0/60.0-1e-8 && delay<=0.5);
        if(delay>1.0/60.0+1e-8) {
          for(double dt=1.0/240;dt<delay;dt+=1.0/240) {
            const float error=mixie_cat_pose_displacement(motion.at(t),motion.at(t+dt))*pixels;
            assert(error<0.26f);
          }
        }
        if(motion.at(t).openness<.10f) blink_frames++;
        max_sleep=std::max(max_sleep,delay);
        t+=delay; frames++;
      }
      assert(frames/90.0<30); // Never a permanent60Hz resting loop, even at4×.
      assert(max_sleep>=.15 && blink_frames>=8); // Sleeps AND catches closed eyes.
      std::cout<<pixels<<":"<<int(activity)<<" "<<frames/90.0<<"fps maxsleep="<<max_sleep<<"\n";
    }
  }
  MixieCatMotion motion;
  motion.sample(0,MixieCatActivity::Idle);
  motion.sample(1,MixieCatActivity::Waiting);
  assert(mixie_cat_next_frame(motion,1.1,70)==MIXIE_CAT_FRAME_SECONDS);
  for(auto mode : {MixieCatActivity::Thinking, MixieCatActivity::Working,
                  MixieCatActivity::Reading, MixieCatActivity::Generating,
                  MixieCatActivity::Responding, MixieCatActivity::Connecting}) {
    motion.sample(10,mode);
    assert(mixie_cat_next_frame(motion,20,70)==MIXIE_CAT_FRAME_SECONDS);
  }
}
''')
    binary = tmp_path/'cadence'
    subprocess.run([shutil.which('c++'), '-std=c++17', '-I',
                    str(ROOT/'src/source/blender/editors/space_agent_bubble'),
                    str(source), '-o', str(binary)], check=True, capture_output=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr


def test_only_native_one_shot_scheduler_owns_mascot_redraws():
    base = ROOT/'src/source/blender/editors/space_agent_bubble'
    scheduler = (base/'agent_ui_cat_scheduler.cc').read_text()
    hover = (ROOT/'src/scripts/mixar/modules/agent_bubble/ui/operators/hover_ops.py').read_text()
    space = (base/'space_agent_bubble.cc').read_text()
    assert '_animation_tick' not in hover and 'bubble_animation_tick' not in space
    assert 'ED_area_tag_redraw' not in scheduler
    callback = scheduler.split('double redraw_once(',1)[1].split('void arm(',1)[0]
    assert 'return -1.0;' in callback
    assert callback.index('live_region(') < callback.index('ED_region_tag_redraw(')
    assert 'agent_ui_cat_scheduler_window_freed(ghostwin)' in space
    assert 'agent_ui_cat_scheduler_forget(region)' in (base/'agent_ui_motion.cc').read_text()
