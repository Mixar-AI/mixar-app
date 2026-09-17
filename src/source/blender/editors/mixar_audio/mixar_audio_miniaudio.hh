/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edmixaraudio
 *
 * The ONE place miniaudio is configured and included.
 *
 * Everything below is an opt-OUT: miniaudio compiles its whole world by
 * default, and all we want is "open the default input device and hand me
 * PCM". The decoders, encoders, generators, resource manager, node graph and
 * high-level engine are code we would ship and never call — we write our own
 * WAV header in `mixar_audio_wav.cc` precisely because the record path needs
 * no format machinery at all.
 *
 * Both translation units that touch miniaudio include THIS header rather than
 * the vendored one, because several of these macros change the declarations
 * as well as the implementation: configuring them in only one TU would compile
 * two different `ma_device` layouts into one binary.
 *
 * Re-read this list whenever `extern/miniaudio.h` is updated: a new subsystem
 * arrives with a new opt-out macro, and one that is missed gets compiled in
 * silently (see `extern/README.mixar.md`).
 */

#pragma once

/* No file format support — we neither read nor write audio files through
 * miniaudio. `MA_NO_WAV` is deliberate despite our output being a WAV. */
#define MA_NO_DECODING
#define MA_NO_ENCODING
#define MA_NO_WAV
#define MA_NO_FLAC
#define MA_NO_MP3

/* No synthesis (waveforms, noise) and none of the high-level playback stack. */
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#define MA_NO_ENGINE

/* Custom backends are an extension point we do not use. */
#define MA_NO_CUSTOM

#include "extern/miniaudio.h"
