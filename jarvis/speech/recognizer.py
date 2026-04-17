import logging

import numpy as np

log = logging.getLogger("jarvis.speech.stt")


class SpeechRecognizer:
    def __init__(self, config):
        self.model_name = config.get("whisper_model", "base.en")
        self.language = config.get("language", "en")
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return

        log.info(f"Loading Whisper model '{self.model_name}' (first run downloads ~150MB)...")
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
            )
            log.info("Whisper model loaded.")
        except ImportError:
            log.error(
                "faster-whisper not installed. "
                "Run: pip install faster-whisper"
            )
            raise

    def transcribe(self, audio):
        """Transcribe a numpy float32 audio array to text."""
        self._load_model()

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            best_of=1,
            vad_filter=True,
        )

        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info(f"Transcribed: '{text}'")
        return text
