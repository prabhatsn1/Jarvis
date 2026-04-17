import subprocess
import platform
import logging

log = logging.getLogger("jarvis.speech.tts")

SYSTEM = platform.system()


class Synthesizer:
    def __init__(self, config):
        self.voice = config.get("voice", "Daniel")
        self.rate = config.get("rate", 180)

    def speak(self, text):
        """Speak text aloud using the system TTS engine."""
        if not text:
            return

        log.info(f"Speaking: '{text}'")

        try:
            if SYSTEM == "Darwin":
                subprocess.run(
                    ["say", "-v", self.voice, "-r", str(self.rate), text],
                    check=True,
                    timeout=15,
                )
            elif SYSTEM == "Windows":
                # Use PowerShell with stdin piping to avoid injection
                ps_script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.Rate = {max(-10, min(10, (self.rate - 180) // 20))}; "
                    "$s.Speak([Console]::In.ReadToEnd())"
                )
                subprocess.run(
                    ["powershell", "-Command", ps_script],
                    input=text,
                    text=True,
                    check=True,
                    timeout=15,
                )
            else:
                log.warning(f"TTS not supported on {SYSTEM}")
        except subprocess.TimeoutExpired:
            log.warning("TTS timed out")
        except Exception as e:
            log.error(f"TTS error: {e}")

    def beep(self):
        """Play a short attention sound."""
        if SYSTEM == "Darwin":
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Tink.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif SYSTEM == "Windows":
            subprocess.Popen(
                [
                    "powershell", "-NoProfile", "-Command",
                    "[Console]::Beep(800, 150)"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
