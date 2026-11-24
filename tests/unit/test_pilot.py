"""pilot.py over real takes: WAVs written by the studio, judged by scoring.py against a stand-in strata-models."""

import datetime

import pytest
from sqlalchemy.orm import Session
from strata_python.testing import FakeModels, sine_wav
from takes import heard, speech

from stratavoice import pilot, scoring, settings, studio
from stratavoice.models import Take


@pytest.fixture
def consented() -> None:
    settings.SETTINGS.save({"consented_on": "2026-11-24"})


def _at(db: Session, take_id: int, when: datetime.datetime) -> None:
    db.get_one(Take, take_id).created = when
    db.commit()


def test_nothing_recorded_yet(db_session: Session):
    p = pilot.report(db_session)
    assert (p.takes, p.started, p.speech_per_minute, p.lead) == (0, None, None, None)
    assert all(c.spread is None and c.measured == 0 for c in p.checks)
    assert pilot.describe(p) == ["No takes yet: record a session in the studio, then run this again."]


def test_a_session_against_each_threshold(db_session: Session, consented: None, models: FakeModels):
    studio.seed(db_session)
    read = [p for p in studio.prompts(db_session) if p.kind == "phonetic"][:3]
    start = datetime.datetime(2026, 11, 24, 9, 0, tzinfo=datetime.UTC)

    old = studio.add_take(db_session, read[0].id, speech())  # yesterday's session: not in the report
    _at(db_session, old.id, start - datetime.timedelta(days=1))

    models.down = False
    models.results["transcribe"] = heard(read[0].text)
    good = studio.add_take(db_session, read[0].id, speech(2.0))
    studio.score_take(db_session, good.id)
    models.results["transcribe"] = heard("something else entirely")
    wrong = studio.add_take(db_session, read[1].id, speech(2.0))
    studio.score_take(db_session, wrong.id)
    studio.accept_take(db_session, wrong.id)
    models.results["transcribe"] = heard(read[2].text)
    talk = studio.add_take(db_session, read[2].id, speech(2.0))
    studio.score_take(db_session, talk.id)
    models.results["transcribe"] = heard(read[0].text)
    again = studio.add_take(db_session, read[0].id, speech(2.0))  # Record again after a good take: only one is kept
    studio.score_take(db_session, again.id)
    noisy = studio.add_take(db_session, read[1].id, sine_wav(1.0))  # no quiet at all; never scored
    for i, t in enumerate((good, wrong, talk, again, noisy)):
        _at(db_session, t.id, start + datetime.timedelta(minutes=2 * i))

    p = pilot.report(db_session)
    assert (p.takes, p.prompts, p.again) == (5, 3, 2)
    assert p.verdicts == {"good": 3, "retry": 1, "unchecked": 0, "unscored": 1}
    assert p.accepted == 1
    assert p.started == start - datetime.timedelta(seconds=2)
    assert p.minutes == 8.0
    # Each prompt's newest usable take, as the manifest exports: `again` and `talk`. The second prompt's newest is the
    # unscored take, which counts but has no crop yet.
    assert p.speech_seconds == pytest.approx(2 * (0.9 + 0.25 - 0.15), abs=0.05)
    assert p.speech_per_minute == pytest.approx(p.speech_seconds / 8.0, abs=0.05)
    assert p.lead is not None
    assert p.lead.median == pytest.approx(0.15)  # the first word at 0.3 s, less PAD_BEFORE
    checks = {c.code: c for c in p.checks}
    words = checks["words"]
    assert (words.measured, words.failed, words.limit) == (4, 1, scoring.MAX_WER)
    peak = checks["quiet"]
    assert (peak.measured, peak.failed, peak.fails_when) == (4, 0, "below")
    assert checks["clipped"].near == 0

    lines = pilot.describe(p)
    assert lines[0].startswith("Session 2026-11-24 08:59 to 09:08 UTC, 8 min: 5 take(s) of 3 prompt(s)")
    assert "1 retry (1 kept anyway)" in lines[1]
    assert any(line.startswith("Word error rate: limit 0.1 share (fails above)") for line in lines)
    assert lines[-1].startswith("Some takes are not fully judged")
    judged = p.model_copy(update={"verdicts": {**p.verdicts, "unscored": 0}})
    assert not pilot.describe(judged)[-1].startswith("Some takes")

    since = pilot.report(db_session, since=(start - datetime.timedelta(days=1)).date())
    assert since.takes == 6


def test_a_break_starts_a_new_session(db_session: Session, consented: None):
    studio.seed(db_session)
    prompt = studio.prompts(db_session)[0]
    start = datetime.datetime(2026, 11, 24, 9, 0, tzinfo=datetime.UTC)
    ids = [studio.add_take(db_session, prompt.id, speech()).id for _ in range(3)]
    for t, minutes in zip(ids, (0, 31, 60), strict=True):  # a break of 31 minutes, then 29
        _at(db_session, t, start + datetime.timedelta(minutes=minutes))
    assert [t.id for t in pilot.session(db_session)] == ids[1:]
    p = pilot.report(db_session)
    assert (p.verdicts["unscored"], p.speech_seconds, p.lead) == (2, 0.0, None)  # not scored: nothing measured
    assert "Word error rate: nothing measured." in pilot.describe(p)


@pytest.mark.parametrize(
    ("values", "failed", "near"),
    [([-20.0, -26.0, -31.0], 1, 1), ([-29.0], 0, 1), ([], 0, 0)],
)
def test_a_check_counts_failures_and_near_misses(values: list[float], failed: int, near: int):
    c = pilot._check("quiet", "Peak level", -30.0, "dBFS", True, 6.0, values)  # pyright: ignore[reportPrivateUsage]
    assert (c.failed, c.near, c.measured) == (failed, near, len(values))
