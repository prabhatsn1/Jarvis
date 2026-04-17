import time
import logging

import numpy as np

log = logging.getLogger("jarvis.audio.clap")


class ClapDetector:
    def __init__(self, config):
        self.enabled = config.get("enabled", True)
        self.threshold = config.get("threshold", 0.6)
        self.min_interval = config.get("min_interval", 0.1)
        self.max_interval = config.get("max_interval", 0.5)

        self._last_clap_time = 0.0
        self._clap_count = 0

    def _is_clap(self, audio_chunk):
        """Detect impulsive transient (clap-like) sound."""
        rms = np.sqrt(np.mean(audio_chunk ** 2))
        if rms < self.threshold:
            return False

        # High crest factor distinguishes claps from sustained loud sounds
        peak = np.max(np.abs(audio_chunk))
        if rms > 0:
            crest = peak / rms
            return crest > 1.5
        return False

    def process(self, audio_chunk):
        """Process audio chunk. Returns True on double-clap detection."""
        if not self.enabled:
            return False

        now = time.time()

        if self._is_clap(audio_chunk):
            elapsed = now - self._last_clap_time

            if self._clap_count == 0:
                self._clap_count = 1
                self._last_clap_time = now
            elif self.min_interval <= elapsed <= self.max_interval:
                # Valid double clap
                self._clap_count = 0
                self._last_clap_time = 0.0
                log.info("Double clap detected!")
                return True
            else:
                # Too fast or too slow — treat as new first clap
                self._clap_count = 1
                self._last_clap_time = now
        elif self._clap_count > 0 and (now - self._last_clap_time) > self.max_interval:
            # Timeout waiting for second clap
            self._clap_count = 0

        return False
