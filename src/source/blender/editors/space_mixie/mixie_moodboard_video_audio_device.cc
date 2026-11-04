/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The audio device moodboard movies play on, and its idle close.
 */

#include "mixie_moodboard_video_audio_device.hh"

#ifdef WITH_AUDASPACE

#  include "BKE_sound.hh"

#  include "BLI_string.h"
#  include "BLI_timer.h"

#  include "DNA_userdef_types.h"

#  include <Exception.h>
#  include <devices/DeviceManager.h>
#  include <devices/IDevice.h>
#  include <devices/IDeviceFactory.h>

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Audio device
 *
 * Blender opens its own device only while the scene plays (and closes it 30 s
 * after), so the device manager usually has none while the board is idle.
 * Movies therefore play on a device of their own, opened from the same
 * user-preference device and specs on the first play and closed once nothing
 * has sounded for a while. JACK / PulseAudio / PipeWire keep Blender's device
 * open for good and are shared instead of opening a second client.
 * \{ */

static std::shared_ptr<aud::IDevice> g_audio_device;
static constexpr double AUDIO_DEVICE_IDLE_CLOSE_SECONDS = 30.0;
static char g_audio_close_identity;

static const char *audio_device_name()
{
  char **names = BKE_sound_get_device_names();
  const char *name = names ? names[0] : nullptr;
  for (int i = 0; names && names[i]; i++) {
    if (i == U.audiodevice) {
      name = names[i];
    }
  }
  return name;
}

std::shared_ptr<aud::IDevice> audio_device_ensure()
{
  if (g_audio_device) {
    return g_audio_device;
  }
  const char *name = audio_device_name();
  if (name && STR_ELEM(name, "JACK", "PulseAudio", "PipeWire")) {
    return aud::DeviceManager::getDevice();
  }
  try {
    std::shared_ptr<aud::IDeviceFactory> factory =
        name ? aud::DeviceManager::getDeviceFactory(name) : nullptr;
    if (!factory) {
      factory = aud::DeviceManager::getDefaultDeviceFactory();
    }
    if (!factory) {
      return nullptr;
    }
    aud::DeviceSpecs specs;
    specs.channels = aud::Channels(U.audiochannels);
    specs.format = aud::SampleFormat(U.audioformat);
    specs.rate = U.audiorate;
    if (specs.rate < double(aud::RATE_8000)) {
      specs.rate = aud::RATE_48000;
    }
    if (specs.format <= aud::FORMAT_INVALID) {
      specs.format = aud::FORMAT_S16;
    }
    if (specs.channels <= aud::CHANNELS_INVALID) {
      specs.channels = aud::CHANNELS_STEREO;
    }
    factory->setName("Mixar Moodboard");
    factory->setBufferSize(U.mixbufsize < 128 ? 1024 : U.mixbufsize);
    factory->setSpecs(specs);
    /* Never DeviceManager::setDevice(): that slot belongs to Blender. */
    g_audio_device = factory->openDevice();
  }
  catch (aud::Exception &) {
    g_audio_device.reset();
  }
  return g_audio_device;
}

static double audio_device_close_tick(uintptr_t /*uuid*/, void * /*user_data*/)
{
  if (!video_sessions_any_audio_handle()) {
    g_audio_device.reset();
  }
  return -1.0;
}

void audio_device_schedule_close()
{
  const uintptr_t id = uintptr_t(&g_audio_close_identity);
  BLI_timer_unregister(id);
  if (g_audio_device) {
    BLI_timer_register(
        id, audio_device_close_tick, nullptr, nullptr, AUDIO_DEVICE_IDLE_CLOSE_SECONDS, true);
  }
}

void audio_device_close()
{
  BLI_timer_unregister(uintptr_t(&g_audio_close_identity));
  g_audio_device.reset();
}

/** \} */

}  // namespace blender::ed::mixie

#endif /* WITH_AUDASPACE */
