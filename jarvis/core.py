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
from jarvis.brain.llm import LLMEngine
from jarvis.brain.registry import CommandRegistry
from jarvis.actions.executor import ActionExecutor
from jarvis.memory.store import MemoryStore
from jarvis.ipc.server import IPCServer
from jarvis.monitor.health import SystemHealthMonitor, set_monitor
from jarvis.monitor.stats import StatsBroadcaster

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("jarvis")

# ── Approval-gate helpers ────────────────────────────────────────────────────
# (defined in exec_commands so they can be imported without heavy audio deps)
from jarvis.actions.exec_commands import _is_confirmation, _is_rejection


class Jarvis:
    def __init__(self, config_path=None):
        self.config = load_config(config_path)
        self.running = False
        self.wake_queue: queue.Queue = queue.Queue()
        self.state = "dormant"
        self.awake = False  # persistent-awake mode

        log.info("Initializing JARVIS v1...")

        # Subsystems
        self.memory = MemoryStore(self.config["memory"]["db_path"])
        self.registry = CommandRegistry()
        self.llm = LLMEngine(self.config.get("llm", {}))

        # Semantic memory (optional)
        self.semantic_memory = None
        if self.config.get("memory", {}).get("semantic_enabled", False):
            from jarvis.memory.semantic import SemanticMemory
            self.semantic_memory = SemanticMemory(
                self.config["memory"], llm=self.llm
            )
            from jarvis.actions.memory import set_semantic_memory
            set_semantic_memory(self.semantic_memory)

        self.intent_engine = IntentEngine(
            self.registry, self.memory, self.llm,
            semantic_memory=self.semantic_memory,
        )
        self.recognizer = SpeechRecognizer(self.config["speech"])
        self.synthesizer = Synthesizer(self.config["voice"])
        self.executor = ActionExecutor()
        self.ipc = IPCServer(self.config["ipc"]["socket_path"])

        # Audio
        self.audio = AudioCapture(self.config["audio"])
        self.wake_detector = WakeWordDetector(self.config["wake"])
        self.clap_detector = ClapDetector(self.config.get("clap", {}))

        # Health monitor
        self._alert_queue: queue.Queue = queue.Queue()
        monitor_cfg = self.config.get("health_monitor", {})
        self.health_monitor = SystemHealthMonitor(
            monitor_cfg, on_alert=self._on_health_alert
        )
        set_monitor(self.health_monitor)

        self.stats_broadcaster = StatsBroadcaster(
            self.ipc, self.health_monitor, interval_sec=5
        )

        # Browser automation config injection
        from jarvis.actions.browser import set_browser_config
        set_browser_config(self.config.get("browser", {}))

        # Integrations (calendar / email) — optional; graceful if not configured
        integrations_cfg = self.config.get("integrations", {})
        if integrations_cfg.get("enabled", True):
            try:
                from jarvis.actions.integrations import set_integrations_context
                set_integrations_context(integrations_cfg, self.memory)
                log.info("Calendar/email integration context injected.")
            except Exception as exc:
                log.warning("Could not initialise integrations context: %s", exc)

            try:
                from jarvis.brain.tools import set_calendar_context
                set_calendar_context(integrations_cfg, self.memory)
                log.info("Calendar tool context injected into LLM tools.")
            except Exception as exc:
                log.warning("Could not initialise calendar tool context: %s", exc)

        # Smart home — optional; graceful if not configured
        smarthome_cfg = self.config.get("smart_home", {})
        if smarthome_cfg.get("enabled", False):
            try:
                from jarvis.actions.smarthome import set_smarthome_context
                set_smarthome_context(smarthome_cfg)
                log.info("Smart home context injected.")
            except Exception as exc:
                log.warning("Could not initialise smart home context: %s", exc)

            try:
                from jarvis.brain.tools import set_smarthome_context as _set_sh_tool_ctx
                _set_sh_tool_ctx(smarthome_cfg)
                log.info("Smart home tool context injected into LLM tools.")
            except Exception as exc:
                log.warning("Could not initialise smart home tool context: %s", exc)

        # Exec commands — always injected (enabled flag checked inside)
        exec_cfg = self.config.get("exec_commands", {})
        try:
            from jarvis.actions.exec_commands import set_exec_context
            set_exec_context(exec_cfg)
            log.info("Exec commands context injected.")
        except Exception as exc:
            log.warning("Could not initialise exec commands context: %s", exc)

        # Notifications (timers, alarms, reminders)
        notif_cfg = self.config.get("notifications", {})
        try:
            from jarvis.actions.notify import set_notification_context
            set_notification_context(
                notif_cfg,
                synthesizer=self.synthesizer,
                on_fire=self.ipc.broadcast,
            )
            log.info("Notification context injected.")
        except Exception as exc:
            log.warning("Could not initialise notification context: %s", exc)

        # Event scheduler (proactive calendar reminders)
        event_sched_cfg = self.config.get("event_scheduler", {})
        try:
            from jarvis.actions.event_scheduler import (
                EventScheduler,
                set_event_scheduler_context,
            )
            set_event_scheduler_context(
                event_sched_cfg,
                integrations_cfg=self.config.get("integrations", {}),
                memory_store=self.memory,
                synthesizer=self.synthesizer,
                on_fire=self.ipc.broadcast,
            )
            self.event_scheduler = EventScheduler()
            log.info("Event scheduler context injected.")
        except Exception as exc:
            self.event_scheduler = None
            log.warning("Could not initialise event scheduler: %s", exc)

        # Vision (screenshot + GPT-4 Vision)
        vision_cfg = self.config.get("vision", {})
        try:
            from jarvis.actions.vision import set_vision_context
            set_vision_context(vision_cfg, llm_cfg=self.config.get("llm", {}))
            log.info("Vision context injected.")
        except Exception as exc:
            log.warning("Could not initialise vision context: %s", exc)

        log.info("All systems initialized.")

    # ── State management ────────────────────────────────────────

    def _set_state(self, new_state):
        old_state = self.state
        self.state = new_state
        self.ipc.broadcast({"type": "state", "state": new_state})
        log.info(f"State → {new_state}")
        if new_state == "listening":
            self.synthesizer.chime_listening()
            self.stats_broadcaster.set_task("Listening...")
        elif new_state == "thinking":
            self.synthesizer.chime_thinking()
        elif new_state == "speaking":
            self.synthesizer.chime_speaking()
        elif new_state == "dormant" and old_state not in ("dormant",):
            self.synthesizer.chime_dormant()
            self.stats_broadcaster.set_task("")
        # Flush deferred health alerts when returning to an idle state
        if new_state in ("dormant", "thinking"):
            self._flush_alert_queue()

    # ── Health alert handling ────────────────────────────────────

    def _on_health_alert(self, metric: str, value: float, threshold: float, severity: str) -> None:
        """Callback fired by SystemHealthMonitor on threshold crossing."""
        label_map = {"cpu": "CPU", "ram": "RAM", "disk": "disk", "gpu": "GPU"}
        label = label_map.get(metric, metric.upper())
        message = f"Boss, your {label} is at {value:.0f}%."

        try:
            self.ipc.broadcast({"type": "health_alert", "metric": metric,
                                 "value": value, "threshold": threshold,
                                 "severity": severity})
        except Exception as exc:
            log.warning("IPC broadcast error during health alert: %s", exc)

        # Speak immediately if idle, otherwise queue for later
        if self.state in ("dormant", "thinking"):
            try:
                self.synthesizer.speak(message)
            except Exception as exc:
                log.warning("Synthesizer error during health alert: %s", exc)
        else:
            # Queue a single deferred alert (drop older queued items first)
            while not self._alert_queue.empty():
                try:
                    self._alert_queue.get_nowait()
                except queue.Empty:
                    break
            self._alert_queue.put_nowait(message)

    def _flush_alert_queue(self) -> None:
        """Speak any queued health alert (at most one at a time)."""
        try:
            message = self._alert_queue.get_nowait()
            self.synthesizer.speak(message)
        except queue.Empty:
            pass
        except Exception as exc:
            log.warning("Error flushing alert queue: %s", exc)

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
        """Press Enter to wake Jarvis."""
        while self.running:
            try:
                input()  # blocks until Enter
                if self.state == "dormant":
                    self.wake_queue.put("keyboard")
            except EOFError:
                break

    # ── Command pipeline ────────────────────────────────────────

    def _process_command(self):
        if not self.awake:
            self.awake = True
            self._set_state("woke")
            self.synthesizer.beep()

        # Pending-approval state: set True after a run_terminal_command /
        # run_python_script action returns the APPROVAL_PREFIX sentinel.
        _awaiting_approval = False

        while self.awake:
            # Record
            self._set_state("listening")
            audio_data = self.audio.record_command(
                timeout=self.config["audio"]["command_timeout"]
            )

            if audio_data is None:
                continue  # nothing said, just keep listening

            # Transcribe
            self._set_state("thinking")
            text = self.recognizer.transcribe(audio_data)

            if not text:
                continue  # nothing transcribed, keep listening

            log.info(f"Heard: '{text}'")
            self.ipc.broadcast({"type": "transcript", "text": text})
            self.stats_broadcaster.set_task(text)

            # ── Emotion / urgency detection ──────────────────────────────────
            if self.config.get("emotion", {}).get("enabled", True):
                try:
                    from jarvis.audio.emotion import analyze_emotion
                    emotion_result = analyze_emotion(audio_data, text=text)
                    if emotion_result.emotion != "normal":
                        log.info(
                            "Emotion detected: %s (confidence=%.2f)",
                            emotion_result.emotion, emotion_result.confidence,
                        )
                    self.ipc.broadcast({
                        "type": "emotion",
                        "emotion": emotion_result.emotion,
                        "confidence": round(emotion_result.confidence, 2),
                    })
                    if self.llm:
                        self.llm.set_tone(emotion_result.emotion)
                except Exception as _emotion_exc:
                    log.debug("Emotion detection skipped: %s", _emotion_exc)
            # ────────────────────────────────────────────────────────────────

            # ── Approval gate ────────────────────────────────────────────────
            if _awaiting_approval:
                from jarvis.actions.exec_commands import (
                    execute_pending, cancel_pending, has_pending,
                )
                normalized = text.strip().lower().rstrip(".!?,;")
                if _is_confirmation(normalized):
                    if has_pending():
                        self._set_state("speaking")
                        exec_result = execute_pending()
                        self.synthesizer.speak(exec_result)
                    else:
                        self.synthesizer.speak("Nothing pending to run.")
                    _awaiting_approval = False
                elif _is_rejection(normalized):
                    cancel_pending()
                    self._set_state("speaking")
                    self.synthesizer.speak("Cancelled.")
                    _awaiting_approval = False
                else:
                    self._set_state("speaking")
                    self.synthesizer.speak(
                        "Say confirm to run the command, or cancel to abort."
                    )
                continue
            # ────────────────────────────────────────────────────────────────

            # Match intent
            result = self.intent_engine.match(text)

            if result is None:
                self.synthesizer.speak("I don't know how to do that.")
                continue

            log.info(f"Intent: {result.intent} | Slots: {result.slots}")

            # Execute
            action_result = self.executor.execute(result.action, result.slots)

            # ── Check for approval sentinel ──────────────────────────────────
            from jarvis.actions.exec_commands import APPROVAL_PREFIX
            if action_result and action_result.startswith(APPROVAL_PREFIX):
                prompt = action_result[len(APPROVAL_PREFIX):]
                _awaiting_approval = True
                self._set_state("speaking")
                self.synthesizer.speak(prompt)
                self.memory.log_action(result.intent, text, result.slots)
                continue

            # Also check if an LLM-invoked run_command left a pending action
            # (the LLM tool returns PENDING_APPROVAL... not the full sentinel)
            from jarvis.actions.exec_commands import has_pending as _has_pending
            if _has_pending():
                _awaiting_approval = True
            # ────────────────────────────────────────────────────────────────

            # Respond
            self._set_state("speaking")
            try:
                response = result.response.format(
                    **result.slots, result=action_result or ""
                )
            except (KeyError, ValueError):
                response = result.response or action_result or "Done."
            self.synthesizer.speak(response)

            # Log
            self.memory.log_action(result.intent, text, result.slots)

            # Stand by if user said bye
            if result.intent == "jarvis_stop":
                self.awake = False
                self.llm.clear_history()

        self._set_state("dormant")

    # ── Main loop ───────────────────────────────────────────────

    def run(self):
        self.running = True

        def shutdown(sig, frame):
            log.info("\nShutting down...")
            self.running = False
            try:
                self.stats_broadcaster.stop()
            except Exception as exc:
                log.warning("Stats broadcaster stop error: %s", exc)
            try:
                self.health_monitor.stop()
            except Exception as exc:
                log.warning("Health monitor stop error: %s", exc)
            if getattr(self, "event_scheduler", None):
                try:
                    self.event_scheduler.stop()
                except Exception as exc:
                    log.warning("Event scheduler stop error: %s", exc)
            self.audio.stop()
            self.wake_detector.cleanup()
            self.ipc.stop()
            if self.semantic_memory:
                try:
                    rows = self.memory.get_recent_actions(n=50)
                    self.semantic_memory.summarize_and_store_session(rows)
                except Exception as exc:
                    log.warning("Session summarization failed: %s", exc)
                self.semantic_memory.close()
            self.memory.close()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        # Start IPC
        self.ipc.start()
        self.stats_broadcaster.start()

        # Start health monitor (if enabled in config)
        if self.config.get("health_monitor", {}).get("enabled", False):
            try:
                self.health_monitor.start()
            except Exception as exc:
                log.warning("Health monitor failed to start: %s", exc)

        # Start event scheduler (proactive calendar reminders)
        if getattr(self, "event_scheduler", None):
            try:
                self.event_scheduler.start()
            except Exception as exc:
                log.warning("Event scheduler failed to start: %s", exc)

        # Start audio pipeline
        self.audio.start(self._on_audio)

        # Keyboard always available alongside wake word / clap
        kb_thread = threading.Thread(target=self._keyboard_loop, daemon=True)
        kb_thread.start()

        self._set_state("dormant")
        self.synthesizer.speak("Jarvis online.")
        log.info("JARVIS is listening. Say 'Hey Jarvis', double-clap, or press Enter to wake.")

        # Main event loop
        while self.running:
            try:
                trigger = self.wake_queue.get(timeout=0.5)
                log.info(f"Wake trigger: {trigger}")
                if not self.awake:
                    self._process_command()
            except queue.Empty:
                continue
