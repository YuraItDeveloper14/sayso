"""The noises Sayso makes.

Two jobs. The push-to-talk clicks tell you it is listening when the dashboard
is not on screen, which is most of the time - the app runs in the background.
The alarm keeps ringing when a timer comes due until somebody actually deals
with it, because a reminder you can miss is not a reminder.

Every sound is synthesised from sine waves at play time. No audio files ship
with the project, nothing is downloaded, and it works with the network off.
"""

import threading

import numpy as np
import sounddevice as sd

RATE = 44100
# Samples per write. Small enough that stopping feels instant (~25 ms), large
# enough not to underrun.
CHUNK = 1024


def tone(freq, ms, amplitude=0.2, fade_ms=7):
    """One note. The fades matter: a raw sine cut mid-cycle pops."""
    count = int(RATE * ms / 1000)
    t = np.arange(count) / RATE
    wave = np.sin(2 * np.pi * freq * t)

    envelope = np.ones(count)
    fade = min(int(RATE * fade_ms / 1000), count // 2)
    if fade > 0:
        envelope[:fade] = np.linspace(0, 1, fade)
        envelope[-fade:] = np.linspace(1, 0, fade)

    return (wave * envelope * amplitude).astype(np.float32)


def silence(ms):
    return np.zeros(int(RATE * ms / 1000), dtype=np.float32)


def sequence(*parts):
    return np.concatenate(parts)


# Push-to-talk: rising on key down, falling on key up. Kept short and quiet, so
# the tail cannot bleed into the recording that starts a few milliseconds later.
CLICK_ON = sequence(tone(760, 34, 0.16), tone(1180, 42, 0.16))
CLICK_OFF = sequence(tone(1180, 30, 0.13), tone(700, 38, 0.13))

# Timer alarm: a rising A minor arpeggio, then a gap. Bright enough to catch
# across a room, musical enough to hear ten times without hating it.
ALARM_PHRASE = sequence(
    tone(880, 130, 0.26),
    tone(1047, 130, 0.26),
    tone(1319, 200, 0.26),
    silence(620),
)


class Sounds:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self._alarm_stop = threading.Event()
        self._alarm_thread = None
        self._lock = threading.Lock()
        self._ringing = False
        self.alarm_label = ""

    @property
    def alarm_ringing(self):
        # An explicit flag, not thread liveness: the ringing thread sits inside
        # a blocking play call for up to a second after being told to stop, and
        # the dashboard should go quiet the instant you press the button.
        return self._ringing

    def _write(self, samples, stop_event=None):
        """Play samples on this thread's own stream.

        Deliberately not `sd.play`/`sd.stop`: those drive one shared stream, and
        aborting it from a different thread than the one blocked on it takes
        PortAudio down hard - it killed the whole process during testing.
        Writing in chunks and checking a flag between them means nothing ever
        reaches across threads.
        """
        if not self.enabled:
            return
        try:
            with sd.OutputStream(samplerate=RATE, channels=1, dtype="float32") as stream:
                for start in range(0, len(samples), CHUNK):
                    if stop_event is not None and stop_event.is_set():
                        return
                    stream.write(samples[start:start + CHUNK])
        except Exception:
            # No output device, or it is busy. Sound is never load-bearing.
            pass

    def _play_async(self, samples):
        threading.Thread(
            target=self._write, args=(samples,), daemon=True, name="sayso-click"
        ).start()

    def click_on(self):
        self._play_async(CLICK_ON)

    def click_off(self):
        self._play_async(CLICK_OFF)

    # ---------------------------------------------------------------- alarm

    def start_alarm(self, label=""):
        with self._lock:
            if self._ringing:
                return
            self._alarm_stop.clear()
            self._ringing = True
            self.alarm_label = label
            self._alarm_thread = threading.Thread(
                target=self._ring, daemon=True, name="sayso-alarm"
            )
            self._alarm_thread.start()

    def _ring(self):
        # Rings until dismissed, with a ceiling so a forgotten alarm does not
        # follow you around the building for the rest of the day.
        try:
            for _ in range(120):
                if self._alarm_stop.is_set():
                    break
                self._write(ALARM_PHRASE, self._alarm_stop)
        finally:
            with self._lock:
                self._ringing = False
                self.alarm_label = ""

    def stop_alarm(self):
        """Returns True if an alarm was actually ringing.

        Only sets a flag. The ringing thread notices between chunks, roughly
        every 25 ms, and closes its own stream.
        """
        with self._lock:
            if not self._ringing:
                return False
            self._ringing = False
            self.alarm_label = ""
        self._alarm_stop.set()
        return True


sounds = Sounds()
