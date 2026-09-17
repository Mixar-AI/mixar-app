# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for voice dictation (mic button -> transcript -> text field)."""

#: Backend catalog service. Frozen contract with the `speech_to_text` row the
#: seed migration writes; the model slug is NEVER hardcoded beside it — it is
#: resolved from the live catalog (see `core/transcription.py`).
SERVICE_KEY = "speech_to_text"

#: Capability key the catalog files that service under. Used only to ask the
#: catalog whether voice is published at all.
CAPABILITY_KEY = "voice"

#: Recorder states mirrored onto the WindowManager for the UI to draw.
STATE_IDLE = "IDLE"
STATE_RECORDING = "RECORDING"
STATE_TRANSCRIBING = "TRANSCRIBING"
STATE_ERROR = "ERROR"

#: Hard ceiling on one recording, in seconds. MUST stay at or below
#: `MIXAR_AUDIO_MAX_SECONDS` in `ED_mixar_audio.hh` — the C++ buffer simply
#: stops growing at its own cap, so a higher number here would show a clock
#: ticking past audio nobody is capturing.
MAX_RECORDING_SECONDS = 300

#: Below this, there is nothing to transcribe. The backend refuses shorter
#: clips outright (422); catching it here turns a mis-click into a quiet
#: "nothing recorded" instead of a round trip and an error toast.
MIN_RECORDING_SECONDS = 0.4

#: How often the session ticks while recording: advances the clock, samples
#: the level for the waveform, and enforces the ceiling. 20 fps is smooth for
#: a meter without repainting the whole editor on every frame.
RECORDING_TICK_S = 0.05

#: Poll interval for the transcription job. Wizper runs at ~250x real time, so
#: a voice note is usually done on the first or second poll; this is the
#: latency the user actually feels, which is why it is not the queue's 5 s
#: watchdog cadence.
POLL_INTERVAL_S = 0.6

#: Give up on a transcription after this long. Generous next to a job that
#: normally finishes in a second — it exists so a wedged job cannot leave the
#: mic button spinning forever, not to police the backend.
TRANSCRIBE_TIMEOUT_S = 90.0

#: How long an error or an empty-transcript notice stays on the button before
#: it returns to idle.
MESSAGE_TTL_S = 4.0

#: Target kinds. A target says WHERE the transcript goes and is captured when
#: recording STARTS — the audio belongs to the field the user was standing in,
#: not to whatever is focused when it finishes.
TARGET_CHAT = "chat"
TARGET_NODE_PREFIX = "node:"
TARGET_TAB_PREFIX = "tab:"

#: The chat composer's update callback treats this control character as
#: "Enter was pressed, send the message" (see the chat paste contract). A
#: transcript that happened to contain one would send itself mid-insert, so
#: every inserted string is stripped of it.
SUBMIT_MARKER = "\x1f"

#: Nothing was heard. Said plainly rather than raised as an error: the backend
#: reports silence as a SUCCESS with an empty transcript, and a user who did
#: not speak has not hit a failure.
EMPTY_TRANSCRIPT_MESSAGE = "Didn't catch that — try again"
