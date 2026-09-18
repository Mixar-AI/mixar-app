/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edmixaraudio
 *
 * The process-wide microphone recorder behind `ED_mixar_audio.hh`.
 *
 * Shape of it: `record_start` opens a miniaudio capture device and allocates
 * the ENTIRE capture buffer up front; the audio callback then only ever
 * memcpy's into a pre-sized array and bumps an atomic counter. That is the
 * whole reason for the up-front allocation — an `alloc` (or a `vector` growth
 * memcpy) inside an audio callback is the classic source of dropouts, and the
 * bound also means a forgotten recording can never eat memory without limit.
 * At `MIXAR_AUDIO_MAX_SECONDS` the callback simply stops appending; the UI's
 * own timer sees the duration flatline and stops.
 *
 * What the audio thread may touch is exactly: `g_samples` (below its own
 * write cursor), `g_written`, `g_level`, `g_levels`/`g_levels_head`. It never
 * calls into Blender, never allocates, and never takes a lock that the main
 * thread holds for longer than a pointer swap.
 */

#include <atomic>
#include <cstdio>
#include <cstring>
#include <mutex>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"

#include "ED_mixar_audio.hh"

#include "mixar_audio_intern.hh"
#include "mixar_audio_miniaudio.hh"

/* Mixar 5.2 port: namespace wrap. Every include stays ABOVE this line -- a
 * header pulled in after it would land in `blender::blender`. */
namespace blender {

namespace {

/* Samples the buffer can hold — the hard ceiling from the public header. */
constexpr size_t capture_capacity()
{
  return size_t(MIXAR_AUDIO_SAMPLE_RATE) * size_t(MIXAR_AUDIO_CHANNELS) *
         size_t(MIXAR_AUDIO_MAX_SECONDS);
}

/* How fast the displayed level falls back toward the real peak. A raw
 * per-block peak flickers hard on speech; decaying toward it makes a meter
 * that reads as a voice rather than as noise. Attack is instant (a loud block
 * shows immediately); only the fall is smoothed. */
constexpr float LEVEL_DECAY = 0.80f;

/* The device is opened once and reused: on some backends opening an input
 * device is slow enough (and, on macOS, permission-prompting enough) to be
 * felt between a click and the first captured sample. */
ma_device g_device;
bool g_device_ready = false;

/* Guards device lifecycle against the reader helpers. Held only for the
 * moment it takes to swap the buffer pointer or flip `g_recording`; the audio
 * callback never waits on it. */
std::mutex g_lifecycle_mutex;

int16_t *g_samples = nullptr;
std::atomic<size_t> g_written{0};
std::atomic<bool> g_recording{false};

std::atomic<float> g_level{0.0f};
float g_levels[MIXAR_AUDIO_LEVEL_HISTORY] = {0.0f};
std::atomic<int> g_levels_head{0};
std::atomic<int> g_levels_count{0};

/* Peak of one captured block, 0..1. */
float block_peak(const int16_t *frames, ma_uint32 count)
{
  int32_t peak = 0;
  for (ma_uint32 i = 0; i < count; i++) {
    const int32_t magnitude = frames[i] < 0 ? -int32_t(frames[i]) : int32_t(frames[i]);
    if (magnitude > peak) {
      peak = magnitude;
    }
  }
  return float(peak) / 32768.0f;
}

/* AUDIO THREAD. No allocation, no Blender calls, no blocking. */
void capture_callback(ma_device * /*device*/,
                      void * /*output*/,
                      const void *input,
                      ma_uint32 frame_count)
{
  if (!g_recording.load(std::memory_order_acquire) || g_samples == nullptr ||
      input == nullptr || frame_count == 0)
  {
    return;
  }

  const int16_t *frames = static_cast<const int16_t *>(input);
  const size_t written = g_written.load(std::memory_order_relaxed);
  const size_t capacity = capture_capacity();
  /* Past the ceiling we drop the block rather than wrap: a ring buffer here
   * would silently hand back the LAST five minutes of a longer recording,
   * which is a worse answer than a recording that stopped growing and a UI
   * that says so. */
  if (written >= capacity) {
    return;
  }

  const size_t incoming = size_t(frame_count) * size_t(MIXAR_AUDIO_CHANNELS);
  const size_t room = capacity - written;
  const size_t take = incoming < room ? incoming : room;
  memcpy(g_samples + written, frames, take * sizeof(int16_t));
  /* Publish the new length only after the samples are in place, so a reader
   * can never see a length that covers bytes still being written. */
  g_written.store(written + take, std::memory_order_release);

  const float peak = block_peak(frames, ma_uint32(take));
  const float previous = g_level.load(std::memory_order_relaxed);
  g_level.store(peak > previous ? peak : previous * LEVEL_DECAY,
                std::memory_order_relaxed);

  const int head = g_levels_head.load(std::memory_order_relaxed);
  g_levels[head] = peak;
  g_levels_head.store((head + 1) % MIXAR_AUDIO_LEVEL_HISTORY, std::memory_order_release);
  const int count = g_levels_count.load(std::memory_order_relaxed);
  if (count < MIXAR_AUDIO_LEVEL_HISTORY) {
    g_levels_count.store(count + 1, std::memory_order_release);
  }
}

void reset_meters()
{
  g_level.store(0.0f, std::memory_order_relaxed);
  g_levels_head.store(0, std::memory_order_relaxed);
  g_levels_count.store(0, std::memory_order_relaxed);
  memset(g_levels, 0, sizeof(g_levels));
}

/* Tear the device down and free the buffer. Callers hold g_lifecycle_mutex. */
void teardown_locked()
{
  g_recording.store(false, std::memory_order_release);
  if (g_device_ready) {
    /* ma_device_uninit stops the device and JOINS its thread, so by the time
     * this returns no callback can still be running against `g_samples`. The
     * free below is only safe because of that ordering. */
    ma_device_uninit(&g_device);
    g_device_ready = false;
  }
  if (g_samples != nullptr) {
    /* 5.2: MEM_freeN is gone for a raw buffer; same port as mixie_chat_slots.cc. */
    MEM_delete_void(static_cast<void *>(g_samples));
    g_samples = nullptr;
  }
  g_written.store(0, std::memory_order_release);
  reset_meters();
}

void set_error(char *r_error, int error_maxlen, const char *message)
{
  if (r_error != nullptr && error_maxlen > 0) {
    BLI_strncpy(r_error, message, size_t(error_maxlen));
  }
}

}  // namespace

bool ED_mixar_audio_is_available()
{
  /* Every platform we build for has a miniaudio backend compiled in, and the
   * backends themselves are loaded at runtime — so availability is a build
   * fact, not a device fact. "No microphone plugged in" is a START failure
   * with its own message, deliberately NOT a reason to hide the button:
   * hiding it would leave a user who plugs a headset in with no way back. */
  return true;
}

bool ED_mixar_audio_record_start(char *r_error, int error_maxlen)
{
  if (g_recording.load(std::memory_order_acquire)) {
    return true;
  }

  std::lock_guard<std::mutex> lock(g_lifecycle_mutex);
  /* A previous session that failed halfway leaves state behind; start from a
   * known-idle recorder rather than trusting the last teardown. */
  teardown_locked();

  /* 5.2: MEM_callocN is gone; MEM_new_uninitialized is the sized raw-buffer
   * allocation (wm_event_system.cc, mixie_chat_slots.cc). Losing the zero-fill
   * is free here and slightly better: nothing ever reads past `g_written`, and
   * the WAV writer is handed exactly that many samples -- so the only thing
   * calloc bought was touching 9.6 MB of pages on the main thread between the
   * click and the first captured block. */
  g_samples = static_cast<int16_t *>(
      MEM_new_uninitialized(capture_capacity() * sizeof(int16_t), "mixar voice capture"));
  if (g_samples == nullptr) {
    set_error(r_error, error_maxlen, "Not enough memory to start recording");
    return false;
  }

  ma_device_config config = ma_device_config_init(ma_device_type_capture);
  config.capture.format = ma_format_s16;
  config.capture.channels = MIXAR_AUDIO_CHANNELS;
  config.sampleRate = MIXAR_AUDIO_SAMPLE_RATE;
  config.dataCallback = capture_callback;

  if (ma_device_init(nullptr, &config, &g_device) != MA_SUCCESS) {
    teardown_locked();
    /* One message for two causes we cannot tell apart here: every backend
     * reports "no default capture device" and "the OS refused access" the
     * same way. Naming both is more useful than guessing one. */
    set_error(r_error,
              error_maxlen,
              "No microphone is available. Check that one is connected and "
              "that Mixar is allowed to use it in your system settings.");
    return false;
  }
  g_device_ready = true;

  /* Arm the flag BEFORE starting the device: ma_device_start can deliver the
   * first block before it returns, and a callback that sees `g_recording`
   * false drops it. */
  g_recording.store(true, std::memory_order_release);
  if (ma_device_start(&g_device) != MA_SUCCESS) {
    teardown_locked();
    set_error(r_error, error_maxlen, "The microphone could not be started");
    return false;
  }
  return true;
}

bool ED_mixar_audio_record_stop(char *r_filepath,
                                int filepath_maxlen,
                                char *r_error,
                                int error_maxlen)
{
  std::lock_guard<std::mutex> lock(g_lifecycle_mutex);
  if (!g_device_ready && g_samples == nullptr) {
    set_error(r_error, error_maxlen, "Nothing was being recorded");
    return false;
  }

  /* Stop capturing first, then read the length: any block still in flight is
   * delivered (or dropped) before ma_device_uninit returns, so `written` can
   * only grow until this point and never after it. */
  g_recording.store(false, std::memory_order_release);
  if (g_device_ready) {
    ma_device_uninit(&g_device);
    g_device_ready = false;
  }

  const size_t written = g_written.load(std::memory_order_acquire);
  if (written == 0 || g_samples == nullptr) {
    teardown_locked();
    set_error(r_error, error_maxlen, "No audio was captured");
    return false;
  }

  char error[256] = "";
  const bool ok = mixar_audio_write_wav(
      g_samples, written, r_filepath, filepath_maxlen, error, sizeof(error));
  /* The buffer goes either way — a failed write must not leave nine megabytes
   * and a half-finished recording behind for the next start to inherit. */
  teardown_locked();
  if (!ok) {
    set_error(r_error, error_maxlen, error);
    return false;
  }
  return true;
}

void ED_mixar_audio_record_cancel()
{
  std::lock_guard<std::mutex> lock(g_lifecycle_mutex);
  teardown_locked();
}

bool ED_mixar_audio_is_recording()
{
  return g_recording.load(std::memory_order_acquire);
}

float ED_mixar_audio_level()
{
  if (!g_recording.load(std::memory_order_acquire)) {
    return 0.0f;
  }
  return g_level.load(std::memory_order_relaxed);
}

float ED_mixar_audio_duration()
{
  const size_t written = g_written.load(std::memory_order_acquire);
  if (written == 0) {
    return 0.0f;
  }
  return float(written) / float(MIXAR_AUDIO_SAMPLE_RATE * MIXAR_AUDIO_CHANNELS);
}

int ED_mixar_audio_levels(float *r_levels, int count)
{
  if (r_levels == nullptr || count <= 0) {
    return 0;
  }
  const int available = g_levels_count.load(std::memory_order_acquire);
  const int head = g_levels_head.load(std::memory_order_acquire);
  const int wanted = count < available ? count : available;
  /* Oldest first, so a waveform reads left to right in time. */
  for (int i = 0; i < wanted; i++) {
    const int index = ((head - wanted + i) % MIXAR_AUDIO_LEVEL_HISTORY +
                       MIXAR_AUDIO_LEVEL_HISTORY) %
                      MIXAR_AUDIO_LEVEL_HISTORY;
    r_levels[i] = g_levels[index];
  }
  return wanted;
}

void ED_mixar_audio_shutdown()
{
  ED_mixar_audio_record_cancel();
}

}  // namespace blender
