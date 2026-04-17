import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

import yaml

log = logging.getLogger("jarvis.brain.registry")

COMMANDS_PATH = Path(__file__).parent.parent.parent / "commands.yaml"


@dataclass
class Command:
    intent: str
    patterns: list
    action: str
    slots: dict = field(default_factory=dict)
    response: str = "Done."
    compiled: list = field(default_factory=list)


@dataclass
class IntentResult:
    intent: str
    action: str
    slots: dict
    response: str
    confidence: float


class CommandRegistry:
    def __init__(self, path=None):
        self.commands: list[Command] = []
        self._load(path or COMMANDS_PATH)

    def _load(self, path):
        with open(path) as f:
            data = yaml.safe_load(f)

        for cmd_data in data.get("commands", []):
            cmd = Command(
                intent=cmd_data["intent"],
                patterns=cmd_data["patterns"],
                action=cmd_data["action"],
                slots=cmd_data.get("slots", {}),
                response=cmd_data.get("response", "Done."),
            )
            for pattern in cmd.patterns:
                regex = self._pattern_to_regex(pattern)
                cmd.compiled.append(re.compile(regex, re.IGNORECASE))

            self.commands.append(cmd)

        log.info(f"Loaded {len(self.commands)} commands")

    @staticmethod
    def _pattern_to_regex(pattern):
        """Convert 'open {app}' → regex with named capture groups."""
        # Escape regex specials, then restore slot placeholders
        escaped = re.escape(pattern)
        regex = re.sub(r"\\{(\w+)\\}", r"(?P<\1>.+?)", escaped)
        # Allow flexible whitespace
        regex = regex.replace(r"\ ", r"\s+")
        return rf"^\s*{regex}\s*$"
