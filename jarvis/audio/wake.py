import logging

import numpy as np

log = logging.getLogger("jarvis.audio.wake")


class WakeWordDetector:
    def __init__(self, config):
        self.engine = config.get("engine", "openwakeword")
        self._model = None

        if self.engine == "openwakeword":
            self._init_openwakeword(config)
        else:
            log.info("Wake word engine: keyboard (press Enter to wake)")

    def _init_openwakeword(self, config):
        try:
            import openwakeword
            from openwakeword.model import Model

            model_name = config.get("model", "hey_jarvis")
            self.threshold = config.get("threshold", 0.5)
            self._model_name = model_name

            # Download pre-trained models if not already present
            openwakeword.utils.download_models()

            self._model = Model(wakeword_models=[model_name])
            log.info(
                f"OpenWakeWord ready (model='{model_name}', "
                f"threshold={self.threshold})"
            )
        except ImportError:
            log.warning(
                "openwakeword not installed — falling back to keyboard mode."
            )
            self.engine = "disabled"
        except Exception as e:
            log.error(f"OpenWakeWord init failed: {e}")
            self.engine = "disabled"

    def process(self, audio_chunk):
        """Process a single audio chunk. Returns True if wake word detected."""
        if self.engine != "openwakeword" or self._model is None:
            return False

        # OpenWakeWord expects int16 PCM
        pcm = (audio_chunk * 32767).astype(np.int16)

        prediction = self._model.predict(pcm)

        for key, score in prediction.items():
            if score >= self.threshold:
                log.info(f"Wake word detected! (model={key}, score={score:.3f})")
                self._model.reset()
                return True

        return False

    def cleanup(self):
        self._model = None
