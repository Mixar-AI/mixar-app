<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Vendored: miniaudio

`miniaudio.h` — **v0.11.25 (2026-03-04)**, by David Reid
(<https://github.com/mackron/miniaudio>), dual-licensed **public domain
(Unlicense) or MIT-0**. The license text is at the end of the header itself;
nothing here requires attribution, and the file is unmodified.

## Why it is here

Blender bundles `aud` (audaspace), which is a **playback** library — it exposes
no microphone capture, and there is no ffmpeg binary in the app to shell out
to. Voice dictation therefore needs a capture backend of its own, and
miniaudio is one header that speaks WASAPI (Windows), Core Audio (macOS) and
ALSA/PulseAudio (Linux) with no build-time dependency on any of them: every
backend is loaded at runtime, so the app still links and runs on a machine
with no audio stack at all.

## Why it lives in this directory rather than `extern/`

Adding a top-level `extern/miniaudio` would mean overlaying upstream's
`extern/CMakeLists.txt` purely to `add_subdirectory` it. The header has
exactly one consumer — `bf_editor_mixar_audio`, next door — so it sits inside
that module and is reached by include path. Nothing else in the tree may
include it.

## How it is compiled

`miniaudio_impl.cc` is the single translation unit that defines
`MA_IMPLEMENTATION`. It first defines a wall of `MA_NO_*` macros to compile
**only** the device-capture path: no decoders, no encoders, no resource
manager, no node graph, no high-level engine. We record raw PCM and write our
own WAV header (`mixar_audio_wav.cc`), so miniaudio's own WAV encoder would be
dead weight.

## Updating it

Replace the file wholesale from upstream and re-read the `MA_NO_*` list in
`miniaudio_impl.cc` — new subsystems arrive with new opt-out macros, and one
that is missed is compiled in silently. Record the new version above.
