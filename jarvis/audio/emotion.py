"""Voice emotion / urgency detection from audio signals.

Analyses three signal features extracted from the raw audio:
  - RMS energy          — overall loudness / arousal level
  - Zero-crossing rate variance — correlates with vocal tension and stress
  - Voiced-frame ratio  — density of speech activity (proxy for speaking rate)

Detected emotions:
  ``normal``     — calm, relaxed speech
  ``urgent``     — high energy + dense speech (fast, loud commands)
  ``frustrated`` — clipped with silence bursts, elevated energy, tension cues

Text-based keyword cues from the transcription supplement the signal features.
The combined score is normalised to a 0–1 confidence value.

Usage::

    from jarvis.audio.emotion import analyze_emotion, EmotionResult
    result = analyze_emotion(audio_array, sample_rate=16000, text="do it now!")
    print(result.emotion, result.confidence)   # → urgent 0.82
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("jarvis.audio.emotion")

# ── Signal thresholds ─────────────────────────────────────────────────────────

_ENERGY_HIGH = 0.06        # RMS ≥ this → clearly elevated arousal
_ENERGY_MEDIUM = 0.03      # RMS ≥ this → mild arousal
_ZCR_VAR_HIGH = 0.005      # ZCR frame-variance ≥ this → vocal tension
_VOICED_RATIO_HIGH = 0.70  # voiced frames / total ≥ this → dense / fast speech

# ── Text-based keyword cues ───────────────────────────────────────────────────

_URGENCY_WORDS = frozenset({
    "now", "immediately", "hurry", "quick", "quickly", "fast", "asap",
    "urgent", "emergency", "right now", "stat", "please hurry",
})

_FRUSTRATION_WORDS = frozenset({
    "ugh", "again", "still", "not working", "broken", "useless",
    "why", "wrong", "error", "failed", "keep", "always", "never",
    "ridiculous", "seriously", "come on", "again",
})


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class EmotionResult:
    emotion: str          # "normal" | "urgent" | "frustrated"
    confidence: float     # 0.0–1.0
    energy: float         # RMS amplitude
    zcr_variance: float   # ZCR frame-variance
    voiced_ratio: float   # fraction of voiced frames


# ── Main analysis function ────────────────────────────────────────────────────

def analyze_emotion(
    audio: np.ndarray,
    sample_rate: int = 16000,
    text: str = "",
) -> EmotionResult:
    """Detect emotion from audio signal features and optional transcription text.

    Parameters
    ----------
    audio:
        float32 ndarray of mono audio samples.
    sample_rate:
        Samples-per-second (default 16 kHz).
    text:
        Transcribed text of the utterance — optional but improves accuracy.

    Returns
    -------
    EmotionResult with ``.emotion`` in {"normal", "urgent", "frustrated"}.
    """
    audio = audio.astype(np.float32)

    # ── Signal feature extraction ────────────────────────────────────────────

    # 1. RMS energy (overall loudness)
    rms = float(np.sqrt(np.mean(audio ** 2)))

    # 2. Zero-crossing rate per 10 ms frame, then variance across frames
    frame_size = max(1, int(sample_rate * 0.010))  # 10 ms
    n_frames = len(audio) // frame_size

    if n_frames > 1:
        zcr_per_frame = np.array([
            np.mean(np.abs(np.diff(np.sign(
                audio[i * frame_size:(i + 1) * frame_size]
            )))) / 2
            for i in range(n_frames)
        ])
        zcr_var = float(np.var(zcr_per_frame))
    else:
        zcr_var = 0.0

    # 3. Voiced-frame ratio (frames with RMS > silence threshold)
    _silence_threshold = 0.01
    if n_frames > 0:
        voiced_count = sum(
            1 for i in range(n_frames)
            if float(np.sqrt(np.mean(
                audio[i * frame_size:(i + 1) * frame_size] ** 2
            ))) > _silence_threshold
        )
        voiced_ratio = voiced_count / n_frames
    else:
        voiced_ratio = 0.0

    # ── Text-based keyword scoring ───────────────────────────────────────────
    text_lower = text.lower()
    urgency_cues = sum(1 for w in _URGENCY_WORDS if w in text_lower)
    frustration_cues = sum(1 for w in _FRUSTRATION_WORDS if w in text_lower)

    # ── Classification ───────────────────────────────────────────────────────
    # Sub-scores (0–3 each) for urgency and frustration axes
    energy_score = (
        3 if rms >= _ENERGY_HIGH else
        2 if rms >= _ENERGY_MEDIUM else 0
    )
    tension_score = 2 if zcr_var >= _ZCR_VAR_HIGH else 0
    speed_score = 2 if voiced_ratio >= _VOICED_RATIO_HIGH else 0

    urgency_text_score = min(urgency_cues, 3)
    frustration_text_score = min(frustration_cues, 2)

    urgent_score = energy_score + speed_score + urgency_text_score
    frustrated_score = energy_score + tension_score + frustration_text_score

    if frustrated_score >= 4 and frustrated_score >= urgent_score:
        emotion = "frustrated"
        confidence = min(1.0, frustrated_score / 7.0)
    elif urgent_score >= 4:
        emotion = "urgent"
        confidence = min(1.0, urgent_score / 8.0)
    else:
        emotion = "normal"
        confidence = 1.0 - min(0.8, max(urgent_score, frustrated_score) / 8.0)

    log.debug(
        "Emotion: %s (%.2f) | rms=%.4f zcr_var=%.5f voiced=%.2f "
        "urgency_cues=%d frustration_cues=%d",
        emotion, confidence, rms, zcr_var, voiced_ratio,
        urgency_cues, frustration_cues,
    )

    return EmotionResult(
        emotion=emotion,
        confidence=confidence,
        energy=rms,
        zcr_variance=zcr_var,
        voiced_ratio=voiced_ratio,
    )
