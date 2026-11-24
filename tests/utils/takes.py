"""Takes for the tests: WAVs that read like speech to scoring.py's level checks, and transcripts shaped like
strata-models' `transcribe` answer (Whisper's segments and word timings) for `fake_models` to give back."""

from typing import Any

from strata_python.testing import sine_wav


def speech(seconds: float = 1.0, **kw: Any) -> bytes:
    """A take `seconds` long that passes the level checks: a tone (the voice) with a fifth of quiet before and
    after it, as a real take has between pressing Record and speaking. A bare `sine_wav` has no quiet at all, so its
    noise floor is the tone itself and it reads as a noisy room."""
    return sine_wav(seconds * 0.6, lead=seconds * 0.2, tail=seconds * 0.2, **kw)


def heard(text: str, start: float = 0.3, end: float = 0.9) -> dict[str, Any]:
    """The transcribe role's answer for `text` said between `start` and `end`, its words spread evenly."""
    words = text.split()
    step = (end - start) / max(1, len(words))
    timed = [
        {
            "start": round(start + i * step, 3),
            "end": round(start + (i + 1) * step, 3),
            "word": f" {w}",
            "probability": 0.9,
        }
        for i, w in enumerate(words)
    ]
    segment = {"start": start, "end": end, "text": f" {text}", "avg_logprob": -0.2, "no_speech_prob": 0.01}
    return {
        "language": "en",
        "language_probability": 0.99,
        "duration": end,
        "segments": [{**segment, "words": timed}] if words else [],
    }
