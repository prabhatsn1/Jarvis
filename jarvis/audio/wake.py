import logging

import numpy as np

log = logging.getLogger("jarvis.audio.wake")


class WakeWordDetector:
    def __init__(self, config):
        self.engine = config.get("engine", "porcupine")
        self._detector = None

        if self.engine == "porcupine":
            self._init_porcupine(config)
        else:
            log.info("Wake word engine: keyboard (press Enter to wake)")

    def _init_porcupine(self, config):
        access_key = config.get("porcupine_access_key", "")
        if not access_key:
            log.warning(
                "No Porcupine access key provided. "
                "Get one free at https://console.picovoice.ai — "
                "falling back to keyboard mode."
            )
            self.engine = "disabled"
            return

        try:
            import pvporcupine

            keyword = config.get("keyword", "jarvis")
            sensitivity = config.get("sensitivity", 0.7)

            self._detector = pvporcupine.create(
                access_key=access_key,
                keywords=[keyword],
                sensitivities=[sensitivity],
            )
            log.info(f"Porcupine wake word ready (keyword='{keyword}')")
        except ImportError:
            log.warning("pvporcupine not installed — falling back to keyboard mode.")
            self.engine = "disabled"
        except Exception as e:
            log.error(f"Porcupine init failed: {e}")
            self.engine = "disabled"

    def process(self, audio_chunk):
        """Process a single audio chunk. Returns True if wake word detected."""
        if self.engine != "porcupine" or self._detector is None:
            return False

        # Porcupine expects int16 PCM
        pcm = (audio_chunk * 32767).astype(np.int16)

        frame_length = self._detector.frame_length
        if len(pcm) < frame_length:
            pcm = np.pad(pcm, (0, frame_length - len(pcm)))
        elif len(pcm) > frame_length:
            pcm = pcm[:frame_length]

        result = self._detector.process(pcm)
        if result >= 0:
            log.info("Wake word detected!")
            return True

        return False

    def cleanup(self):
        if self._detector:
            self._detector.delete()
            self._detector = None
