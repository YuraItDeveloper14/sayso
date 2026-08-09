"""Offline speech-to-text via faster-whisper.

The model is downloaded once on first run and cached under models/, after which
SaySo never touches the network again.
"""

import threading

from .config import ROOT, settings

MODEL_DIR = ROOT / "models"


class Transcriber:
    def __init__(self, model_size=None, language=None):
        self.model_size = model_size or settings.model_size
        self.language = language or settings.language
        self._model = None
        self._load_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

    @property
    def is_ready(self):
        return self._model is not None

    def load(self):
        """Load the model. Blocking and slow on first run - call it early."""
        with self._load_lock:
            if self._model is not None:
                return self._model
            from faster_whisper import WhisperModel

            MODEL_DIR.mkdir(exist_ok=True)
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                # int8 keeps the footprint under ~200 MB, which matters on a
                # 6 GB laptop that is also running a browser.
                compute_type="int8",
                download_root=str(MODEL_DIR),
            )
            return self._model

    def transcribe(self, audio):
        """Turn a float32 numpy array into text. Returns '' if nothing was said."""
        if self._model is None:
            self.load()

        # faster-whisper's CTranslate2 backend is not safe to call concurrently.
        with self._transcribe_lock:
            segments, _info = self._model.transcribe(
                audio,
                language=self.language,
                # Greedy decoding. Commands are short and formulaic, so a wider
                # beam costs time without changing the answer.
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                without_timestamps=True,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments)

        return text.strip()


transcriber = Transcriber()
