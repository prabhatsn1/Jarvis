import re
import logging

from rapidfuzz import fuzz

from jarvis.brain.registry import IntentResult

log = logging.getLogger("jarvis.brain")

STOP_WORDS = frozenset({
    "please", "could", "you", "can", "would", "hey", "jarvis",
    "just", "go", "ahead", "and", "the", "a", "an", "for", "me",
    "my", "i", "want", "to", "need", "like", "do", "that", "this",
    "it", "now", "right", "okay", "ok", "um", "uh", "so", "well",
    "actually", "maybe", "kind", "of", "sort", "basically",
})

FUZZY_THRESHOLD = 65  # Minimum token_sort_ratio (0-100)


class IntentEngine:
    def __init__(self, registry, memory=None):
        self.registry = registry
        self.memory = memory

    # ── public API ──────────────────────────────────────────────

    def match(self, text):
        """Match text → IntentResult or None. No hallucinations."""
        text = text.strip().rstrip(".!?,;")
        if not text:
            return None

        # Phase 1: exact regex match
        result = self._regex_match(text)
        if result:
            log.info(f"Regex match → {result.intent} (1.0)")
            return result

        # Phase 2: regex after stripping filler words
        clean = self._normalize(text)
        if clean != text.lower():
            result = self._regex_match(clean)
            if result:
                result.confidence = 0.9
                log.info(f"Normalized match → {result.intent} (0.9)")
                return result

        # Phase 3: fuzzy token matching
        result = self._fuzzy_match(clean)
        if result:
            log.info(f"Fuzzy match → {result.intent} ({result.confidence:.2f})")
            return result

        # Phase 4: learned phrase mappings from memory
        if self.memory:
            result = self._memory_match(text)
            if result:
                log.info(f"Memory match → {result.intent}")
                return result

        log.info(f"No match for: '{text}'")
        return None

    # ── internals ───────────────────────────────────────────────

    def _regex_match(self, text):
        for cmd in self.registry.commands:
            for regex in cmd.compiled:
                m = regex.match(text)
                if m:
                    slots = {k: v.strip().rstrip(".!?,;") for k, v in m.groupdict().items()}
                    return IntentResult(
                        intent=cmd.intent,
                        action=cmd.action,
                        slots=slots,
                        response=cmd.response,
                        confidence=1.0,
                    )
        return None

    @staticmethod
    def _normalize(text):
        words = text.lower().split()
        filtered = [w for w in words if w not in STOP_WORDS]
        return " ".join(filtered) if filtered else text.lower()

    def _fuzzy_match(self, text):
        best_score = 0
        best_cmd = None
        best_slots = {}

        for cmd in self.registry.commands:
            for pattern in cmd.patterns:
                # Strip slot placeholders for comparison
                slotless = re.sub(r"\{\w+\}", "", pattern).strip()
                score = fuzz.token_sort_ratio(text, slotless)

                if score > best_score:
                    best_score = score
                    best_cmd = cmd
                    best_slots = self._extract_slots_fuzzy(
                        text, pattern, cmd.slots
                    )

        if best_score >= FUZZY_THRESHOLD and best_cmd:
            return IntentResult(
                intent=best_cmd.intent,
                action=best_cmd.action,
                slots=best_slots,
                response=best_cmd.response,
                confidence=best_score / 100.0,
            )
        return None

    @staticmethod
    def _extract_slots_fuzzy(text, pattern, slot_defs):
        """Best-effort slot extraction from a fuzzy-matched utterance."""
        slots = {}
        pattern_parts = pattern.split()
        pattern_words = {
            p.lower() for p in pattern_parts if not p.startswith("{")
        }
        words = text.split()

        for part in pattern_parts:
            m = re.match(r"\{(\w+)\}", part)
            if m:
                slot_name = m.group(1)
                remaining = [
                    w for w in words
                    if w.lower() not in pattern_words
                    and w.lower() not in STOP_WORDS
                ]
                if remaining:
                    slots[slot_name] = " ".join(remaining)
        return slots

    def _memory_match(self, text):
        if not self.memory:
            return None
        mapping = self.memory.get_phrase_mapping(text.lower())
        if mapping:
            for cmd in self.registry.commands:
                if cmd.intent == mapping["intent"]:
                    return IntentResult(
                        intent=cmd.intent,
                        action=cmd.action,
                        slots=mapping.get("slots", {}),
                        response=cmd.response,
                        confidence=0.85,
                    )
        return None
