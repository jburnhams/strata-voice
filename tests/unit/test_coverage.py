"""coverage.py on the test database with real espeak phonemes: what a text counts as, what the recordings cover, and
the order the ranker puts generated prompts in (and when it ranks again)."""

import pytest
from prompts import generated
from sqlalchemy import select
from sqlalchemy.orm import Session
from strata_python.testing import FakeModels
from takes import heard, speech

from stratavoice import coverage, phonemes, settings, studio
from stratavoice.models import Prompt


@pytest.fixture
def consented() -> None:
    settings.SETTINGS.save({"consented_on": "2026-11-24"})


@pytest.mark.parametrize(
    ("text", "types"),
    [
        ("The kettle has boiled.", {"statement"}),
        ("Are you coming tomorrow?", {"yes/no question"}),
        ("Hang on, where did I put my keys?", {"wh-question"}),
        ("Why not?", {"wh-question"}),
        ("Oh, that's brilliant!", {"exclamation"}),
        ("We need eggs, flour, butter and sugar.", {"statement", "list"}),
        ("It's fine. Honestly. Don't worry?", {"statement", "yes/no question", "several sentences"}),
    ],
)
def test_sentence_types(text: str, types: set[str]):
    assert coverage.sentence_types(text) == types


def test_a_text_counts_its_phonemes_pairs_stress_length_type_and_style():
    t = coverage.Text("A banana, then.", phonemes.ipa("A banana, then."), "amused", cue="dry")
    got = coverage.units(t)
    assert got[("phoneme", "n")] == 3  # banana's two, then's one
    assert got[("pair", "ə b")] == 1  # across the word boundary: connected speech
    assert got[("stress", "010")] == 1
    assert ("stress", "1") not in got  # one syllable has no pattern to learn
    assert (got[("length", "short")], got[("sentence", "statement")], got[("style", "amused")]) == (1, 1, 1)
    assert coverage.seconds(t) == pytest.approx(4.0 + 3 / 2.5 + 2.0)  # setup, three words, a cue to act on
    bare = coverage.units(coverage.Text("Twenty words " * 8, None, None))
    assert set(bare) == {("length", "long"), ("sentence", "statement")}  # no phonemes, no style


def test_nothing_recorded_covers_nothing_and_lists_the_whole_inventory(db_session: Session):
    studio.seed(db_session)
    cov = coverage.coverage(db_session)
    assert (cov.prompts, cov.waiting, cov.phonemised) == (0, 0, True)
    groups = {g.key: g for g in cov.groups}
    assert [g.key for g in cov.groups] == list(coverage.GROUPS)
    assert (groups["phoneme"].covered, groups["phoneme"].inventory, len(groups["phoneme"].units)) == (0, 43, 43)
    assert groups["phoneme"].units[0].model_dump() == {"value": "p", "count": 0, "example": "pin"}  # inventory order
    assert (groups["pair"].inventory, groups["pair"].units) == (None, [])
    assert groups["style"].inventory == len(groups["style"].units) == 23


def test_recorded_takes_are_what_counts(db_session: Session, consented: None, models: FakeModels):
    listed = studio.prompts(db_session)
    spont, phon = listed[0], next(p for p in listed if p.key == "phon-01")
    studio.add_take(db_session, phon.id, speech())  # not judged yet: counts, as the queue counts it
    studio.add_take(db_session, listed[1].id, speech())  # spontaneous, not heard yet: no words to count
    models.down = False
    models.results["transcribe"] = heard("Well I went for a long walk on Saturday")
    studio.score_take(db_session, studio.add_take(db_session, spont.id, speech()).id)
    models.results["transcribe"] = heard("Mumble")
    eval_take = studio.add_take(db_session, next(p for p in listed if p.key == "eval-01").id, speech())
    assert studio.score_take(db_session, eval_take.id).verdict == "retry"  # misread: not counted

    cov = coverage.coverage(db_session)
    groups = {g.key: g for g in cov.groups}
    assert cov.prompts == 2
    said = {u.value: u.count for u in groups["phoneme"].units}
    assert said["θ"] == 1  # "thick" in phon-01
    assert said["w"] >= 2  # "Well", "went", "walk" from the spontaneous transcript
    assert {u.value: u.count for u in groups["style"].units}["neutral"] == 1  # spontaneous talk has no style
    assert {u.value: u.count for u in groups["length"].units} == {"short": 0, "medium": 2, "long": 0}
    assert groups["pair"].covered > len(groups["pair"].units) == coverage.OPEN_LIMIT  # an open set lists its least said


def test_the_ranker_puts_the_most_new_coverage_per_second_first(db_session: Session):
    studio.seed(db_session)
    plain = generated(db_session, "The cat sat on the mat.")
    rare = generated(db_session, "Usually the treasure is a pleasure to measure.", style="pleased", kind="expressive")
    long = generated(db_session, " ".join(["The cat sat on the mat and then the cat sat on the mat again."] * 2))
    copy = generated(db_session, "The cat sat on the mat again.")
    assert coverage.rank(db_session) == 4
    order = sorted([plain, rare, long, copy], key=lambda p: p.position)
    assert order[0] is rare  # /ʒ/ three times and a style never said
    assert order[-1] is long  # the most words for what it adds
    assert all(p.position > coverage.GENERATED_BASE for p in order)
    assert [p.score for p in order] == sorted([p.score or 0 for p in order], reverse=True)
    ahead, behind = sorted([plain, copy], key=lambda p: p.position)
    assert (behind.score or 0) < (ahead.score or 0) / 2  # a near-copy of a prompt placed above is worth little
    # The starter set stays first: generated prompts come after every one of its prompts.
    assert [p.source for p in studio.upcoming(db_session, 100)][-4:] == ["generated"] * 4


def test_ranking_repeats_every_few_usable_takes(db_session: Session, consented: None, models: FakeModels):
    studio.seed(db_session)
    later = generated(db_session, "A short line.")
    first = studio.upcoming(db_session, 5)
    for p in first[: coverage.RERANK_EVERY - 1]:
        studio.score_take(db_session, studio.add_take(db_session, p.id, speech()).id)
        assert later.score is None  # not yet
    p = first[coverage.RERANK_EVERY - 1]
    studio.score_take(db_session, studio.add_take(db_session, p.id, speech()).id)
    db_session.refresh(later)
    assert later.score is not None  # the fifth usable take ranks the queue again
    assert coverage.due(db_session)


def test_seeding_fills_style_and_phonemes_kept_before(db_session: Session):
    studio.seed(db_session)
    row = db_session.scalars(select(Prompt).where(Prompt.key == "expr-07")).one()
    row.style, row.phonemes = None, None  # as a database from before step 3 has it
    db_session.commit()
    studio.seed(db_session)
    assert (row.style, row.phonemes) == ("whispered", phonemes.ipa(row.text))
    spont = db_session.scalars(select(Prompt).where(Prompt.key == "spont-01")).one()
    assert spont.style is None  # the speaker's own manner


def test_without_espeak_coverage_still_counts_the_rest(db_session: Session, consented: None):
    settings.SETTINGS.save({"espeak": "no-such-espeak-program"})
    studio.seed(db_session)
    assert db_session.scalars(select(Prompt.phonemes)).first() is None
    phon = next(p for p in studio.prompts(db_session) if p.key == "phon-01")
    studio.add_take(db_session, phon.id, speech())
    cov = coverage.coverage(db_session)
    groups = {g.key: g for g in cov.groups}
    assert (cov.phonemised, groups["phoneme"].covered, groups["length"].covered) == (False, 0, 1)
