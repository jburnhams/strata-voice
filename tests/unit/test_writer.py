"""writer.py against a stand-in strata-models over real HTTP (`models`): the brief it sends, the candidates it keeps
and drops, and each way the writer can fail."""

import pytest
from prompts import candidate, offer
from sqlalchemy import select
from sqlalchemy.orm import Session
from strata_python.clients import models as sm
from strata_python.testing import FakeModels

from stratavoice import coverage, studio, writer
from stratavoice.models import Prompt


@pytest.fixture
def up(models: FakeModels) -> FakeModels:
    models.down = False
    return models


def _generated(db: Session) -> list[Prompt]:
    return list(db.scalars(select(Prompt).where(Prompt.source == "generated").order_by(Prompt.position)))


def test_a_batch_is_kept_phonemised_and_ranked(db_session: Session, up: FakeModels):
    studio.seed(db_session)
    up.models["write"] = "claude-sonnet-5-5-api"
    up.results["write"] = offer(
        candidate("The cat sat by the fire."),
        candidate("Usually the treasure is a pleasure to measure.", "expressive", "pleased", "  quietly   proud "),
        candidate("Is it Tuesday already?", "prosodic", "surprised", "a surprised question"),
    )
    done = writer.write(db_session, 3)
    assert done.model_dump() == {
        "offered": 3,
        "added": 3,
        "writer": "claude-sonnet-5-5-api",
        "cost_usd": 0.031,
        "waiting": 3,
    }
    rows = _generated(db_session)
    assert [r.position for r in rows] == [coverage.GENERATED_BASE + i for i in (1, 2, 3)]  # ranked
    assert rows[0].text.startswith("Usually")  # /ʒ/ and a new style: the most to add
    measure = rows[0]
    assert (measure.kind, measure.style, measure.cue, measure.writer) == (
        "expressive",
        "pleased",
        "quietly proud",
        "claude-sonnet-5-5-api",
    )
    assert measure.phonemes is not None
    assert "ʒ" in measure.phonemes  # ʒ

    (job,) = up.jobs
    assert (job["role"], job["app"]) == ("write", "strata-voice")
    params = job["params"]
    assert params["schema"] == writer.SCHEMA
    assert params["system"] == writer.SYSTEM
    assert params["prompt"].startswith("Write 3 new prompts")
    assert "(never said yet)" in params["prompt"]  # nothing recorded: every sound is missing


def test_candidates_that_break_a_rule_or_repeat_are_dropped(db_session: Session, up: FakeModels):
    studio.seed(db_session)
    starter = studio.prompts(db_session)[3]
    up.results["write"] = offer(
        candidate("It costs 23 pounds."),  # a digit
        candidate("Too short."),
        candidate(" ".join(["word"] * 31)),
        candidate("A fine sentence about the weather.", kind="narrative"),  # not a kind
        {"text": 42, "kind": "phonetic"},
        "not an object",
        candidate("A fine sentence about the weather.", style="ecstatic"),  # unknown style: neutral
        candidate("A fine sentence about the weather."),  # the same again
        candidate("“A quoted sentence about the garden.”", cue="   "),
    )
    done = writer.write(db_session, 9)
    assert (done.offered, done.added) == (9, 2)
    texts = {r.text: r for r in _generated(db_session)}
    assert texts["A fine sentence about the weather."].style == "neutral"
    assert texts["A quoted sentence about the garden."].cue is None
    assert starter.text not in texts

    up.results["write"] = offer(candidate("A fine sentence about the weather."), as_text=True)  # a second batch
    again = writer.write(db_session, 1)
    assert (again.offered, again.added, again.waiting) == (1, 0, 2)  # written before: one prompt, not two


def test_the_brief_names_what_is_missing():
    cov = coverage.Coverage(
        prompts=1,
        waiting=0,
        phonemised=True,
        groups=[
            coverage.Group(
                key="phoneme",
                title="Phonemes",
                covered=1,
                inventory=2,
                units=[
                    coverage.UnitOut(value="ʒ", count=0, example="measure"),
                    coverage.UnitOut(value="p", count=4, example="pin"),
                ],
            ),
            coverage.Group(
                key="sentence",
                title="",
                covered=0,
                inventory=1,
                units=[coverage.UnitOut(value="wh-question", count=0, example=None)],
            ),
            coverage.Group(
                key="style",
                title="",
                covered=0,
                inventory=1,
                units=[coverage.UnitOut(value="sad", count=0, example=None)],
            ),
        ],
    )
    text = writer.brief(cov, 5)
    assert "/ʒ/ as in “measure” (never said yet); /p/ as in “pin” (said 4 times)." in text
    assert "- Sentence types: wh-question." in text
    assert "- Styles for the expressive and prosodic prompts: sad." in text
    assert "Sounds" not in writer.brief(cov.model_copy(update={"phonemised": False}), 5)  # no phonemes: no sounds


@pytest.mark.parametrize("count", [0, writer.MAX_COUNT + 1])
def test_a_batch_has_a_sensible_size(db_session: Session, count: int):
    with pytest.raises(ValueError, match="between 1 and 100"):
        writer.write(db_session, count)


def test_each_way_the_writer_can_fail(db_session: Session, models: FakeModels, monkeypatch: pytest.MonkeyPatch):
    studio.seed(db_session)
    with pytest.raises(sm.Unavailable, match="strata-models is not running"):
        writer.write(db_session, 5)

    models.down = False
    models.results["write"] = {"text": "Here are some prompts!", "json": None}
    with pytest.raises(writer.WriterFailed, match="no list of prompts"):
        writer.write(db_session, 5)
    models.results["write"] = {"text": '{"prompts": "none"}', "json": None}
    with pytest.raises(writer.WriterFailed, match="no list of prompts"):
        writer.write(db_session, 5)

    models.fail("refusal")
    with pytest.raises(writer.WriterFailed, match=r"The prompt writer failed: .*refusal"):
        writer.write(db_session, 5)

    models.running_polls = 1_000_000  # still writing
    monkeypatch.setattr(writer, "WAIT_SECONDS", 0.2)
    with pytest.raises(writer.WriterFailed, match="took too long"):
        writer.write(db_session, 5)
    assert _generated(db_session) == []
