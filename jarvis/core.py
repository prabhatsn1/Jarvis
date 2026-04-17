import threading
import queue
import logging
import signal
import sys

from jarvis.config import load_config
from jarvis.audio.capture import AudioCapture
from jarvis.audio.wake import WakeWordDetector
from jarvis.audio.clap import ClapDetector
from jarvis.speech.recognizer import SpeechRecognizer
from jarvis.speech.synthesizer import Synthesizer
from jarvis.brain.engine import IntentEngine
from jarvis.brain.registry import CommandRegistry
from jarvis.actions.executor import ActionExecutor
from jarvis.memory.store import MemoryStore
from jarvis.ipc.server import IPCServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("jarvis")


class Jarvis:
    def __init__(self, config_path=None):
        self.config = load_config(config_path)
        self.running = False
        self.wake_queue: queue.Queue = queue.Queue()
        self.state = "dormant"

        log.info("Initializing JARVIS v1...")

        # Subsystems
        self.memory = MemoryStore(self.config["memory"]["db_path"])
        self.registry = CommandRegistry()
        self.intent_engine = IntentEngine(self.registry, self.memory)
        self.recognizer = SpeechRecognizer(self.config["speech"])
        self.synthesizer = Synthesizer(self.config["voice"])
        self.executor = ActionExecutor()
        self.ipc = IPCServer(self.config["ipc"]["socket_path"])

        # Audio
        self.audio = AudioCapture(self.config["audio"])
        self.wake_detector = WakeWordDetector(self.config["wake"])
        self.clap_detector = ClapDetector(self.config.get("clap", {}))

        log.info("All systems initialized.")

    # ── State management ────────────────────────────────────────

    def _set_state(self, new_state):
        self.state = new_state
        self.ipc.broadcast({"type": "state", "state": new_state})
        log.info(f"State → {new_state}")

    # ── Wake detection ──────────────────────────────────────────

    def _on_audio(self, audio_chunk):
        """Called by AudioCapture for every chunk while not recording."""
        if self.state != "dormant":
            return

        if self.wake_detector.process(audio_chunk):
            self.wake_queue.put("wake_word")
        elif self.clap_detector.process(audio_chunk):
            self.wake_queue.put("clap")

    def _keyboard_loop(self):
        """Fallback: press Enter to wake Jarvis (when no wake-word engine)."""
        while self.running:
            try:
                input()  # blocks until Enter
                if self.state == "dormant":
                    self.wake_queue.put("keyboard")
            except EOFError:
                break

    # ── Command pipeline ────────────────────────────────────────

    def _process_command(self):
        self._set_state("woke")
        self.synthesizer.beep()

        # Record
        self._set_state("listening")
        audio_data = self.audio.record_command(
            timeout=self.config["audio"]["command_timeout"]
        )

        if audio_data is None:
            self.synthesizer.speak("I didn't catch that.")
            self._set_state("dormant")
            return

        # Transcribe
        self._set_state("thinking")
        text = self.recognizer.transcribe(audio_data)

        if not text:
            self.synthesizer.speak("I didn't catch that.")
            self._set_state("dormant")
            return

        log.info(f"Heard: '{text}'")
        self.ipc.broadcast({"type": "transcript", "text": text})

        # Match intent
        result = self.intent_engine.match(text)

        if result is None:
            self.synthesizer.speak("I don't know how to do that.")
            self._set_state("dormant")
            return

        log.info(f"Intent: {result.intent} | Slots: {result.slots}")

        # Execute
        action_result = self.executor.execute(result.action, result.slots)

        # Respond
        self._set_state("speaking")
        try:
            response = result.response.format(
                **result.slots, result=action_result or ""
            )
        except KeyError:
            response = action_result or "Done."
        self.synthesizer.speak(response)

        # Log
        self.memory.log_action(result.intent, text, result.slots)

        self._set_state("dormant")

    # ── Main loop ───────────────────────────────────────────────

    def run(self):
        self.running = True

        def shutdown(sig, frame):
            log.info("\nShutting down...")
            self.running = False
            self.audio.stop()
            self.wake_detector.cleanup()
            self.ipc.stop()
            self.memory.close()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        # Start IPC
        self.ipc.start()

        # Start audio pipeline
        self.audio.start(self._on_audio)

        # Keyboard fallback when no wake-word engine
        if self.wake_detector.engine == "disabled":
            kb_thread = threading.Thread(
                target=self._keyboard_loop, daemon=True
            )
            kb_thread.start()
            log.info("No wake word — press Enter to wake Jarvis.")

        self._set_state("dormant")
        self.synthesizer.speak("Jarvis online.")
        log.info("JARVIS is listening. Say 'Jarvis' or double-clap to wake.")

        # Main event loop
        while self.running:
            try:
                trigger = self.wake_queue.get(timeout=0.5)
                log.info(f"Wake trigger: {trigger}")
                self._process_command()
            except queue.Empty:
                continue
