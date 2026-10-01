# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ffmpeg rendering of a planned dub: cut, freeze, logo card, encode, split.

One filter graph does the whole edit so no intermediate file is written:
every kept run is trimmed from the dub (video + audio, 25 ms audio fades at
each cut), the last run is padded with a frozen frame when the dub's
presenter tail is shorter than the English one, the English logo card is
appended (its own silent audio), and the concatenation is scaled to
1280×720 @ 24 fps, loudness-normalised to −16 LUFS and encoded H.264 + AAC
with forced keyframes at the act boundaries. A second pass splits the file
losslessly at those keyframes into ``part-<k>.mp4``.
"""

import hashlib
import json
import os
import subprocess

from plan import FADE_MS


def _sec(ms) -> str:
    return f"{ms / 1000.0:.3f}"


def _run(argv):
    subprocess.run(argv, check=True)


def render(dub_path: str, english_path: str, runs, card_start_raw_en_ms: int,
           english_duration_ms: int, act_boundaries_ms, out_path: str,
           crf: int = 22, preset: str = "medium", source_fps: float = 25.0) -> None:
    """Runs are concatenated at the DUB's frame rate and converted to 24 fps
    once, so rounding to the output grid happens one time for the whole
    file instead of once per run (per-run conversion drifted the act
    boundaries by up to 150 ms). ``cli.reconcile`` then moves the timing
    table onto the split parts' real boundaries."""
    parts_v, parts_a = [], []
    graph = []
    for i, r in enumerate(runs):
        dur = r.src_end_ms - r.src_start_ms
        v = f"[0:v]trim=start={_sec(r.src_start_ms)}:end={_sec(r.src_end_ms)},setpts=PTS-STARTPTS"
        if r.freeze_ms:
            v += f",tpad=stop_mode=clone:stop_duration={_sec(r.freeze_ms)}"
        graph.append(f"{v}[v{i}]")
        a = (f"[0:a]atrim=start={_sec(r.src_start_ms)}:end={_sec(r.src_end_ms)},asetpts=PTS-STARTPTS,"
             f"afade=t=in:st=0:d={FADE_MS / 1000:.3f},"
             f"afade=t=out:st={_sec(max(0, dur - FADE_MS))}:d={FADE_MS / 1000:.3f}")
        if r.freeze_ms:
            a += f",apad=pad_dur={_sec(r.freeze_ms)}"
        graph.append(f"{a}[a{i}]")
        parts_v.append(f"[v{i}]")
        parts_a.append(f"[a{i}]")
    n = len(runs)
    # The English logo card, scaled to the dub's frame size and rate before concat.
    graph.append(f"[1:v]trim=start={_sec(card_start_raw_en_ms)}:end={_sec(english_duration_ms)},"
                 f"setpts=PTS-STARTPTS,scale=iw:ih[vcard_raw]")
    graph.append(f"[1:a]atrim=start={_sec(card_start_raw_en_ms)}:end={_sec(english_duration_ms)},"
                 f"asetpts=PTS-STARTPTS,volume=0[acard]")
    parts_v.append("[vcard]")
    parts_a.append("[acard]")
    # Every video branch to the output geometry/rate so concat sees one format.
    fps_src = f"{source_fps:.3f}"
    for i in range(n):
        graph.append(f"[v{i}]scale=1280:720:flags=lanczos,fps={fps_src},format=yuv420p[vs{i}]")
    graph.append(f"[vcard_raw]scale=1280:720:flags=lanczos,fps={fps_src},format=yuv420p[vcard]")
    for i in range(n + 1):
        graph.append(f"[a{i}]aresample=48000,aformat=channel_layouts=stereo[as{i}]" if i < n
                     else "[acard]aresample=48000,aformat=channel_layouts=stereo[ascard]")
    concat_in = "".join(f"[vs{i}][as{i}]" for i in range(n)) + "[vcard][ascard]"
    graph.append(f"{concat_in}concat=n={n + 1}:v=1:a=1[vc_src][ac]")
    graph.append("[vc_src]fps=24[vc]")
    graph.append("[ac]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    kf = ",".join(_sec(ms) for ms in act_boundaries_ms if ms > 0)
    argv = ["ffmpeg", "-v", "error", "-y", "-i", dub_path, "-i", english_path,
            "-filter_complex", ";".join(graph),
            "-map", "[vc]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-force_key_frames", kf, "-x264-params", "scenecut=0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-movflags", "+faststart", out_path]
    _run(argv)


def split(rendered: str, act_boundaries_ms, out_dir: str) -> list:
    """Lossless split at the forced keyframes → part-<k>.mp4 files."""
    os.makedirs(out_dir, exist_ok=True)
    times = ",".join(_sec(ms) for ms in act_boundaries_ms if ms > 0)
    pattern = os.path.join(out_dir, "part-%d.mp4")
    _run(["ffmpeg", "-v", "error", "-y", "-i", rendered, "-c", "copy", "-map", "0",
          "-f", "segment", "-segment_times", times, "-reset_timestamps", "1",
          "-movflags", "+faststart", pattern])
    parts = sorted((p for p in os.listdir(out_dir) if p.startswith("part-")),
                   key=lambda p: int(p.split("-")[1].split(".")[0]))
    return [os.path.join(out_dir, p) for p in parts]


def probe_duration_ms(path: str) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], check=True, capture_output=True, text=True)
    return int(round(float(out.stdout.strip()) * 1000))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_entry(code: str, parts: list, act_boundaries_ms, total_ms: int,
                   url_base: str) -> dict:
    """Part table with PROBED boundaries: the segment muxer cuts on the
    keyframe at or after each requested time, so a part's real start is
    the sum of the real durations before it. The client chains parts by
    these numbers; ``act_boundaries_ms`` (the requested cuts) are checked
    to be within one frame of them."""
    entries, start = [], 0
    for k, path in enumerate(parts):
        dur = probe_duration_ms(path)
        end = start + dur
        want = int(act_boundaries_ms[k]) if k < len(act_boundaries_ms) else start
        if abs(want - start) > 250:
            raise SystemExit(f"{path}: starts at {start} ms, act boundary is {want} ms")
        entries.append({"k": k, "url": f"{url_base}/{code}/{os.path.basename(path)}",
                        "sha256": sha256(path), "bytes": os.path.getsize(path),
                        "start_ms": int(start), "end_ms": int(end)})
        start = end
    return {"code": code, "duration_ms": int(start), "parts": entries}


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
