# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build the onboarding tour's language packs.

    <embedded python> scripts/dev/tour_pack/cli.py --media ~/Work/tour-media \\
        --out dist/tour-packs --pack-version 2 [--languages french german] \\
        [--crop crop=1418:1064:11:8]

Inputs (never in the repo): ``<media>/raw/<english_name>.mp4`` for the raw
English take and every dub, ``<media>/srt/<english_name>.srt``. When the
dubs are cut from the same edit the app ships, ``raw/english.mp4`` is the
bundled ``founder.mp4`` itself (the cut list is then the identity). Work files
(mono WAVs, frame tracks) go to ``<media>/work``. Outputs:

    <out>/<pack_version>/<code>/part-<k>.mp4, timing.json, plan.json
    <out>/<pack_version>/manifest.json      (all languages built so far; the
                                             client reads this one, so upload
                                             the whole <pack_version>/ folder)
    <out>/manifest.json                     (the same, read back by the next build)
    src/scripts/mixar/modules/onboarding/assets/tour/subtitles/<code>.srt
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pack_subtitles  # noqa: E402
import plan  # noqa: E402
import render  # noqa: E402
import script_access  # noqa: E402
import warp as warp_mod  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
FOUNDER_MP4 = os.path.join(ROOT, "src/scripts/mixar/modules/onboarding/assets/tour/founder.mp4")
SUBTITLES_DIR = os.path.join(ROOT, "src/scripts/mixar/modules/onboarding/assets/tour/subtitles")
CDN_BASE = "https://cdn.mixar.app/tour-packs"

# code → media file stem (the language module's ``english`` names, lower-case)
LANGS = {"zh": "mandarin", "ko": "korean", "ja": "japanese", "ar": "arabic",
         "fr": "french", "de": "german", "es": "spanish", "it": "italian", "pt": "portuguese"}


def sh(argv):
    subprocess.run(argv, check=True)


def ensure_work(media: str) -> str:
    work = os.path.join(media, "work")
    os.makedirs(os.path.join(work, "wav"), exist_ok=True)
    os.makedirs(os.path.join(work, "frames"), exist_ok=True)
    return work


def wav_for(work: str, name: str, src: str) -> str:
    out = os.path.join(work, "wav", f"{name}.wav")
    if not os.path.isfile(out):
        sh(["ffmpeg", "-v", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", out])
    return out


def track_for(work: str, name: str, src: str, crop: str = "") -> str:
    # The crop is part of the cache key: a track cut with another crop
    # would align the warp on different frames.
    tag = "-" + re.sub(r"[^0-9a-z]+", "_", crop.lower()).strip("_") if crop else ""
    out = os.path.join(work, "frames", f"{name}{tag}.gray")
    if not os.path.isfile(out):
        pre = f"{crop}," if crop else ""
        sh(["ffmpeg", "-v", "error", "-y", "-i", src, "-an", "-vf",
            f"{pre}fps={warp_mod.FPS},scale={warp_mod.W}:{warp_mod.H}:flags=area,format=gray",
            "-f", "rawvideo", out])
    return out


def probe(src: str) -> tuple:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate:format=duration", "-of", "json", src],
                         check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    num, den = data["streams"][0]["r_frame_rate"].split("/")
    return float(num) / float(den), int(round(float(data["format"]["duration"]) * 1000))


def reconcile(timing: dict, planned: list, actual: list, tour) -> None:
    """Shift every beat time inside part k by (actual_k - planned_k), keeping
    the table monotonic; the shifts are a frame or two."""
    def shift(ms):
        if ms is None:
            return None
        k = max(i for i, b in enumerate(planned) if ms >= b) if ms >= planned[0] else 0
        return int(ms + actual[k] - planned[k])

    prev_end = 0
    for b in tour.beats:
        t = timing["beats"][b.id]
        enter = max(prev_end, shift(t["enter_ms"]))
        clip_end = max(enter + 200, shift(t["clip_end_ms"]))
        t["enter_ms"], t["clip_end_ms"] = enter, clip_end
        clampf = lambda v: None if v is None else max(enter, min(clip_end, shift(v)))
        t["actions"] = [clampf(a) for a in t["actions"]]
        for o in t["overlays"].values():
            for key in ("appear_ms", "disappear_ms", "click_ms"):
                o[key] = clampf(o[key])
            if "rows_ms" in o:
                o["rows_ms"] = [clampf(r) for r in o["rows_ms"]]
        prev_end = clip_end
    last = timing["beats"][tour.beats[-1].id]
    last["clip_end_ms"] = min(last["clip_end_ms"], timing["duration_ms"] - 50)


def build_language(code: str, media: str, out_root: str, pack_version: int, founder,
                   card_raw_en: int, english_mp4: str, english_dur: int, tour, work: str,
                   crf: int, preset: str, crop: str = "") -> dict:
    stem = LANGS[code]
    src = os.path.join(media, "raw", f"{stem}.mp4")
    fps, dur = probe(src)
    dub = plan.Dub(code, wav_for(work, stem, src), track_for(work, stem, src, crop),
                   track_for(work, "english", english_mp4), fps, dur)
    srt_src = os.path.join(media, "srt", f"{stem}.srt")
    if not os.path.isfile(srt_src):
        raise SystemExit(f"[{code}] {srt_src} is required: the cues are the dub's line structure")
    cues = pack_subtitles.read_srt_cues(srt_src)
    runs, fn, total, to_founder, lines = plan.plan_dub(tour, founder, dub, cues, card_raw_en)
    timing = plan.build_timing(tour, fn, total, code, pack_version)
    acts = plan.act_boundaries(tour, timing)
    timing["act_boundaries_ms"] = acts

    out_dir = os.path.join(out_root, str(pack_version), code)
    os.makedirs(out_dir, exist_ok=True)
    rendered = os.path.join(work, f"{code}-full.mp4")
    print(f"[{code}] warp cost {dub.warp_cost:.4f}, {len(runs)} runs, {total} ms; rendering…",
          flush=True)
    render.render(src, english_mp4, runs, card_raw_en, english_dur, acts, rendered,
                  crf=crf, preset=preset, source_fps=fps, crop=crop)
    real_total = render.probe_duration_ms(rendered)
    if abs(real_total - total) > 120:
        print(f"[{code}] WARNING rendered {real_total} ms vs planned {total} ms", flush=True)
    timing["duration_ms"] = real_total
    if timing["beats"][tour.beats[-1].id]["clip_end_ms"] > real_total - 50:
        timing["beats"][tour.beats[-1].id]["clip_end_ms"] = real_total - 50
    for p in os.listdir(out_dir):
        if p.startswith("part-"):
            os.remove(os.path.join(out_dir, p))
    parts = render.split(rendered, acts, out_dir)
    if len(parts) != len(acts):
        raise SystemExit(f"[{code}] expected {len(acts)} parts, got {len(parts)}")
    # The split lands on the keyframe at/after each boundary and the 24 fps
    # conversion rounds once: move the table onto the real part starts.
    actual = []
    start = 0
    for p in parts:
        actual.append(start)
        start += render.probe_duration_ms(p)
    reconcile(timing, acts, actual, tour)
    acts = actual
    timing["act_boundaries_ms"] = acts

    gates = plan.gate_silence_report(tour, timing, dub.db, runs, fps, card_raw_en)
    loud = [g for g in gates if g[2] is not None and g[2] > -40.0]
    if loud:
        print(f"[{code}] WARNING gate pause not silent: {loud}", flush=True)
    render.write_json(os.path.join(out_dir, "timing.json"), timing)
    render.write_json(os.path.join(out_dir, "plan.json"), {
        "runs": [vars(r) for r in runs], "lines": lines, "cues": cues,
        "cues_per_beat": [len(v) for v in plan.assign_cues(tour, founder, dub, cues).values()],
        "warp_cost": dub.warp_cost,
        "gates_peak_db": gates, "source_fps": fps, "source_duration_ms": dur})

    os.makedirs(SUBTITLES_DIR, exist_ok=True)
    n = pack_subtitles.retime_srt(srt_src, os.path.join(SUBTITLES_DIR, f"{code}.srt"),
                                  to_founder, pack_subtitles.gates_of(tour))
    print(f"[{code}] subtitles: {n} cues re-timed to the English edit", flush=True)

    entry = render.manifest_entry(code, parts, acts, real_total, f"{CDN_BASE}/{pack_version}")
    entry["script_hash"] = timing["script_hash"]
    entry["timing"] = {"url": f"{CDN_BASE}/{pack_version}/{code}/timing.json",
                       "sha256": render.sha256(os.path.join(out_dir, "timing.json"))}
    print(f"[{code}] done: {sum(p['bytes'] for p in entry['parts']) // 1024} KiB in "
          f"{len(parts)} parts", flush=True)
    return entry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "tour-packs"))
    ap.add_argument("--pack-version", type=int, default=1)
    ap.add_argument("--languages", nargs="*", default=sorted(LANGS))
    ap.add_argument("--crf", type=int, default=22)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--crop", default="",
                    help="ffmpeg crop filter applied to every dub before scaling, e.g. "
                         "crop=1418:1064:11:8 for the 1440x1080 takes' letterbox bars")
    args = ap.parse_args()

    media = os.path.expanduser(args.media)
    work = ensure_work(media)
    english_mp4 = os.path.join(media, "raw", "english.mp4")
    _fps, english_dur = probe(english_mp4)
    founder = plan.Founder(wav_for(work, "founder", FOUNDER_MP4), wav_for(work, "english", english_mp4))
    tour = script_access.load_tour()
    card_raw_en = plan.detect_card_start(track_for(work, "english", english_mp4),
                                         after_ms=int(founder.to_raw(tour.beats[-1].enter_ms)))
    if english_dur - card_raw_en < render.MIN_CARD_MS:
        card_raw_en = english_dur          # the take ends on the presenter: no card
        print(f"English: {len(founder.runs)} kept runs, no logo card", flush=True)
    else:
        print(f"English: {len(founder.runs)} kept runs, logo card from raw {card_raw_en} ms",
              flush=True)

    manifest_path = os.path.join(args.out, "manifest.json")
    manifest = {"pack_version": args.pack_version, "script_hash": plan.script_hash(tour),
                "languages": {}}
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            old = json.load(fh)
        if old.get("pack_version") == args.pack_version:
            manifest = old
    for lang in args.languages:
        code = lang if lang in LANGS else next((c for c, s in LANGS.items() if s == lang), None)
        if code is None:
            raise SystemExit(f"unknown language {lang!r}")
        manifest["languages"][code] = build_language(
            code, media, args.out, args.pack_version, founder, card_raw_en, english_mp4,
            english_dur, tour, work, args.crf, args.preset, args.crop)
        os.makedirs(args.out, exist_ok=True)
        render.write_json(manifest_path, manifest)
        # A copy inside the version folder makes that folder usable as the
        # client's cache stand-in (MIXAR_TOUR_PACK_DIR=<out>/<version>).
        render.write_json(os.path.join(args.out, str(args.pack_version), "manifest.json"), manifest)
    print(f"manifest: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
