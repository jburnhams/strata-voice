"""Recordings brought in (the Upload screen, `strata-voice ingest`): a found recording of the speaker, in any format,
turned into takes for the dataset beside the studio's.

A found recording is not a take: it is long, it was not made for this, its level is whatever it was, and it may hold
other people (an interviewer, a family table) and stretches of nothing. So each upload is processed in the background,
by the `ingest` job on strata-python's queue (`models.JOBS`), in five stages a person can watch:

1. **Decode and level** (ffmpeg, through `strata_python.media`): the first audio stream, mixed to one channel, at its
   own rate up to 48 kHz, lifted or lowered by one gain for the whole file so its loudest moment is at
   `TARGET_PEAK_DB`, written as one 24-bit WAV (`normalized.wav`). One gain and no compression: the voice's own
   dynamics are what a voice model learns, and every sentence keeps its level relative to the others.
2. **Transcribe** the whole recording once (strata-models' `transcribe`, word timings, Whisper's voice-activity filter
   so long silences are not "heard"). Waits for strata-models (`RetryLater`) rather than failing while it is down.
3. **Cut into sentences** (`sentences`): at each full stop, question or exclamation mark, at any pause over
   `GAP_SECONDS`, and a sentence over `MAX_SECONDS` again at its longest pause; under `MIN_SECONDS` or `MIN_WORDS` is
   too little to learn from. Each cut is padded as a studio crop is, but never into the next sentence's words.
4. **Whose voice** (strata-models' `speaker-embedding`, ECAPA): every sentence, and up to `REFERENCE_TAKES` of the
   speaker's good studio takes, in one call. Each sentence's similarity is to the mean of the studio takes; with none
   yet, to the voice that speaks most in this recording (the mean of every sentence, refined twice on the sentences
   that match it). If the role cannot answer, voices are not checked and every sentence is kept (`speaker_reference`
   null), which the screen says.
5. **Keep and judge**: each sentence becomes a prompt (`source` "upload", its text what was heard) and a take of its
   own WAV under `found/`, judged by `scoring.score` like a studio take: its levels, its words heard again on their
   own against the whole recording's, and its voice. A `retry` (someone else, a cut word, noise) is kept on disk but
   left out of the dataset, and the speaker can keep it anyway on the Takes screen, as in the studio.

The original stays as it came (`found/<id>/original.<ext>`): a master is never thrown away. Removing an upload removes
it, its WAVs and every take cut from it. An upload's prompts never enter the studio's queue (studio.py)."""

import datetime
import hashlib
import io
import logging
import math
import os
import re
import shutil
import wave
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session
from strata_python import media
from strata_python.clients import models as sm
from strata_python.contracts import ApiModel, Page, Task
from strata_python.files import inside, write_bytes_atomic
from strata_python.tasks.progress import report_progress
from strata_python.tasks.queue import Job, Queue
from strata_python.tasks.retry import RetryLater
from strata_python.wav import read_wav

from stratavoice import coverage, phonemes, scoring, settings, studio
from stratavoice.models import Prompt, Take, Upload

log = logging.getLogger(__name__)

KIND = "ingest"  # the job's kind on the queue
SOURCE = studio.UPLOADED  # Prompt.source of a sentence cut from an upload: never in the studio's queue
FOUND = "found"  # Prompt.kind, and the folder under the recordings folder
MAX_UPLOAD_BYTES = 4_000_000_000  # two hours of a WAV at 48 kHz stereo 24-bit is 2 GB; a video brings more
MAX_RATE = 48_000
TARGET_PEAK_DB = -1.0
MAX_GAIN_DB = 30.0  # a near-silent file is not lifted into hiss
GAP_SECONDS = 0.8
MIN_SECONDS = 1.0
MIN_WORDS = 2
MAX_SECONDS = 15.0  # voice models train on a few seconds to 15; longer is cut at its longest pause
SENTENCE_END = (".", "?", "!", "\u2026")
CLOSERS = "\"')\u201d\u2019"  # a sentence may end inside a quote or a bracket
REFERENCE_TAKES = 30
TRANSCRIBE_WAIT_SECONDS = 3600.0  # an hour of speech is a minute or two on the GPU; longer means a busy queue
MODELS_DOWN_RETRY_SECONDS = 600.0
SCORE_WAIT_SECONDS = 300.0
TEXT_MAX = 600  # Prompt.text


class NotConsented(ValueError):
    """Bringing in a recording before the speaker agreed to be recorded (a 400 with the sentence)."""


class UploadOut(ApiModel):
    """An upload and how far it has got: `job` is its ingest job (null for one whose job was pruned). Of its
    `sentences`, `kept` count in the dataset (with `kept_seconds` of speech), `other_voice` were someone else and
    `retry` had another problem (cut, unclear, noisy). `speaker_reference` is what voices were compared with: `studio`,
    `upload` (the voice that speaks most here) or null (not checked)."""

    id: int
    name: str
    created: datetime.datetime
    size_bytes: int
    seconds: float | None
    gain_db: float | None
    speaker_reference: str | None
    job: Task | None
    sentences: int
    kept: int
    other_voice: int
    retry: int
    kept_seconds: float


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _utc(t: datetime.datetime) -> datetime.datetime:
    return t.replace(tzinfo=datetime.UTC) if t.tzinfo is None else t.astimezone(datetime.UTC)


def _upload(db: Session, upload_id: int) -> Upload:
    u = db.get(Upload, upload_id)
    if u is None:
        raise KeyError(f"There is no upload {upload_id}.")
    return u


def _folder(u: Upload) -> str:
    return inside(u.root, f"{FOUND}/upload_{u.id:06d}")


def _out(db: Session, queue: Queue, u: Upload) -> UploadOut:
    rows = list(db.scalars(select(Take).where(Take.upload_id == u.id)))
    kept = [t for t in rows if t.verdict != scoring.RETRY or t.accepted]
    other = [t for t in rows if t.verdict == scoring.RETRY and not t.accepted and "speaker" in t.problems.split()]
    job = None if u.job_id is None else queue.get(u.job_id)
    seconds = sum(
        t.speech_end - t.speech_start
        if t.speech_start is not None and t.speech_end is not None
        else t.frames / t.sample_rate
        for t in kept
    )
    return UploadOut(
        id=u.id,
        name=u.name,
        created=_utc(u.created),
        size_bytes=u.size_bytes,
        seconds=u.seconds,
        gain_db=u.gain_db,
        speaker_reference=u.speaker_reference,
        job=None if job is None else job.to_task(),
        sentences=len(rows),
        kept=len(kept),
        other_voice=len(other),
        retry=len(rows) - len(kept) - len(other),
        kept_seconds=round(seconds, 2),
    )


def _clean_name(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/")).strip()
    return base[:300] or "recording"


def add_upload(db: Session, queue: Queue, name: str, src: str) -> UploadOut:
    """Keep the file at `src` (moved into the recordings folder) as an upload and queue its ingest job.

    Checked first, so a wrong file is refused with a sentence and not kept: the speaker agreed to be recorded, ffprobe
    finds a sound in it, and it was not brought in before (by its SHA-256)."""
    clean = _clean_name(name)
    try:
        if not settings.consented():
            raise NotConsented("Agree to be recorded first: nothing is kept until you do.")
        size = os.path.getsize(src)
        if size == 0:
            raise ValueError(f"{clean} is empty.")
        digest = _sha256(src)
        same = db.scalar(select(Upload).where(Upload.sha256 == digest))
        if same is not None:
            raise ValueError(f"{clean} was brought in already, as {same.name} on {_utc(same.created):%Y-%m-%d}.")
        try:
            info = media.probe(src)
        except media.MediaError:
            raise ValueError(f"{clean} is not a recording ffmpeg can read.") from None
        if info.audio is None:
            raise ValueError(f"{clean} has no sound in it.")
        u = Upload(name=clean, path="", root=settings.recordings_dir(), size_bytes=size, sha256=digest, created=_now())
        u.seconds = None if info.duration is None else round(info.duration, 3)
        db.add(u)
        db.flush()
        ext = os.path.splitext(clean)[1].lower()
        ext = ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else ""  # the format is ffprobe's to tell, not the name's
        u.path = f"{FOUND}/upload_{u.id:06d}/original{ext}"
        target = inside(u.root, u.path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(src, target)
    except BaseException:
        db.rollback()
        if os.path.exists(src):
            os.remove(src)
        raise
    db.commit()
    u.job_id = queue.enqueue(KIND, {"upload": u.id}, domain=f"upload:{u.id}", dedupe=True)
    db.commit()
    return _out(db, queue, u)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def uploads_page(db: Session, queue: Queue, after: int | None = None, limit: int = 20) -> Page[UploadOut]:
    """Uploads newest first, after the one with id `after` (a cursor, as for takes)."""
    q = select(Upload).order_by(Upload.id.desc()).limit(limit + 1)
    if after is not None:
        q = q.where(Upload.id < after)
    rows = list(db.scalars(q))
    items = [_out(db, queue, u) for u in rows[:limit]]
    return Page[UploadOut](items=items, next=str(items[-1].id) if len(rows) > limit else None)


def get_upload(db: Session, queue: Queue, upload_id: int) -> UploadOut:
    return _out(db, queue, _upload(db, upload_id))


def _remove_sentences(db: Session, u: Upload) -> None:
    """The takes and prompts cut from `u`, and their WAVs (before a re-run, and with the upload)."""
    takes = list(db.scalars(select(Take).where(Take.upload_id == u.id)))
    prompt_ids = {t.prompt_id for t in takes}
    for t in takes:
        path = inside(t.root or settings.recordings_dir(), t.path)
        if os.path.isfile(path):
            os.remove(path)
        db.delete(t)
    db.flush()
    if prompt_ids:
        db.execute(delete(Prompt).where(Prompt.id.in_(prompt_ids), Prompt.source == SOURCE))
    db.commit()


def remove_upload(db: Session, queue: Queue, upload_id: int) -> UploadOut:
    """Remove an upload: its job is cancelled, then its sentences, its folder (the original and the levelled WAV) and
    its row go. Files first, as for a take, so a file that cannot be removed leaves the upload listed to try again."""
    u = _upload(db, upload_id)
    gone = _out(db, queue, u)
    if u.job_id is not None:
        queue.cancel(u.job_id)
    _remove_sentences(db, u)
    folder = _folder(u)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    db.delete(u)
    db.commit()
    return gone


# --- the job -----------------------------------------------------------------------------------------------------------


def _peak_db(src: str, rate: int) -> float:
    """The loudest sample of the decoded mono mix, in dBFS: decoded to 16-bit as it streams, never held whole."""
    peak = [0]
    carry = [b""]

    def sink(chunk: bytes) -> None:
        data = carry[0] + chunk
        cut = len(data) - len(data) % 2
        carry[0] = data[cut:]
        a = array("h", data[:cut])
        if a:
            peak[0] = max(peak[0], max(a), -min(a))

    media.ffmpeg(["-i", src, "-vn", "-map", "0:a:0", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], sink=sink)
    return -120.0 if peak[0] == 0 else 20 * math.log10(min(peak[0], 32767) / 32767)


def level(src: str, out: str, source_rate: int | None) -> float:
    """Decode `src` to a mono 24-bit WAV at `out` (at its own rate, up to MAX_RATE) with one gain so its peak is
    `TARGET_PEAK_DB`. Returns the gain in dB."""
    rate = min(source_rate or MAX_RATE, MAX_RATE)
    gain = min(TARGET_PEAK_DB - _peak_db(src, rate), MAX_GAIN_DB)
    tmp = out + ".part.wav"
    media.ffmpeg(
        [
            "-i",
            src,
            "-vn",
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-af",
            f"volume={gain:.2f}dB",
            "-c:a",
            "pcm_s24le",
            tmp,
        ]
    )
    os.replace(tmp, out)
    return round(gain, 2)


@dataclass(frozen=True)
class Sentence:
    """A stretch of the recording to keep as one take: `start`/`end` are its words', `cut_start`/`cut_end` the padded
    cut (never into a neighbour's words)."""

    text: str
    start: float
    end: float
    cut_start: float
    cut_end: float
    words: int


def _ends_sentence(word: str) -> bool:
    return word.strip().rstrip(CLOSERS).endswith(SENTENCE_END)


def _split_long(run: list[sm.Word]) -> list[list[sm.Word]]:
    """A run over MAX_SECONDS cut at its longest pause between words (recursively)."""
    if len(run) < 2 or run[-1].end - run[0].start <= MAX_SECONDS:
        return [run]
    gaps = [(run[i + 1].start - run[i].end, i) for i in range(len(run) - 1)]
    _, at = max(gaps)
    return _split_long(run[: at + 1]) + _split_long(run[at + 1 :])


def sentences(words: list[sm.Word], seconds: float) -> list[Sentence]:
    """The recording's words cut into sentences to keep (module docstring, stage 3), in time order."""
    runs: list[list[sm.Word]] = []
    run: list[sm.Word] = []
    for i, w in enumerate(words):
        if not w.word.strip():
            continue
        run.append(w)
        nxt = next((x for x in words[i + 1 :] if x.word.strip()), None)
        if nxt is None or _ends_sentence(w.word) or nxt.start - w.end > GAP_SECONDS:
            runs.extend(_split_long(run))
            run = []
    pieces = [r for r in runs if r]
    out: list[Sentence] = []
    for k, r in enumerate(pieces):
        start, end = r[0].start, r[-1].end
        if end - start < MIN_SECONDS or len(r) < MIN_WORDS:
            continue
        before = pieces[k - 1][-1].end if k else 0.0
        after = pieces[k + 1][0].start if k + 1 < len(pieces) else seconds
        cut_start = max(start - scoring.PAD_BEFORE, (before + start) / 2, 0.0)
        cut_end = min(end + scoring.PAD_AFTER, (end + after) / 2, seconds)
        text = " ".join("".join(w.word for w in r).split())
        out.append(Sentence(text[:TEXT_MAX], start, end, round(cut_start, 3), round(cut_end, 3), len(r)))
    return out


def _cut(src: str, start: float, end: float) -> bytes:
    """The frames of the levelled WAV between `start` and `end` seconds, as a WAV of their own (lossless: a copy)."""
    with wave.open(src, "rb") as w:
        rate = w.getframerate()
        first = max(0, int(start * rate))
        w.setpos(min(first, w.getnframes()))
        frames = w.readframes(max(0, int(end * rate) - first))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(w.getsampwidth())
            o.setframerate(rate)
            o.writeframes(frames)
    return buf.getvalue()


def _references(db: Session) -> list[tuple[str, tuple[float, float] | None]]:
    """The speaker's newest good studio takes, each its crop: what an upload's voices are compared with."""
    q = (
        select(Take)
        .where(Take.upload_id.is_(None), (Take.verdict == scoring.GOOD) | Take.accepted)
        .order_by(Take.id.desc())
        .limit(REFERENCE_TAKES)
    )
    out: list[tuple[str, tuple[float, float] | None]] = []
    for t in db.scalars(q):
        path = inside(t.root or settings.recordings_dir(), t.path)
        if os.path.isfile(path):
            crop = None if t.speech_start is None or t.speech_end is None else (t.speech_start, t.speech_end)
            out.append((path, crop))
    return out


def _mean(vectors: list[list[float]], weights: list[float] | None = None) -> list[float]:
    ws = weights or [1.0] * len(vectors)
    m = [sum(w * v[i] for v, w in zip(vectors, ws, strict=True)) for i in range(len(vectors[0]))]
    n = math.sqrt(sum(x * x for x in m)) or 1.0
    return [x / n for x in m]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def voices(
    sentence_vectors: list[list[float] | None], weights: list[float], reference_vectors: list[list[float] | None]
) -> tuple[list[float | None], str]:
    """Each sentence's similarity to the speaker, and what the speaker's voice was taken from (stage 4)."""
    refs = [v for v in reference_vectors if v is not None]
    known = [(v, w) for v, w in zip(sentence_vectors, weights, strict=True) if v is not None]
    if refs:
        centre, source = _mean(refs), "studio"
    elif known:
        centre, source = _mean([v for v, _ in known], [w for _, w in known]), SOURCE
        for _ in range(2):  # the voice that speaks most: drop the sentences unlike the mean, and take the mean again
            near = [(v, w) for v, w in known if _dot(v, centre) >= scoring.MIN_SPEAKER_SIMILARITY]
            if near:
                centre = _mean([v for v, _ in near], [w for _, w in near])
    else:
        return [None] * len(sentence_vectors), SOURCE
    return [None if v is None else round(_dot(v, centre), 4) for v in sentence_vectors], source


def _transcribe(path: str) -> tuple[sm.Transcript, str | None]:
    try:
        result, made = sm.run_with_provenance(
            scoring.ASR_ROLE,
            {"path": path, "language": scoring.LANGUAGE, "word_timestamps": True, "vad_filter": True},
            scoring.APP,
            timeout=TRANSCRIBE_WAIT_SECONDS,
        )
    except (sm.Unavailable, TimeoutError) as e:
        raise RetryLater(
            f"strata-models cannot transcribe now ({e}); trying again", after_s=MODELS_DOWN_RETRY_SECONDS
        ) from e
    return sm.Transcript.from_json(result), made.model


def _embed(items: list[tuple[str, tuple[float, float] | None]]) -> list[list[float] | None] | None:
    """One voice vector per item, or None when strata-models cannot measure voices (not installed, down, failed)."""
    try:
        got = sm.SpeakerEmbeddings.from_json(sm.speaker_embeddings(items, scoring.APP))
    except (sm.Unavailable, TimeoutError, sm.JobFailed) as e:
        log.warning("voices not checked: %s", e)
        return None
    return got.embeddings if len(got.embeddings) == len(items) else None


def process(db: Session, upload_id: int, stopping: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """Run the five stages on one upload (the module docstring). Run again, it starts over: the sentences of an
    earlier attempt are removed first, so a retried job never keeps two copies."""
    u = _upload(db, upload_id)
    _remove_sentences(db, u)
    original = inside(u.root, u.path)
    report_progress(0, None, "Decoding and levelling", "decode")
    info = media.probe(original)
    levelled = os.path.join(_folder(u), "normalized.wav")
    u.gain_db = level(original, levelled, None if info.audio is None else info.audio.sample_rate)
    u.normalized = os.path.relpath(levelled, u.root).replace(os.sep, "/")
    seconds = u.seconds = round(read_wav(levelled).seconds, 3)
    db.commit()

    report_progress(0, None, "Transcribing the whole recording", "transcribe")
    transcript, u.asr_model = _transcribe(levelled)
    u.transcript = transcript.text
    db.commit()
    words = [w for s in transcript.segments for w in s.words]
    found = sentences(words, seconds)
    report_progress(0, None, f"{len(found)} sentences; checking whose voice each is", "voices")
    if stopping():
        return {"sentences": 0, "stopped": True}

    vectors = _embed([(levelled, (s.start, s.end)) for s in found] + _references(db)) if found else None
    if vectors is None:  # nothing to compare, or strata-models could not measure voices
        similarity: list[float | None] = [None] * len(found)
        u.speaker_reference = None
    else:
        similarity, u.speaker_reference = voices(
            vectors[: len(found)], [s.end - s.start for s in found], vectors[len(found) :]
        )
    db.commit()

    base = db.scalar(select(func.max(Prompt.position))) or 0
    kept = 0
    for i, (s, sim) in enumerate(zip(found, similarity, strict=True)):
        if stopping():
            break
        report_progress(i, len(found), f"Judging sentence {i + 1} of {len(found)}", "judge")
        p = Prompt(
            key=f"upload-{u.id:06d}-{i + 1:04d}",
            text=s.text,
            kind=FOUND,
            cue=None,
            partition="train",
            source=SOURCE,
            position=base + i + 1,
            created=_now(),
            phonemes=phonemes.ipa_or_none(s.text),
        )
        db.add(p)
        db.flush()
        data = _cut(levelled, s.cut_start, s.cut_end)
        wav = read_wav(data)
        t = Take(
            prompt_id=p.id,
            path="",
            sample_rate=wav.sample_rate,
            sample_width=wav.sample_width,
            frames=wav.frames,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            device=f"upload: {u.name}"[:200],
            created=_now(),
        )
        t.root, t.upload_id, t.speaker_similarity = u.root, u.id, sim
        t.source_start, t.source_end = s.cut_start, s.cut_end
        db.add(t)
        db.flush()
        t.path = f"{FOUND}/take_{t.id:06d}.wav"
        target = inside(t.root, t.path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        write_bytes_atomic(target, data)
        db.commit()
        scoring.score(db, t, p, target, priority="normal", wait=SCORE_WAIT_SECONDS)
        kept += t.verdict != scoring.RETRY
    report_progress(len(found), len(found), f"{kept} of {len(found)} sentences kept", "done")
    if kept:
        coverage.rank(db)  # once per upload: its sentences change what is still missing
    return {"sentences": len(found), "kept": kept, "speaker_reference": u.speaker_reference}


def handler(engine: Callable[[], Engine]) -> Callable[[Job], Any]:
    """The queue's `ingest` handler on the server's (or the CLI's) database."""

    def run(job: Job) -> Any:
        with Session(engine()) as s:
            return process(s, int(job.options["upload"]), lambda: job.stopping)

    return run
