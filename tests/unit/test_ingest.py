"""ingest.py: a found recording brought in, levelled, transcribed, cut into sentences, checked for whose voice each is,
judged and kept as takes. ffmpeg runs for real on a FLAC made here; strata-models is `fake_models` (over real HTTP),
answering the whole recording's words, each cut sentence's words and the voice vectors from the job's params."""

import os
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from strata_python import media
from strata_python.clients import models as sm
from strata_python.tasks.queue import Queue
from strata_python.testing import FakeModels
from strata_python.wav import measure, read_wav
from takes import OTHER_VOICE, RECORDING, RECORDING_SECONDS, found_heard, found_voices, recording, speech

from stratavoice import ingest, scoring, settings, studio
from stratavoice.models import JOBS, Prompt, Take, Upload


@pytest.fixture
def consented() -> None:
    settings.SETTINGS.save({"consented_on": "2026-11-23"})


@pytest.fixture
def queue(db_engine: Engine) -> Queue:
    return Queue(db_engine, JOBS, retries=2)


@pytest.fixture
def heard_all(models: FakeModels, db_engine: Engine) -> FakeModels:
    models.down = False
    models.results["transcribe"] = found_heard(lambda: Session(db_engine))
    models.results["speaker-embedding"] = found_voices
    return models


def _bring(db: Session, queue: Queue, tmp_path: Any, name: str = "kitchen.flac") -> ingest.UploadOut:
    return ingest.add_upload(db, queue, name, recording(str(tmp_path / "in.flac")))


def _run(queue: Queue, engine: Engine) -> Any:
    job = queue.step({ingest.KIND: ingest.handler(lambda: engine)})
    assert job is not None
    return queue.get(job.id)


def test_a_recording_becomes_judged_sentences_and_someone_else_is_left_out(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    up = _bring(db_session, queue, tmp_path)
    assert up.job is not None
    assert up.job.state == "queued"
    assert up.sentences == 0
    assert up.seconds == pytest.approx(RECORDING_SECONDS, abs=0.05)
    done = _run(queue, db_engine)
    assert done.state == "done", done.error
    assert done.result == {
        "sentences": 3,
        "kept": 2,
        "speaker_reference": "upload",
    }  # no studio takes: the voice that speaks most

    u = db_session.get(Upload, up.id)
    assert u is not None
    db_session.refresh(u)
    levelled = os.path.join(u.root, u.normalized or "")
    info = read_wav(levelled)
    assert (info.channels, info.sample_rate, info.sample_width) == (1, 44_100, 3)  # one channel, its own rate, 24-bit
    assert measure(levelled).peak_db == pytest.approx(ingest.TARGET_PEAK_DB, abs=0.3)
    assert u.gain_db is not None
    assert u.gain_db > 20
    assert u.transcript
    assert u.transcript.startswith("The kettle")
    assert os.path.isfile(os.path.join(u.root, u.path))
    assert u.path.endswith("original.flac")

    takes = studio.takes_page(db_session, upload=up.id).items
    assert [t.prompt_text for t in takes] == [text for _, _, text in RECORDING]
    assert [t.verdict for t in takes] == ["good", "retry", "good"]
    assert [p.code for p in takes[OTHER_VOICE].problems] == ["speaker"]
    assert "sounds like someone else" in takes[OTHER_VOICE].problems[0].sentence
    first = takes[0]
    assert (first.upload_id, first.kind, first.speaker_similarity) == (up.id, ingest.FOUND, 1.0)
    assert first.source_start == pytest.approx(RECORDING[0][0] - scoring.PAD_BEFORE, abs=0.01)
    assert first.seconds == pytest.approx(2.0 + scoring.PAD_BEFORE + scoring.PAD_AFTER, abs=0.01)

    out = ingest.get_upload(db_session, queue, up.id)
    assert (out.sentences, out.kept, out.other_voice, out.retry) == (3, 2, 1, 0)
    assert out.kept_seconds > 4
    assert out.job is not None
    assert out.job.state == "done"

    # The studio's queue and progress are untouched; coverage and the manifest see the kept sentences.
    assert all(p.source != ingest.SOURCE for p in studio.upcoming(db_session, 200))
    assert studio.progress(db_session).recorded == 0
    found = [r for r in studio.manifest(db_session) if r["source"] == "found"]
    assert [r["text"] for r in found] == [RECORDING[0][2], RECORDING[2][2]]
    assert found[0]["found"]["upload"] == up.id
    assert found[0]["elicitation"]["mode"] == "found"

    # Keeping the other voice's sentence anyway puts it in the dataset, as for a studio take.
    studio.accept_take(db_session, takes[OTHER_VOICE].id)
    assert ingest.get_upload(db_session, queue, up.id).kept == 3


def test_voices_are_compared_with_the_studio_takes_when_there_are_some(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    studio.seed(db_session)
    prompt = studio.upcoming(db_session, 1)[0]
    kept = studio.add_take(db_session, prompt.id, speech(1.0))
    t = db_session.get(Take, kept.id)
    assert t is not None
    t.verdict, t.speech_start, t.speech_end = scoring.GOOD, 0.1, 0.9
    db_session.commit()
    _bring(db_session, queue, tmp_path)
    asked: list[int] = []
    voices = found_voices

    def counting(params: dict[str, Any]) -> dict[str, Any]:
        asked.append(len(params["items"]))
        return voices(params)

    heard_all.results["speaker-embedding"] = counting
    done = _run(queue, db_engine)
    assert done.result["speaker_reference"] == "studio"
    assert done.result["kept"] == 2
    assert asked == [4]  # three sentences and the one studio take, in one call


def test_voices_not_measured_keeps_every_sentence(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    heard_all.fail("unknown role speaker-embedding", role="speaker-embedding")
    up = _bring(db_session, queue, tmp_path)
    done = _run(queue, db_engine)
    assert done.result == {"sentences": 3, "kept": 3, "speaker_reference": None}
    assert all(t.speaker_similarity is None for t in studio.takes_page(db_session, upload=up.id).items)


def test_the_job_waits_for_strata_models_and_a_retry_starts_over(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, models: FakeModels, tmp_path: Any
):
    up = _bring(db_session, queue, tmp_path)
    waiting = _run(queue, db_engine)
    assert waiting.state == "queued"
    assert waiting.run_after is not None
    assert "cannot transcribe now" in (waiting.error or "")
    models.down = False
    models.results["transcribe"] = found_heard(lambda: Session(db_engine))
    models.results["speaker-embedding"] = found_voices
    with db_engine.begin() as c:
        c.execute(JOBS.update().values(run_after=None))
    assert _run(queue, db_engine).state == "done"
    first = [t.id for t in studio.takes_page(db_session, upload=up.id).items]
    with Session(db_engine) as s:  # run again (a retried job): the sentences are made again, never twice
        ingest.process(s, up.id)
    again = studio.takes_page(db_session, upload=up.id).items
    assert len(again) == 3
    assert not set(first) & {t.id for t in again}
    assert db_session.scalar(select(Prompt).where(Prompt.key == f"upload-{up.id:06d}-0001")) is not None


def test_a_stopped_job_keeps_what_it_had(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    up = _bring(db_session, queue, tmp_path)
    with Session(db_engine) as s:
        assert ingest.process(s, up.id, lambda: True) == {"sentences": 0, "stopped": True}


def test_what_is_refused_is_not_kept(db_session: Session, queue: Queue, tmp_path: Any, consented: None):
    def bring(name: str, data: bytes) -> None:
        src = tmp_path / "in.part"
        src.write_bytes(data)
        try:
            ingest.add_upload(db_session, queue, name, str(src))
        finally:
            assert not src.exists()  # refused or kept, the incoming copy is gone

    with pytest.raises(ValueError, match=r"notes\.txt is not a recording ffmpeg can read"):
        bring("notes.txt", b"shopping: milk, eggs")
    with pytest.raises(ValueError, match="empty"):
        bring("blank.wav", b"")
    picture = tmp_path / "p.png"
    media.ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=16x16", "-frames:v", "1", str(picture)])
    with pytest.raises(ValueError, match="no sound"):
        bring("p.png", picture.read_bytes())
    ok = recording(str(tmp_path / "talk.flac"))
    with open(ok, "rb") as f:
        data = f.read()
    bring("C:\\Users\\ada\\talk.flac", data)
    with pytest.raises(ValueError, match=r"brought in already, as talk\.flac on"):
        bring("again.flac", data)
    assert [u.name for u in ingest.uploads_page(db_session, queue).items] == ["talk.flac"]


def test_nothing_is_brought_in_without_consent(db_session: Session, queue: Queue, tmp_path: Any):
    with pytest.raises(ingest.NotConsented):
        _bring(db_session, queue, tmp_path)
    assert db_session.scalar(select(Upload)) is None


def test_uploads_are_paged_and_removed_with_their_files(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    first = _bring(db_session, queue, tmp_path, "one.flac")
    _run(queue, db_engine)
    second = ingest.add_upload(db_session, queue, "two.flac", recording(str(tmp_path / "b.flac"), amplitude=0.06))
    page = ingest.uploads_page(db_session, queue, limit=1)
    assert [u.id for u in page.items] == [second.id]
    assert page.next == str(second.id)
    assert [u.id for u in ingest.uploads_page(db_session, queue, after=second.id).items] == [first.id]

    u = db_session.get(Upload, first.id)
    assert u is not None
    folder = os.path.join(u.root, f"found/upload_{u.id:06d}")
    files = [os.path.join(u.root, t.path) for t in db_session.scalars(select(Take).where(Take.upload_id == u.id))]
    assert os.path.isdir(folder)
    assert all(os.path.isfile(f) for f in files)
    assert len(files) == 3
    gone = ingest.remove_upload(db_session, queue, first.id)
    assert gone.sentences == 3
    assert not os.path.exists(folder)
    assert not any(os.path.exists(f) for f in files)
    assert db_session.scalar(select(Prompt).where(Prompt.source == ingest.SOURCE)) is None
    ingest.remove_upload(db_session, queue, second.id)  # still queued: its job is cancelled
    assert second.job is not None
    job = queue.get(int(second.job.id))
    assert job is not None
    assert job.state == "cancelled"
    with pytest.raises(KeyError, match="no upload"):
        ingest.get_upload(db_session, queue, first.id)


def _w(start: float, end: float, word: str) -> sm.Word:
    return sm.Word(start, end, f" {word}", 0.9)


def test_sentences_end_at_stops_and_pauses_and_long_ones_split_at_their_longest_pause():
    words = [
        _w(0.0, 0.5, "Hello"), _w(0.6, 1.1, "there."),                              # a stop
        _w(1.2, 1.7, "Right"), _w(1.8, 2.4, "then"),                                # a pause ends it
        _w(3.4, 3.6, "so"),                                                         # one word: too little
        _w(5.0, 5.5, "\u201cWell,"), _w(5.6, 6.1, "maybe.\u201d"),                  # a stop inside a quote
        _w(7.0, 7.1, ""), _w(7.2, 7.5, "um"), _w(7.6, 7.7, "ok"),                   # under MIN_SECONDS
    ]  # fmt: skip
    got = ingest.sentences(words, 10.0)
    assert [s.text for s in got] == ["Hello there.", "Right then", "\u201cWell, maybe.\u201d"]
    first, second = got[0], got[1]
    assert (first.cut_start, first.start, first.end, first.words) == (0.0, 0.0, 1.1, 2)
    assert first.cut_end == pytest.approx(1.15)  # halfway to the next sentence's first word, not past it
    assert second.cut_start == pytest.approx(1.15)
    assert second.cut_end == pytest.approx(2.4 + scoring.PAD_AFTER)

    long = [_w(i * 0.5, i * 0.5 + 0.4, f"w{i}") for i in range(20)] + [_w(10.6, 11.0, "w20"), _w(11.1, 11.5, "w21")]
    long += [_w(11.6 + i * 0.5, 12.0 + i * 0.5, f"x{i}") for i in range(10)]
    parts = ingest.sentences(long, 20.0)
    assert len(parts) == 2
    assert all(p.end - p.start <= ingest.MAX_SECONDS for p in parts)
    assert parts[0].text.endswith("w19")
    assert parts[1].text.startswith("w20")


def test_voices_against_the_studio_or_the_voice_that_speaks_most():
    a, b = [1.0, 0.0], [0.0, 1.0]
    sims, ref = ingest.voices([a, b, None], [1.0, 1.0, 1.0], [a, None])
    assert (sims, ref) == ([1.0, 0.0, None], "studio")
    sims, ref = ingest.voices([a, a, b], [3.0, 3.0, 2.0], [])
    assert ref == "upload"
    assert sims[0] == 1.0
    assert sims[2] == 0.0
    assert ingest.voices([None], [1.0], []) == ([None], "upload")


def test_level_lifts_a_quiet_file_but_not_into_hiss(tmp_path: Any):
    quiet = recording(str(tmp_path / "q.flac"), amplitude=0.0005)
    out = str(tmp_path / "q.wav")
    assert ingest.level(quiet, out, 96_000) == ingest.MAX_GAIN_DB
    assert read_wav(out).sample_rate == ingest.MAX_RATE  # never above 48 kHz
    silent = tmp_path / "s.wav"
    from strata_python.testing import sine_wav

    silent.write_bytes(sine_wav(0.0, tail=1.0))
    assert ingest.level(str(silent), str(tmp_path / "s2.wav"), None) == ingest.MAX_GAIN_DB


def test_a_recording_with_no_words_keeps_nothing_and_a_stop_ends_between_sentences(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    first = _bring(db_session, queue, tmp_path, "music.flac")
    whole = heard_all.results["transcribe"]
    heard_all.results["transcribe"] = lambda params: {"language": "en", "duration": 9.0, "segments": []}
    done = _run(queue, db_engine)
    assert done.result == {"sentences": 0, "kept": 0, "speaker_reference": None}
    heard_all.results["transcribe"] = whole
    second = ingest.add_upload(db_session, queue, "two.flac", recording(str(tmp_path / "b.flac"), amplitude=0.06))
    asked = iter([False, False, True])  # after the voices are checked, and after the first sentence is kept
    with Session(db_engine) as s:
        assert ingest.process(s, second.id, lambda: next(asked))["sentences"] == 3
    assert len(studio.takes_page(db_session, upload=second.id).items) == 1
    assert ingest.get_upload(db_session, queue, first.id).sentences == 0


def test_removing_an_upload_whose_files_are_already_gone(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    import shutil

    up = _bring(db_session, queue, tmp_path)
    _run(queue, db_engine)
    u = db_session.get(Upload, up.id)
    assert u is not None
    shutil.rmtree(os.path.join(u.root, "found"))
    u.job_id = None
    db_session.commit()
    assert ingest.remove_upload(db_session, queue, up.id).job is None
    assert db_session.get(Upload, up.id) is None


def test_a_studio_take_whose_file_is_gone_is_not_a_reference(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    studio.seed(db_session)
    kept = studio.add_take(db_session, studio.upcoming(db_session, 1)[0].id, speech(1.0))
    t = db_session.get(Take, kept.id)
    assert t is not None
    t.verdict = scoring.GOOD
    db_session.commit()
    os.remove(os.path.join(t.root, t.path))
    _bring(db_session, queue, tmp_path)
    assert _run(queue, db_engine).result["speaker_reference"] == "upload"


def test_voices_when_no_sentence_is_near_the_mean():
    sims, ref = ingest.voices([[1.0, 0.0], [0.0, 1.0]], [1.0, 1.0], [])
    assert ref == "upload"
    assert sims == [0.7071, 0.7071]  # two voices, evenly: both near enough the middle to stay


def test_sentences_of_one_upload_page_in_the_order_said(
    db_session: Session, db_engine: Engine, consented: None, queue: Queue, heard_all: FakeModels, tmp_path: Any
):
    up = _bring(db_session, queue, tmp_path)
    _run(queue, db_engine)
    first = studio.takes_page(db_session, limit=1, upload=up.id)
    assert first.next is not None
    rest = studio.takes_page(db_session, after=int(first.next), upload=up.id).items
    assert [t.prompt_text for t in first.items + rest] == [text for _, _, text in RECORDING]
