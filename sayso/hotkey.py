"""Global push-to-talk hotkey.

Hold the combo to record, release to run. Matching is done on virtual key codes
rather than characters, because Windows reports Ctrl+S as the control character
\\x13 instead of "s".
"""

import threading

from pynput import keyboard

MODIFIER_KEYS = {
    "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "cmd": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
}


class PushToTalk:
    def __init__(self, modifiers, key, on_start, on_stop, on_cancel=None):
        self.required = set(m.lower() for m in modifiers)
        self.key_char = key.lower()
        self.key_vk = ord(key.upper())
        # Ctrl+<letter> arrives as a control character on Windows.
        self.key_ctrl_char = chr(ord(key.upper()) - 64)
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel

        self._held_modifiers = set()
        self._active = False
        self._lock = threading.Lock()
        self._listener = None

    def _modifier_name(self, key):
        for name, variants in MODIFIER_KEYS.items():
            if key in variants:
                return name
        return None

    def _is_trigger(self, key):
        vk = getattr(key, "vk", None)
        if vk is not None and vk == self.key_vk:
            return True
        char = getattr(key, "char", None)
        return char is not None and char in (self.key_char, self.key_ctrl_char)

    def _press(self, key):
        name = self._modifier_name(key)
        if name:
            self._held_modifiers.add(name)
            return

        # Escape while still holding the key throws the recording away. You
        # realise you said the wrong thing before you have finished saying it,
        # and this is the only moment where that is still free.
        if key == keyboard.Key.esc:
            self._abandon()
            return

        if not self._is_trigger(key):
            return
        if not self.required.issubset(self._held_modifiers):
            return

        with self._lock:
            if self._active:
                return  # key auto-repeat while held
            self._active = True
        self.on_start()

    def _release(self, key):
        name = self._modifier_name(key)
        if name:
            self._held_modifiers.discard(name)
            # Letting go of a modifier ends the utterance too, so the recorder
            # can never be left running.
            if name in self.required:
                self._end()
            return
        if self._is_trigger(key):
            self._end()

    def _end(self):
        with self._lock:
            if not self._active:
                return
            self._active = False
        self.on_stop()

    def _abandon(self):
        """Discard whatever is being recorded. Releasing the key after this
        does nothing, because `_active` is already false."""
        with self._lock:
            if not self._active:
                return
            self._active = False
        if self.on_cancel is not None:
            self.on_cancel()

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._press, on_release=self._release
        )
        self._listener.daemon = True
        self._listener.start()
        return self._listener

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
