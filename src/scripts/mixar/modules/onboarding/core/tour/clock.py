# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the single time source.

The runner never reads the wall clock for video time; it asks a clock for
``position_ms()`` and drives it with ``pause``/``resume``/``seek_ms``.

* ``AudClock`` wraps an audaspace playback handle, so the narration's own
  playback position *is* the tour time — video frames and beats can never
  drift from the voice.
* ``WallClock`` is the silent fallback (audio device unavailable, CI): a
  monotonic timer with the same interface.

Both start **paused at 0**; the runner calls ``resume()``.

Rate changes on the audio clock rebuild the sound through rubberband
(``timeStretchPitchScale``) so speech keeps its pitch; the handle then
reports positions in the stretched output domain and ``position_ms``
maps them back to source time (``output * rate``). Without rubberband the
clock falls back to ``handle.pitch`` (faster and higher).

``position_ms`` never runs backwards except across an explicit seek: the
last reported value is the floor, and while paused it is frozen.
"""

import os
import time
from typing import Optional

from mixar.config.logging_config import get_logger

from . import config

logger = get_logger(__name__)

_TRUTHY = ("1", "true", "yes", "on")


def _now() -> float:
    # Looked up at call time so tests can monkeypatch ``time.monotonic``.
    return time.monotonic()


class BaseClock:
    """The interface the runner drives (see ``runner.Clock``)."""

    rate: float = 1.0
    paused: bool = True
    duration_ms: Optional[int] = None

    def __init__(self, duration_ms: Optional[int] = None, rate: float = 1.0):
        self.duration_ms = int(duration_ms) if duration_ms is not None else None
        self.rate = float(rate) if rate and rate > 0 else 1.0
        self.paused = True
        self._last_ms = 0

    # -- helpers ---------------------------------------------------------

    def _clamp(self, ms: int) -> int:
        """Apply the monotonic floor and the duration ceiling."""
        ms = max(int(ms), self._last_ms)
        if self.duration_ms is not None:
            ms = min(ms, self.duration_ms)
        self._last_ms = ms
        return ms

    # -- interface -------------------------------------------------------

    def position_ms(self) -> int:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def resume(self) -> None:
        raise NotImplementedError

    def seek_ms(self, ms: int) -> None:
        raise NotImplementedError

    def set_rate(self, rate: float) -> None:
        raise NotImplementedError

    def ended(self) -> bool:
        if self.duration_ms is None:
            return False
        return self.position_ms() >= self.duration_ms

    def close(self) -> None:
        pass


class WallClock(BaseClock):
    """Silent clock: monotonic time scaled by ``rate``."""

    def __init__(self, duration_ms: Optional[int] = None, rate: float = 1.0):
        super().__init__(duration_ms, rate)
        self._base_ms = 0.0     # logical position when the timer last (re)started
        self._t0 = _now()       # wall time of that restart

    def _raw_ms(self) -> float:
        if self.paused:
            return self._base_ms
        return self._base_ms + (_now() - self._t0) * 1000.0 * self.rate

    def position_ms(self) -> int:
        return self._clamp(int(self._raw_ms()))

    def pause(self) -> None:
        if self.paused:
            return
        self._base_ms = self._raw_ms()
        self.paused = True

    def resume(self) -> None:
        if not self.paused:
            return
        self._t0 = _now()
        self.paused = False

    def seek_ms(self, ms: int) -> None:
        ms = max(0, int(ms))
        self._base_ms = float(ms)
        self._t0 = _now()
        self._last_ms = ms

    def set_rate(self, rate: float) -> None:
        if not rate or rate <= 0:
            return
        self._base_ms = self._raw_ms()
        self._t0 = _now()
        self.rate = float(rate)


class AudClock(BaseClock):
    """Audio-backed clock: the playback handle is the time source.

    Raises ``RuntimeError`` from ``__init__`` when playback cannot start so
    ``make_clock`` can fall back to the wall clock.
    """

    def __init__(self, path: str, duration_ms: Optional[int] = None,
                 rate: float = 1.0):
        super().__init__(duration_ms, 1.0)
        self.path = path
        self._stretched = False
        self._handle = None
        try:
            import aud
        except ImportError as exc:
            raise RuntimeError(f"aud module unavailable: {exc}") from exc
        self._aud = aud
        try:
            self._device = aud.Device()
            self._source = aud.Sound(path)
        except Exception as exc:  # aud raises aud.error (an Exception subclass)
            raise RuntimeError(f"audio init failed for {path!r}: {exc}") from exc
        if self.duration_ms is None:
            self.duration_ms = self._source_duration_ms()
        self._start(0, rate)
        if self._handle is None:
            raise RuntimeError(f"audio playback could not start for {path!r}")

    # -- internals -------------------------------------------------------

    def _source_duration_ms(self) -> Optional[int]:
        try:
            samples = int(self._source.length)
            sample_rate = float(self._source.specs[0])
            if samples > 0 and sample_rate > 0:
                return int(round(samples / sample_rate * 1000.0))
        except Exception as exc:
            logger.debug("AudClock: source length unavailable: %s", exc)
        return None

    def _sound_for_rate(self, rate: float):
        """A Sound playing at ``rate``; sets ``_stretched`` accordingly."""
        self._stretched = False
        if abs(rate - 1.0) < 1e-6:
            return self._source
        stretch = getattr(self._source, "timeStretchPitchScale", None)
        if stretch is not None:
            try:
                snd = stretch(time_stretch=1.0 / rate, pitch_scale=1.0)
                self._stretched = True
                return snd
            except Exception as exc:
                logger.warning("AudClock: time-stretch unavailable (%s); "
                               "falling back to pitch", exc)
        return self._source

    def _to_handle_seconds(self, source_ms: int) -> float:
        seconds = max(0, int(source_ms)) / 1000.0
        return seconds / self.rate if self._stretched else seconds

    def _from_handle_seconds(self, seconds: float) -> int:
        seconds = float(seconds)
        if self._stretched:
            seconds *= self.rate
        return int(seconds * 1000.0)

    def _start(self, source_ms: int, rate: float) -> None:
        """(Re)create the handle at ``source_ms``, paused."""
        self._stop_handle()
        self.rate = float(rate) if rate and rate > 0 else 1.0
        snd = self._sound_for_rate(self.rate)
        try:
            # keep=True: a finished handle stays paused at its end and can
            # still be seeked; close() must stop() it.
            handle = self._device.play(snd, keep=True)
            handle.pause()
            if not self._stretched and abs(self.rate - 1.0) >= 1e-6:
                handle.pitch = self.rate
            if source_ms > 0:
                handle.position = self._to_handle_seconds(source_ms)
        except Exception as exc:
            logger.warning("AudClock: playback failed: %s", exc)
            self._handle = None
            return
        self._handle = handle
        self.paused = True
        self._last_ms = max(0, int(source_ms))

    def _stop_handle(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.stop()
        except Exception as exc:
            logger.debug("AudClock: stop failed: %s", exc)

    def _handle_alive(self) -> bool:
        # ``Handle.status`` is a bool in Blender's bindings: True while
        # playing or paused, False once the handle is invalid.
        try:
            return self._handle is not None and bool(self._handle.status)
        except Exception:
            return False

    # -- interface -------------------------------------------------------

    def position_ms(self) -> int:
        if self.paused or not self._handle_alive():
            return self._clamp(self._last_ms)
        try:
            ms = self._from_handle_seconds(self._handle.position)
        except Exception as exc:
            logger.debug("AudClock: position read failed: %s", exc)
            ms = self._last_ms
        return self._clamp(ms)

    def pause(self) -> None:
        if self.paused:
            return
        # Snapshot before flipping the flag so the frozen value is current.
        self.position_ms()
        self.paused = True
        if self._handle_alive():
            try:
                self._handle.pause()
            except Exception as exc:
                logger.debug("AudClock: pause failed: %s", exc)

    def resume(self) -> None:
        if not self.paused:
            return
        if not self._handle_alive():
            # The handle died (device reset, keep=False path): rebuild it at
            # the last known position so the tour keeps going.
            self._start(self._last_ms, self.rate)
            if self._handle is None:
                return
        try:
            self._handle.resume()
        except Exception as exc:
            logger.debug("AudClock: resume failed: %s", exc)
            return
        self.paused = False

    def seek_ms(self, ms: int) -> None:
        ms = max(0, int(ms))
        if not self._handle_alive():
            was_paused = self.paused
            self._start(ms, self.rate)
            if not was_paused:
                self.resume()
            return
        try:
            self._handle.position = self._to_handle_seconds(ms)
        except Exception as exc:
            logger.debug("AudClock: seek failed (%s); restarting handle", exc)
            was_paused = self.paused
            self._start(ms, self.rate)
            if not was_paused:
                self.resume()
            return
        self._last_ms = ms

    def set_rate(self, rate: float) -> None:
        if not rate or rate <= 0 or abs(rate - self.rate) < 1e-6:
            return
        position = self.position_ms()
        was_paused = self.paused
        self._start(position, rate)
        if self._handle is None:
            return
        if not was_paused:
            self.resume()

    def ended(self) -> bool:
        if not self._handle_alive():
            return True
        if self.duration_ms is not None and self.position_ms() >= self.duration_ms:
            return True
        return False

    def close(self) -> None:
        self.paused = True
        self._stop_handle()


def _env_flag(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in _TRUTHY


def _env_rate(name: str) -> Optional[float]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; ignored", name, raw)
        return None
    if value <= 0:
        logger.warning("%s=%r must be positive; ignored", name, raw)
        return None
    return value


def make_clock(path: str, duration_ms: Optional[int], silent: bool = False,
               rate: float = 1.0) -> BaseClock:
    """Build the tour clock, paused at 0.

    ``config.ENV_SILENT`` and ``config.ENV_CLOCK_RATE`` override the
    arguments when set, so the QA harness can force a deterministic, fast
    wall clock without touching the caller.
    """
    env_silent = _env_flag(config.ENV_SILENT)
    if env_silent is not None:
        silent = env_silent
    env_rate = _env_rate(config.ENV_CLOCK_RATE)
    if env_rate is not None:
        rate = env_rate

    if not silent and path:
        try:
            return AudClock(path, duration_ms, rate=rate)
        except RuntimeError as exc:
            logger.warning("Tour audio clock unavailable, using wall clock: %s", exc)
    return WallClock(duration_ms, rate=rate)
