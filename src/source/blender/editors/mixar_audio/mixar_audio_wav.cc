/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edmixaraudio
 *
 * Writes captured PCM as a plain 16-bit WAV.
 *
 * Forty-four bytes of header and a `fwrite` — which is why miniaudio's own
 * encoder is compiled out. The one thing that matters here is that the header
 * is COMPLETE before the file is handed on: the backend measures the clip's
 * duration from `data`'s size over `fmt `'s byte rate, and that measurement is
 * what the user is billed on. A streaming writer that leaves the size field at
 * zero (the usual shortcut when you cannot seek back) would present every
 * recording as zero seconds long.
 */

#include <cstdio>
#include <cstring>

#include "BKE_appdir.hh"

#include "BLI_fileops.h"
#include "BLI_path_utils.hh"
#include "BLI_string.h"
#include "BLI_time.h"

#include "ED_mixar_audio.hh"

#include "mixar_audio_intern.hh"

namespace {

void write_u32_le(unsigned char *out, uint32_t value)
{
  out[0] = (unsigned char)(value & 0xFF);
  out[1] = (unsigned char)((value >> 8) & 0xFF);
  out[2] = (unsigned char)((value >> 16) & 0xFF);
  out[3] = (unsigned char)((value >> 24) & 0xFF);
}

void write_u16_le(unsigned char *out, uint16_t value)
{
  out[0] = (unsigned char)(value & 0xFF);
  out[1] = (unsigned char)((value >> 8) & 0xFF);
}

}  // namespace

bool mixar_audio_write_wav(const int16_t *samples,
                           size_t sample_count,
                           char *r_filepath,
                           int filepath_maxlen,
                           char *r_error,
                           int error_maxlen)
{
  if (samples == nullptr || sample_count == 0) {
    BLI_strncpy(r_error, "No audio was captured", size_t(error_maxlen));
    return false;
  }

  const char *tempdir = BKE_tempdir_session();
  if (tempdir == nullptr || tempdir[0] == '\0') {
    BLI_strncpy(r_error, "No temporary folder is available", size_t(error_maxlen));
    return false;
  }

  /* The session temp dir is cleaned up with the process, and the timestamp
   * keeps two recordings in one session from colliding. */
  char filename[64];
  BLI_snprintf(filename,
               sizeof(filename),
               "mixar_voice_%llu.wav",
               (unsigned long long)(BLI_time_now_seconds() * 1000.0));
  char filepath[FILE_MAX];
  BLI_path_join(filepath, sizeof(filepath), tempdir, filename);

  const uint32_t data_bytes = uint32_t(sample_count * sizeof(int16_t));
  const uint32_t sample_rate = uint32_t(MIXAR_AUDIO_SAMPLE_RATE);
  const uint16_t channels = uint16_t(MIXAR_AUDIO_CHANNELS);
  const uint16_t bits = 16;
  const uint16_t block_align = uint16_t(channels * bits / 8);
  const uint32_t byte_rate = sample_rate * block_align;

  unsigned char header[44];
  memcpy(header + 0, "RIFF", 4);
  /* Everything after this field: 4 ("WAVE") + 24 (fmt chunk) + 8 (data
   * header) + the samples. */
  write_u32_le(header + 4, 36 + data_bytes);
  memcpy(header + 8, "WAVE", 4);
  memcpy(header + 12, "fmt ", 4);
  write_u32_le(header + 16, 16);  /* PCM fmt chunk size */
  write_u16_le(header + 20, 1);   /* WAVE_FORMAT_PCM */
  write_u16_le(header + 22, channels);
  write_u32_le(header + 24, sample_rate);
  write_u32_le(header + 28, byte_rate);
  write_u16_le(header + 32, block_align);
  write_u16_le(header + 34, bits);
  memcpy(header + 36, "data", 4);
  write_u32_le(header + 40, data_bytes);

  FILE *file = BLI_fopen(filepath, "wb");
  if (file == nullptr) {
    BLI_strncpy(r_error, "Could not write the recording to disk", size_t(error_maxlen));
    return false;
  }

  bool ok = fwrite(header, 1, sizeof(header), file) == sizeof(header);
  if (ok) {
    ok = fwrite(samples, 1, data_bytes, file) == size_t(data_bytes);
  }
  /* A short write leaves a header that promises more audio than the file
   * holds, which the backend would read as a longer (and pricier) clip — so
   * the partial file is removed rather than handed on. */
  if (fclose(file) != 0) {
    ok = false;
  }
  if (!ok) {
    BLI_delete(filepath, false, false);
    BLI_strncpy(r_error, "The recording could not be saved", size_t(error_maxlen));
    return false;
  }

  BLI_strncpy(r_filepath, filepath, size_t(filepath_maxlen));
  return true;
}
