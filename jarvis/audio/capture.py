import time
import logging

import numpy as np
import sounddevice as sd

log = logging.getLogger("jarvis.audio")

CHUNK_DURATION = 0.032  # 32ms chunks — matches Porcupine frame size
SILENCE_THRESHOLD = 0.01
SILENCE_TIMEOUT = 1.5  # Seconds of silence before stopping command recording


class AudioCapture:
    def __init__(self, config):
        self.sample_rate = config.get("sample_rate", 16000)
        self.channels = config.get("channels", 1)
        self.chunk_size = int(self.sample_rate * CHUNK_DURATION)
        self.command_timeout = config.get("command_timeout", 5.0)
        self._stream = None
        self._callback = None
        self._recording = False
        self._record_buffer = []

    def start(self, callback):
        """Start continuous audio capture. callback(np.array) called per chunk."""
        self._callback = callback

        def audio_callback(indata, frames, time_info, status):
            if status:
                log.warning(f"Audio status: {status}")
            chunk = indata[:, 0].copy()

            if self._recording:
                self._record_buffer.append(chunk)
            elif self._callback:
                self._callback(chunk)

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.float32,
            blocksize=self.chunk_size,
            callback=audio_callback,
        )
        self._stream.start()
        log.info(
            f"Audio capture started (rate={self.sample_rate}, "
            f"chunk={self.chunk_size} samples)"
        )

    def record_command(self, timeout=5.0):
        """Record until silence or timeout. Returns np.array of float32 or None."""
        self._record_buffer = []
        self._recording = True

        log.info("Recording command...")
        start = time.time()
        last_speech = start

        while time.time() - start < timeout:
            time.sleep(0.1)
            if self._record_buffer:
                recent = self._record_buffer[-1]
                rms = np.sqrt(np.mean(recent ** 2))
                if rms > SILENCE_THRESHOLD:
                    last_speech = time.time()
                elif time.time() - last_speech > SILENCE_TIMEOUT:
                    break

        self._recording = False

        if not self._record_buffer:
            return None

        audio = np.concatenate(self._record_buffer)
        duration = len(audio) / self.sample_rate
        log.info(f"Recorded {duration:.1f}s of audio")

        if duration < 0.3:
            return None

        return audio

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            log.info("Audio capture stopped")
