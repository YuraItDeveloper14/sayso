"""Microphone capture for push-to-talk.

Records 16 kHz mono float32 - exactly the format Whisper wants - so no
resampling happens between the mic and the model.
"""

import threading

import numpy as np
import sounddevice as sd

from .config import settings


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

    @property
    def is_recording(self):
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status):
        # `status` reports xruns; a dropped frame or two is not worth aborting a
        # command over, so we just keep collecting.
        with self._lock:
            if self._frames_captured >= self._max_frames:
                return
            self._frames.append(indata.copy())
            self._frames_captured += frames

    def start(self):
        if self._stream is not None:
            return
        with self._lock:
            self._frames = []
            self._frames_captured = 0
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
