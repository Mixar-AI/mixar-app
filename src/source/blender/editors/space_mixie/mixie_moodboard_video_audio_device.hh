/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The audio device moodboard movies play on (internal to the session store).
 */

#pragma once

#ifdef WITH_AUDASPACE

#  include <memory>

namespace aud {
class IDevice;
}  // namespace aud

namespace blender::ed::mixie {

/**
 * The device movies play on: opened on first use from the user's audio
 * preferences (Blender's own device for JACK / PulseAudio / PipeWire), or
 * nullptr when none can open.
 */
std::shared_ptr<aud::IDevice> audio_device_ensure();
/**
 * Close the device once nothing has sounded for a while. Re-armed by every
 * call: whenever a track stops, or a play left the device open with no track.
 */
void audio_device_schedule_close();
/** Close the device now. */
void audio_device_close();

/** Whether any session holds a device handle (defined by the session store). */
bool video_sessions_any_audio_handle();

}  // namespace blender::ed::mixie

#endif /* WITH_AUDASPACE */
