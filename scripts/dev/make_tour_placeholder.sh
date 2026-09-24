#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Render the interactive tour's placeholder video:
#
#   onboarding/assets/tour/founder_placeholder.mp4   1280x720, 24 fps, H.264 + AAC
#
# The demo image the tour drops onto the moodboard
# (``assets/tour/demo_concept.png``) is real artwork, committed as-is; this
# script never touches it.
#
# The video is one title card per beat (beat id + its time range) cut at the
# timestamps of ``core/tour/beats.py`` — the beat table is imported, so the
# placeholder can never drift from the script — with a short tone at the
# start of every beat so audio-driven timing is audible. The founder
# recording replaces this file; only ``beats.py`` timings change.
#
# Title cards are rendered with Pillow and joined through ffmpeg's concat
# demuxer: the Homebrew ffmpeg is built without libfreetype, so ``drawtext``
# is unavailable.
#
# Usage: scripts/dev/make_tour_placeholder.sh   (from anywhere; needs ffmpeg + Pillow)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOUR_DIR="$REPO_ROOT/src/scripts/mixar/modules/onboarding/core/tour"
ASSET_DIR="$REPO_ROOT/src/scripts/mixar/modules/onboarding/assets/tour"
VIDEO_OUT="$ASSET_DIR/founder_placeholder.mp4"

FFMPEG="${FFMPEG:-/opt/homebrew/bin/ffmpeg}"
FFPROBE="${FFPROBE:-/opt/homebrew/bin/ffprobe}"
PYTHON="${PYTHON:-python3}"
FONT="${FONT:-/System/Library/Fonts/Supplemental/Arial.ttf}"

WIDTH=1280
HEIGHT=720
FPS=24
TONE_SECONDS=0.3
TONE_HZ=660

command -v "$FFMPEG" >/dev/null || { echo "ffmpeg not found at $FFMPEG" >&2; exit 1; }
command -v "$FFPROBE" >/dev/null || { echo "ffprobe not found at $FFPROBE" >&2; exit 1; }
"$PYTHON" -c "import PIL" 2>/dev/null || { echo "Pillow is required ($PYTHON -m pip install pillow)" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/tour_placeholder.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$ASSET_DIR"

# ---------------------------------------------------------------------------
# 1. Beat table → title cards + concat list + tone expression.
#
# ``beats.py`` only imports its sibling ``config.py``, but the package chain
# above it (``onboarding/core/__init__.py``) imports bpy, so the tour package
# is registered synthetically and imported on its own.
# ---------------------------------------------------------------------------
"$PYTHON" - "$TOUR_DIR" "$WORK" "$FONT" "$WIDTH" "$HEIGHT" "$TONE_SECONDS" "$TONE_HZ" <<'PY'
import importlib
import sys
import types

from PIL import Image, ImageDraw, ImageFont

tour_dir, work, font_path, width, height, tone_s, tone_hz = sys.argv[1:8]
width, height = int(width), int(height)

pkg = "mixar.modules.onboarding.core.tour"
parts = pkg.split(".")
for i in range(1, len(parts) + 1):
    name = ".".join(parts[:i])
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod
sys.modules[pkg].__path__ = [tour_dir]
beats_mod = importlib.import_module(pkg + ".beats")
tour = beats_mod.MIXAR_INTRO
beats = list(tour.beats)

# Every beat runs until the next one enters; the terminal beat until its clip end.
spans = []
for i, b in enumerate(beats):
    end = beats[i + 1].enter_ms if i + 1 < len(beats) else b.clip_end_ms
    spans.append((b, b.enter_ms, end))
total_ms = spans[-1][2]

big = ImageFont.truetype(font_path, 96)
mid = ImageFont.truetype(font_path, 44)
small = ImageFont.truetype(font_path, 26)


def centred(draw, text, font, cy, fill):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (right - left)) / 2 - left, cy - (bottom - top) / 2 - top),
              text, font=font, fill=fill)


def fmt(ms):
    return f"{ms / 1000:.1f}s"


lines = []
for idx, (b, start, end) in enumerate(spans):
    img = Image.new("RGB", (width, height), (23, 23, 28))
    draw = ImageDraw.Draw(img)
    # Progress bar along the bottom: where this beat sits in the tour.
    draw.rectangle((0, height - 10, width, height), fill=(45, 45, 52))
    draw.rectangle((width * start / total_ms, height - 10,
                    width * end / total_ms, height), fill=(255, 204, 64))
    centred(draw, b.id, big, height * 0.40, (245, 245, 247))
    centred(draw, f"{fmt(start)} – {fmt(end)}", mid, height * 0.56, (255, 204, 64))
    tag = f"beat {idx + 1}/{len(spans)}"
    if b.gate is not None:
        tag += f"  ·  gate: {b.gate.check}"
    centred(draw, tag, small, height * 0.68, (160, 162, 170))
    centred(draw, f"{tour.title} — placeholder video", small, height * 0.90, (110, 112, 120))
    path = f"{work}/card_{idx:02d}.png"
    img.save(path)
    lines.append(f"file '{path}'\nduration {(end - start) / 1000:.3f}")
# The concat demuxer needs the last file listed once more for its duration to apply.
lines.append(f"file '{work}/card_{len(spans) - 1:02d}.png'")
with open(f"{work}/cards.txt", "w") as fh:
    fh.write("\n".join(lines) + "\n")

# A soft tone at the start of every beat, over silence.
gates = "+".join(f"between(t,{start / 1000:.3f},{start / 1000 + float(tone_s):.3f})"
                 for _b, start, _end in spans)
expr = f"0.18*sin(2*PI*{tone_hz}*t)*({gates})"
with open(f"{work}/tone.txt", "w") as fh:
    fh.write(expr)
with open(f"{work}/duration.txt", "w") as fh:
    fh.write(f"{total_ms / 1000:.3f}")
print(f"{len(spans)} beats, {total_ms / 1000:.1f} s")
PY

DURATION="$(cat "$WORK/duration.txt")"
TONE_EXPR="$(cat "$WORK/tone.txt")"

# ---------------------------------------------------------------------------
# 2. Encode: title cards (concat demuxer) + generated tone track.
# ---------------------------------------------------------------------------
"$FFMPEG" -hide_banner -loglevel error -y \
    -f concat -safe 0 -i "$WORK/cards.txt" \
    -f lavfi -i "aevalsrc='${TONE_EXPR}':s=48000:c=mono:d=${DURATION}" \
    -map 0:v -map 1:a \
    -vf "fps=${FPS},format=yuv420p" \
    -c:v libx264 -preset veryfast -crf 30 -g 48 \
    -c:a aac -b:a 64k \
    -t "$DURATION" -movflags +faststart \
    "$VIDEO_OUT"

# ---------------------------------------------------------------------------
# 3. Verify.
# ---------------------------------------------------------------------------
echo "--- $VIDEO_OUT"
"$FFPROBE" -v error -show_entries format=duration,size \
    -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames \
    -of default=noprint_wrappers=1 "$VIDEO_OUT"
