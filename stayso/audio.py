"""Microphone capture for push-to-talk.

Records 16 kHz mono float32 - exactly the format Whisper wants - so no
resampling happens between the mic and the model.
"""

import math
import threading
import time

import numpy as np
import sounddevice as sd

from .config import settings
from .events import bus

# The meter reads in decibels, because speech amplitude is logarithmic and a
# linear bar sits nearly flat until you shout. -60 dB is a silent room, -6 dB is
# close to clipping.
FLOOR_DB = -60.0
CEILING_DB = -6.0
METER_HZ = 15


class MicUnavailable(RuntimeError):
    pass


class Recorder:
    """Start on key-down, stop on key-up, hand back one numpy array."""

    def __init__(self, sample_rate=None, max_seconds=None):
        self.sample_rate = sample_rate or settings.sample_rate
        self.max_seconds = max_seconds or settings.max_recording_seconds
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()
        self._max_frames = int(self.sample_rate * self.max_seconds)
        self._frames_captured = 0
        self._last_meter = 0.0
        self.peak = 0.0

    @property
    def is_recording(self):
        return self._stream is not None

    @staticmethod
    def _level(block):
        """One audio block to a 0-1 meter reading."""
        rms = float(np.sqrt(np.mean(np.square(block))))
        db = 20.0 * math.log10(rms) if rms > 1e-9 else FLOOR_DB
        return min(1.0, max(0.0, (db - FLOOR_DB) / (CEILING_DB - FLOOR_DB)))

    def _callback(self, indata, frames, time_info, status):
        # `status` reports xruns; a dropped frame or two is not worth aborting a
        # command over, so we just keep collecting.
        with self._lock:
            if self._frames_captured >= self._max_frames:
                return
            self._frames.append(indata.copy())
            self._frames_captured += frames

        level = self._level(indata)
        self.peak = max(self.peak, level)

        # The callback runs hundreds of times a second; the meter only needs to
        # move as fast as an eye can follow.
        now = time.monotonic()
        if now - self._last_meter >= 1.0 / METER_HZ:
            self._last_meter = now
            bus.publish("level", level=round(level, 3), peak=round(self.peak, 3))

    def start(self):
        if self._stream is not None:
            return
        with self._lock:
            self._frames = []
            self._frames_captured = 0
        self.peak = 0.0
        self._last_meter = 0.0
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
                blocksize=0,
            )
            self._stream.start()
        except Exception as exc:  # sounddevice raises a family of errors
            self._stream = None
            raise MicUnavailable(str(exc)) from exc

    def stop(self):
        """Stop recording and return the audio, or None if it was too short."""
        stream, self._stream = self._stream, None
        if stream is None:
            return None
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

        with self._lock:
            frames = self._frames
            self._frames = []
            self._frames_captured = 0

        bus.publish("level", level=0.0, peak=round(self.peak, 3))

        if not frames:
            return None

        audio = np.concatenate(frames, axis=0).flatten().astype(np.float32)
        if len(audio) < self.sample_rate * settings.min_recording_seconds:
            return None
        return audio

    @staticmethod
    def list_devices():
        try:
            devices = sd.query_devices()
        except Exception as exc:
            raise MicUnavailable(str(exc)) from exc
        return [
            {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]
