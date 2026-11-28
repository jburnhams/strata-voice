import datetime

import pytest

from stratavoice.writing import split

T0 = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)


def day(n: float) -> datetime.datetime:
    return T0 + datetime.timedelta(days=n)


def test_draw_is_fixed_per_seed_and_key() -> None:
    assert split.draw("s", "k") == split.draw("s", "k")
    assert split.draw("s", "k") != split.draw("t", "k")
    assert 0 <= split.draw("s", "k") < 1


def test_freeze_seals_the_newest_year_and_holds_out_some_recipients() -> None:
    rows: list[tuple[datetime.datetime, str | None]] = []
    # Ten big correspondents (never held out), many middling ones, some too thin to test on, and posts with none.
    rows += [(day(i % 700), f"big{i % 10}") for i in range(2000)]
    rows += [(day(i % 700), f"mid{i % 40}") for i in range(400)]
    rows += [(day(5), f"thin{i}") for i in range(30)]
    rows += [(day(800), None)]
    rule = split.freeze(rows, seed="fixed")
    assert rule.cutoff == day(800) - split.SEALED_SPAN
    assert rule.seed == "fixed"
    assert rule.holdout
    assert all(r.startswith("mid") for r in rule.holdout)
    held = sum(1 for at, r in rows if r in rule.holdout and at < rule.cutoff)
    before = sum(1 for at, _ in rows if at < rule.cutoff)
    assert 0 < held <= split.HOLDOUT_SHARE * before * 1.5
    assert split.freeze(rows, seed="fixed") == rule
    assert len(split.freeze(rows).seed) == 16  # a fresh seed when none is given


def test_freeze_refuses_nothing() -> None:
    with pytest.raises(ValueError, match="nothing to split"):
        split.freeze([])


def test_assign() -> None:
    rule = split.Rule(cutoff=day(365), seed="s", holdout=frozenset({"held"}))
    assert split.assign(rule, "g", day(400), set()) == split.SEALED
    assert split.assign(rule, "g", day(10), {"held", "other"}) == split.SEALED
    assert split.assign(rule, "g", day(362), set()) == split.BUFFER
    got = {split.assign(rule, f"g{i}", day(10), set()) for i in range(200)}
    assert got == {split.TRAIN, split.DEV}
    share = sum(split.assign(rule, f"g{i}", day(10), set()) == split.DEV for i in range(2000)) / 2000
    assert abs(share - split.DEV_SHARE) < 0.03


def test_highest() -> None:
    assert split.highest([split.TRAIN, split.SEALED, split.DEV]) == split.SEALED
    assert split.highest([split.TRAIN, split.BUFFER]) == split.BUFFER
