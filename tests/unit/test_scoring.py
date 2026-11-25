"""scoring.py against real WAV files and a stand-in strata-models over real HTTP (`models`, the plugin's
fake_models): each verdict, each problem's sentence, the crop, and what a verdict does to the queue and manifest."""

import pytest
from sqlalchemy.orm import Session
from strata_python.testing import FakeModels
from takes import heard, speech

from stratavoice import scoring, settings, studio


@pytest.fixture
def consented() -> None:
    settings.SETTINGS.save({"consented_on": "2026-11-24"})


def _read(db: Session) -> studio.PromptOut:
    """The first prompt in the queue."""
    return studio.prompts(db)[0]


def test_a_take_said_as_written_is_good_and_cropped(db_session: Session, consented: None, models: FakeModels):
    models.down = False
    prompt = _read(db_session)
    models.results["transcribe"] = heard(prompt.text.upper(), start=0.3, end=0.9)  # case and punctuation do not count
    kept = studio.add_take(db_session, prompt.id, speech(1.2))
    assert kept.verdict is None  # kept first, judged after

    t = studio.score_take(db_session, kept.id)
    assert (t.verdict, t.problems, t.wer, t.clipped) == ("good", [], 0.0, 0)
    assert (t.speech_start, t.speech_end) == (0.15, 1.15)  # 0.15 s before the first word, 0.25 s after the last
    assert t.peak_db == pytest.approx(-10.5, abs=0.2)
    assert t.noise_db == -100.0  # the quiet before and after is digital silence
    (job,) = models.jobs
    assert job["role"] == "transcribe"
    assert job["priority"] == "high"
    assert job["params"] == {"path": studio.take_file(db_session, kept.id), "language": "en", "word_timestamps": True}

    assert prompt.id not in [p.id for p in studio.upcoming(db_session)]
    record = next(r for r in studio.manifest(db_session) if r["prompt"]["key"] == prompt.key)
    assert record["speech"] == {"start": 0.15, "end": 1.15}
    assert record["asr"] == {"model": "fake-transcribe", "hypothesis": prompt.text.upper()}
    assert record["quality"]["verdict"] == "good"
    assert (record["quality"]["clipping"], record["quality"]["noise_ok"]) == (False, True)


def test_a_misread_take_is_asked_for_again_unless_kept_anyway(db_session: Session, consented: None, models: FakeModels):
    models.down = False
    prompt = _read(db_session)
    words = prompt.text.split()
    models.results["transcribe"] = heard(" ".join(["Mumble", *words[1:-1]]))  # first word wrong, last left out
    t = studio.score_take(db_session, studio.add_take(db_session, prompt.id, speech()).id)
    assert t.verdict == "retry"
    assert t.wer is not None
    assert t.wer > scoring.MAX_WER
    (problem,) = t.problems
    assert problem.code == "words"
    first, last = (w.strip(".,!?;:\u2019'\u201c\u201d").lower() for w in (words[0], words[-1]))
    assert problem.sentence.startswith(f"Some words were not the prompt's: \u201c{first}\u201d, \u201c{last}\u201d.")
    assert "It heard \u201cMumble" in problem.sentence
    assert prompt.id in [p.id for p in studio.upcoming(db_session)]  # back in the queue: the studio asks again
    assert studio.progress(db_session).recorded == 0
    assert all(r["prompt"]["key"] != prompt.key for r in studio.manifest(db_session))  # not in the dataset

    assert studio.accept_take(db_session, t.id).accepted is True  # kept anyway: a name the recogniser does not know
    assert prompt.id not in [p.id for p in studio.upcoming(db_session)]
    assert next(r for r in studio.manifest(db_session) if r["prompt"]["key"] == prompt.key)["quality"]["accepted"]
    studio.accept_take(db_session, t.id, accepted=False)
    assert prompt.id in [p.id for p in studio.upcoming(db_session)]


def test_chatter_around_the_prompt_is_cropped_out_and_more_said_inside_it_or_nothing_said(
    db_session: Session, consented: None, models: FakeModels
):
    models.down = False
    prompt = _read(db_session)
    # Chatter before and after the reading (a hands-free take): cropped out, not a fault.
    words = prompt.text.split()
    models.results["transcribe"] = heard(f"sorry {words[0]} sorry again {prompt.text} right next one", 0.2, 2.2)
    around = studio.score_take(db_session, studio.add_take(db_session, prompt.id, speech(2.5)).id)
    step = 2.0 / (len(words) + 7)
    assert (around.verdict, around.wer) == ("good", 0.0)
    assert around.speech_start == pytest.approx(0.2 + 4 * step - scoring.PAD_BEFORE, abs=0.002)
    assert around.speech_end == pytest.approx(0.2 + (4 + len(words)) * step + scoring.PAD_AFTER, abs=0.002)

    # Words inside the reading that are not the prompt's still count.
    inserted = " ".join([*words[:4], "um", "er", *words[4:]])
    models.results["transcribe"] = heard(inserted)
    (extra,) = studio.score_take(db_session, studio.add_take(db_session, prompt.id, speech()).id).problems
    assert extra.sentence.startswith("More was said than the prompt. It heard")

    models.results["transcribe"] = heard("")
    silent = studio.score_take(db_session, studio.add_take(db_session, prompt.id, speech()).id)
    assert (silent.verdict, [p.code for p in silent.problems]) == ("retry", ["no_speech"])
    assert (silent.speech_start, silent.transcript) == (None, "")
    assert silent.problems[0].sentence == "No words were heard. Say the prompt after pressing Record, then press Stop."


@pytest.mark.parametrize(
    ("wav", "codes", "sentence"),
    [
        (speech(amplitude=1.4), ["clipped"], "It clipped: "),
        (speech(amplitude=0.02), ["quiet"], "It is quiet: the loudest moment is -34\u00a0dBFS. Move closer"),
        (speech(noise=0.02), ["noisy"], "The room is noisy: between words it sits at -39\u00a0dBFS."),
    ],
)
def test_level_problems_are_found_without_the_models_service(
    db_session: Session, consented: None, models: FakeModels, wav: bytes, codes: list[str], sentence: str
):
    t = studio.score_take(db_session, studio.add_take(db_session, _read(db_session).id, wav).id)
    assert (t.verdict, [p.code for p in t.problems]) == ("retry", codes)
    assert t.problems[0].sentence.startswith(sentence)
    assert (t.transcript, t.asr_model) == (None, None)  # strata-models was down
    assert studio.unscored(db_session) == [t.id]  # its words are still to hear


def test_a_clean_take_is_unchecked_when_the_service_cannot_answer(
    db_session: Session, consented: None, models: FakeModels
):
    prompt = _read(db_session)
    t = studio.score_take(db_session, studio.add_take(db_session, prompt.id, speech()).id)
    assert (t.verdict, t.problems) == ("unchecked", [])
    assert prompt.id not in [p.id for p in studio.upcoming(db_session)]  # never held up by the service
    assert studio.unscored(db_session) == [t.id]

    models.down = False
    models.fail("CUDA out of memory")  # a job that fails is the same: kept, checked later
    assert studio.score_take(db_session, t.id).verdict == "unchecked"
    models.results["transcribe"] = heard(prompt.text)
    assert studio.score_take(db_session, t.id).verdict == "good"
    assert studio.unscored(db_session) == []
