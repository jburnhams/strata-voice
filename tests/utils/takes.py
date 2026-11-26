"""Takes for the tests: WAVs that read like speech to scoring.py's level checks, and transcripts shaped like
strata-models' `transcribe` answer (Whisper's segments and word timings) for `fake_models` to give back."""

from collections.abc import Callable
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


#: A found recording for the ingest tests: three sentences (start, end, words) with pauses between them, the middle
#: one by someone else.
RECORDING = [
    (0.5, 2.5, "The kettle sang on the stove."),
    (3.5, 5.0, "Who wants more tea?"),
    (6.0, 8.5, "Bring the blue cups from the shelf."),
]
RECORDING_SECONDS = 9.0
OTHER_VOICE = 1  # the index of the sentence said by someone else


def recording(path: str, *, amplitude: float = 0.05) -> str:
    """`RECORDING` as a stereo FLAC at 44.1 kHz, quiet (so levelling lifts it), each sentence a tone, made by ffmpeg:
    a format the studio never records in, as a found file would be."""
    import os
    import subprocess
    import tempfile

    from strata_python.testing import sine_wav

    parts: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        at = 0.0
        for i, (start, end, _) in enumerate(RECORDING):
            wav = os.path.join(tmp, f"{i}.wav")
            with open(wav, "wb") as f:
                f.write(
                    sine_wav(
                        end - start, rate=44_100, channels=2, amplitude=amplitude, lead=start - at, hz=180 + 60 * i
                    )
                )
            parts.append(wav)
            at = end
        tail = os.path.join(tmp, "tail.wav")
        with open(tail, "wb") as f:
            f.write(sine_wav(0.0, rate=44_100, channels=2, tail=RECORDING_SECONDS - at))
        parts.append(tail)
        listing = os.path.join(tmp, "list.txt")
        with open(listing, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c:a", "flac", path],
            check=True,
        )
    return path


def recording_heard() -> dict[str, Any]:
    """The transcribe role's answer for the whole of `RECORDING`."""
    segments = [heard(text, start, end)["segments"][0] for start, end, text in RECORDING]
    return {"language": "en", "language_probability": 0.99, "duration": RECORDING_SECONDS, "segments": segments}


ME, SOMEONE = [1.0, 0.0], [0.0, 1.0]


def found_heard(session: Callable[[], Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """The transcribe role for an upload of `recording()`: the whole levelled file is heard as `RECORDING`, a sentence
    cut from it as its prompt's words (looked up through `session()`, a Session on the test's database), and a studio
    take as "hello"."""
    import re

    from stratavoice.models import Prompt, Take

    def answer(params: dict[str, Any]) -> dict[str, Any]:
        path = params["path"]
        if path.endswith("normalized.wav"):
            assert params["vad_filter"] is True
            return recording_heard()
        m = re.search(r"found[/\\]take_(\d+)\.wav$", path)
        if m is None:
            return heard("hello")
        with session() as s:
            t = s.get(Take, int(m.group(1)))
            p = None if t is None else s.get(Prompt, t.prompt_id)
            assert t is not None
            assert p is not None
            return heard(p.text, 0.15, t.frames / t.sample_rate - 0.25)

    return answer


def found_voices(params: dict[str, Any]) -> dict[str, Any]:
    """The speaker-embedding role for an upload of `recording()`: the `OTHER_VOICE` sentence is someone else, every
    other stretch (and every studio take) the speaker."""
    vectors: list[list[float] | None] = []
    for item in params["items"]:
        clip = item.get("clip")
        other = item["path"].endswith("normalized.wav") and clip and abs(clip[0] - RECORDING[OTHER_VOICE][0]) < 0.01
        vectors.append(SOMEONE if other else ME)
    return {"dim": 2, "embeddings": vectors, "seconds": [1.0] * len(vectors)}
