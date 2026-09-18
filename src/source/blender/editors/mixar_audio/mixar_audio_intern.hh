/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edmixaraudio
 *
 * Internal surface shared between the capture engine and the WAV writer.
 * Nothing outside `editors/mixar_audio` includes this.
 */

#pragma once

#include <cstddef>
#include <cstdint>

/* Mixar 5.2 port: namespace wrap, matching the definition in
 * `mixar_audio_wav.cc`. A prototype at global scope beside a
 * blender-scoped definition only fails at final link. */
namespace blender {

/** Write mono 16-bit PCM to a WAV in the session temp dir.
 *
 * `r_filepath` receives the path written. Returns false with `r_error` filled
 * on any failure — the caller frees the samples either way, so a failed write
 * must never leave the recorder holding a buffer.
 */
bool mixar_audio_write_wav(const int16_t *samples,
                           size_t sample_count,
                           char *r_filepath,
                           int filepath_maxlen,
                           char *r_error,
                           int error_maxlen);

}  // namespace blender
