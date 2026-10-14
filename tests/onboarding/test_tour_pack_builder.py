# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The language-pack builder's pure decisions (``scripts/dev/tour_pack``):
subtitle cues kept off gated pauses, which silences count as pauses, and
where a gated line's voice really ends and the next one begins."""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dev" / "tour_pack"))

import pack_subtitles  # noqa: E402
import plan  # noqa: E402


def _seg(a, b):
    return SimpleNamespace(start_ms=a, end_ms=b)


def test_next_lines_cue_starting_before_a_gate_moves_to_the_next_beat():
    blocks = [[1000, 5000, ["gated line"]], [60522, 62422, ["next line"]]]
    out = pack_subtitles.gate_safe(blocks, [(60660, 60990)])
    assert [c[:2] for c in out] == [[1000, 5000], [60990, 62422]]


def test_gated_lines_cue_running_past_the_gate_ends_at_it():
    out = pack_subtitles.gate_safe([[58000, 60900, ["gated line"]]], [(60660, 60990)])
    assert [c[:2] for c in out] == [[58000, 60660]]


def test_cue_left_too_short_by_the_gate_is_dropped():
    out = pack_subtitles.gate_safe([[60500, 60700, ["blip"]]], [(60660, 60990)])
    assert out == []


def test_retime_writes_gate_safe_cues(tmp_path):
    src, dst = tmp_path / "in.srt", tmp_path / "out.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:03,000\nA\n\n2\n00:00:59,000 --> 00:01:02,000\nB\n")
    n = pack_subtitles.retime_srt(str(src), str(dst), lambda ms: ms + 500, [(60660, 60990)])
    assert n == 2
    assert pack_subtitles.read_srt_cues(str(dst)) == [(1500, 3500), (60990, 62500)]


def test_a_breath_inside_a_long_pause_does_not_split_it():
    """Only the pause after a gated line uses the fine segmentation; a
    60-200 ms breath elsewhere must not split a long pause into two halves
    that each escape the trim."""
    dub = SimpleNamespace(
        speech=[_seg(0, 1000), _seg(3000, 4000), _seg(6000, 7000)],
        fine=[_seg(0, 1000), _seg(1900, 2000), _seg(3000, 4000), _seg(4300, 5000),
              _seg(6000, 7000)])
    gaps = plan._pause_gaps(dub, start=0, until=7000, gate_ends={4000})
    assert gaps == [(1000, 3000), (4000, 4300)]


def test_gated_line_end_follows_the_voice_but_never_before_its_onset():
    dub = SimpleNamespace(fine=[_seg(1000, 2600), _seg(3000, 3200)])
    assert plan.Dub.spoken_end(dub, 2400) == 2600        # voice runs past the cue
    assert plan.Dub.spoken_end(dub, 3500) == 3200        # cue ends in a pause
    assert plan.Dub.spoken_end(dub, 3500, floor=3300) == 3500
    long_run = SimpleNamespace(fine=[_seg(1000, 9000)])
    assert plan.Dub.spoken_end(long_run, 2000) == 2000   # left for the silence report


def test_line_after_a_gate_starts_with_its_first_syllable():
    dub = SimpleNamespace(fine=[_seg(1000, 2000), _seg(2900, 4000)])
    assert plan.Dub.spoken_onset(dub, 3050, floor=2000) == 2900   # voice began early
    assert plan.Dub.spoken_onset(dub, 2500, floor=2000) == 2900   # cue starts in a pause
    assert plan.Dub.spoken_onset(dub, 1500, floor=1200) == 1500   # segment began before floor
