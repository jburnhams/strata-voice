"""Judging a take (step 2 of docs/implementation-plan.md): is it good enough to keep for the voice model, and if not,
what should the speaker do differently on the next one?

Two checks, run on the master as kept (it is never changed):

- **Levels**, here and at once (`strata_python.wav.measure`): it clipped, it is too quiet, or the room is noisy.
- **Words**, through strata-models' `transcribe` role (Whisper with word timings): nothing was said, or the words were
  not the prompt's (word error rate, `strata_python.wer`). A take of an old free-talk prompt (`curriculum.FREE_TALK`)
  has no text to match, so only "nothing was said" applies, and its transcript is its text in the manifest. The prompt
  is not given to Whisper as its `initial_prompt`: that would pull the transcript towards the prompt and hide the
  very misreadings the check is for.

The word timings also give the crop: from just before the first word to just after the last (`PAD_BEFORE`,
`PAD_AFTER`), kept as `speech_start`/`speech_end` on the take, played back by the studio and written to the manifest.
A crop is a pair of numbers, not a second file: the master stays the one lossless copy, and a training tool cuts it.

A take with any problem is `retry`, and the studio asks for another at once; the speaker can keep it anyway
(`accept`: a name the recogniser does not know, a deliberate laugh). When strata-models is not running or is busy
past `ASR_WAIT_SECONDS`, the take is `unchecked`: kept and counted, never refused for the service's sake, and
`strata-voice score` checks it later (which can send its prompt back to the queue).

The thresholds are first guesses from the usual figures for recorded speech; step 4 (the pilot) tunes them."""

import datetime
import logging

from sqlalchemy import ColumnElement, or_
from sqlalchemy.orm import Session
from strata_python.clients import models as sm
from strata_python.contracts import ApiModel
from strata_python.wav import WavLevels, measure
from strata_python.wer import word_errors

from stratavoice import curriculum
from stratavoice.models import Prompt, Take

log = logging.getLogger(__name__)

APP = "strata-voice"
ASR_ROLE = "transcribe"
ASR_WAIT_SECONDS = 30.0  # a few seconds of speech takes well under one on the GPU; longer means the queue is busy
LANGUAGE = "en"

#: More samples than this at full scale is clipping, not one peak that touched the top.
CLIPPED_SAMPLES = 2
#: The same figure as strata-react's `speechLevel`, so the studio's level line and the verdict agree.
QUIET_PEAK_DB = -30.0
#: The room between words. Studio booths sit near -70 dBFS and a quiet home room near -60; a fan, traffic or a
#: computer's hum brings it above this, and a voice model learns the hum as part of the voice.
NOISY_FLOOR_DB = -48.0
#: A read prompt passes with at most this share of its words wrong (none in a sentence under ten words).
MAX_WER = 0.1
#: Whisper's word times are good to about a tenth of a second, and a word's onset (a breath, a plosive) starts
#: before it; the ends of words decay after. Padded so the crop never clips a word.
PAD_BEFORE = 0.15
PAD_AFTER = 0.25

GOOD, RETRY, UNCHECKED = "good", "retry", "unchecked"


def usable() -> ColumnElement[bool]:
    """A take that counts for its prompt (the queue, progress, the manifest, coverage): anything but a `retry` the
    speaker did not keep anyway."""
    return or_(Take.verdict.is_(None), Take.verdict != RETRY, Take.accepted)


class Problem(ApiModel):
    """One reason a take should be recorded again, in words the speaker can act on."""

    code: str
    sentence: str


def _quote(words: list[str]) -> str:
    return ", ".join(f"\u201c{w}\u201d" for w in words)


def problems(t: Take, p: Prompt) -> list[Problem]:
    """The take's problems as sentences, from what scoring stored (so they read the same on every screen)."""
    out: list[Problem] = []
    for code in t.problems.split():
        if code == "clipped":
            sentence = (
                f"It clipped: {t.clipped} samples hit full scale. Move back from the microphone or turn its gain down."
            )
        elif code == "quiet":
            sentence = f"It is quiet: the loudest moment is {t.peak_db:.0f}\u00a0dBFS. Move closer or turn the gain up."
        elif code == "noisy":
            sentence = (
                f"The room is noisy: between words it sits at {t.noise_db:.0f}\u00a0dBFS. "
                "Find a quieter spot or turn off what hums."
            )
        elif code == "no_speech":
            sentence = "No words were heard. Say the prompt after pressing Record, then press Stop."
        else:  # "words", the last code score() writes
            missed = word_errors(p.text, t.transcript or "").missed
            heard = f" It heard \u201c{t.transcript}\u201d." if t.transcript else ""
            sentence = (
                f"Some words were not the prompt's: {_quote(missed)}.{heard}"
                if missed
                else f"More was said than the prompt.{heard}"
            )
        out.append(Problem(code=code, sentence=sentence))
    return out


def level_problems(levels: WavLevels) -> list[str]:
    found: list[str] = []
    if levels.clipped > CLIPPED_SAMPLES:
        found.append("clipped")
    if levels.peak_db < QUIET_PEAK_DB:
        found.append("quiet")
    if levels.noise_db > NOISY_FLOOR_DB:
        found.append("noisy")
    return found


def transcribe(path: str) -> tuple[sm.Transcript, str | None] | None:
    """The take's transcript and the model that made it, or None when strata-models cannot answer now."""
    try:
        result, made = sm.run_with_provenance(
            ASR_ROLE,
            {"path": path, "language": LANGUAGE, "word_timestamps": True},
            APP,
            priority="high",  # someone is waiting at the microphone
            timeout=ASR_WAIT_SECONDS,
        )
    except (sm.Unavailable, TimeoutError, sm.JobFailed) as e:
        log.warning("take not transcribed: %s", e)
        return None
    return sm.Transcript.from_json(result), made.model


def score(db: Session, t: Take, p: Prompt, path: str) -> None:
    """Judge the take at `path` and store the verdict on its row (committed). Scoring again replaces the old one."""
    levels = measure(path)
    found = level_problems(levels)
    t.peak_db, t.noise_db, t.speech_db, t.clipped = levels.peak_db, levels.noise_db, levels.speech_db, levels.clipped
    heard = transcribe(path)
    t.transcript = t.asr_model = t.wer = t.speech_start = t.speech_end = None
    if heard is not None:
        transcript, t.asr_model = heard
        words = [w for s in transcript.segments for w in s.words]
        t.transcript = transcript.text
        if not words:
            found.append("no_speech")
        else:
            t.speech_start = round(max(0.0, words[0].start - PAD_BEFORE), 3)
            t.speech_end = round(min(levels.seconds, words[-1].end + PAD_AFTER), 3)
            if p.kind != curriculum.FREE_TALK:
                t.wer = wer = round(word_errors(p.text, transcript.text).wer, 4)
                if wer > MAX_WER:
                    found.append("words")
    t.problems = " ".join(found)
    t.verdict = RETRY if found else UNCHECKED if heard is None else GOOD
    t.scored = datetime.datetime.now(datetime.UTC)
    db.commit()
