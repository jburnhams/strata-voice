import datetime
import json
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from writing import Source, at

from stratavoice.models import Writing, WritingSplit
from stratavoice.writing import corpus, source, split

LONG = "this is a reply long enough to count as something that says a little about how a person writes"
LONGER = " ".join(
    [LONG, "and then it goes on for a while about the weather, the trains and the plans for the weekend", LONG]
)


def unique(n: int) -> str:
    """A text of its own: no other row is a copy of it."""
    return " ".join(f"w{n}x{i}" for i in range(12))


def quiet(*_: Any, **__: Any) -> None:
    """A progress reporter that keeps nothing."""


def build(db: Session, src: Source) -> corpus.Built:
    return corpus.build(db, src.engine, progress=quiet)


def rows(db: Session) -> list[Writing]:
    return list(db.scalars(select(Writing).order_by(Writing.id)))


def test_consecutive_chat_lines_are_joined_until_someone_else_writes_or_time_passes(
    db_session: Session, writing_source: Source
) -> None:
    s = writing_source
    s.mine("are you coming", at(0))
    s.mine("bring the map", at(1))
    s.mine("and snacks", at(2))
    s.theirs("sam", at(3))
    s.mine("great see you then", at(4))
    s.mine("much later, a new thought here", at(20))
    s.mine("a line the context view never saw", at(30), timeline=False)
    done = build(db_session, s)
    got = rows(db_session)
    assert [w.text for w in got] == [
        "are you coming\nbring the map\nand snacks",
        "great see you then",
        "much later, a new thought here",
        "a line the context view never saw",
    ]
    assert [w.parts for w in got] == [3, 1, 1, 1]
    assert got[0].source_ids == "1 2 3"
    assert done.read == 6
    assert done.rows == 4
    assert done.joined == 2
    assert {w.medium for w in got} == {"chat-direct"}
    assert got[0].ended - got[0].at == datetime.timedelta(minutes=2)
    # One session: within six hours of each other, so one group and one split.
    assert len({w.group_key for w in got}) == 1


def test_a_chat_with_more_than_one_other_person_is_a_group(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    s.theirs("sam", at(0), conversation="g")
    s.theirs("alex", at(1), conversation="g")
    s.mine("hello all of you, what time are we meeting?", at(2), conversation="g")
    build(db_session, s)
    (w,) = rows(db_session)
    assert w.medium == "chat-group"
    assert w.recipients == 2


def test_mail_is_cleaned_and_a_quote_left_in_is_flagged(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    s.mail("<m1>", "please send me the minutes of the meeting we had on tuesday afternoon")
    s.mine(
        "Sure, here they are.\n\nOn Tue, Sam wrote:\n> please send me the minutes\n",
        at(0),
        platform="email",
        kind="email",
        conversation="t1",
        recipients="Sam@example sam@example  b@example",
        subject="Re: minutes",
        in_reply_to="<m1>",
    )
    s.mine(
        "you asked: please send me the minutes of the meeting we had on tuesday",
        at(5),
        platform="email",
        kind="email",
        conversation="t1",
        in_reply_to="<m1>",
        work=True,
    )
    s.mine(
        "no thread, no recipients, a mail with words enough here",
        at(9),
        platform="email",
        kind="email",
        conversation=None,
    )
    done = build(db_session, s)
    first, second, third = rows(db_session)
    assert first.text == "Sure, here they are."
    assert first.original is not None
    assert first.original.startswith("Sure")
    assert json.loads(first.removed) == [["quote", 22, len(first.original)]]
    assert first.medium == "email-personal"
    assert first.recipients == 2  # addresses compared lower-cased, each once
    assert first.subject == "Re: minutes"
    assert first.in_reply_to == "<m1>"
    assert second.flags == "leak"
    assert second.medium == "email-work"
    assert second.original is None
    assert first.group_key == second.group_key  # one thread, one group
    assert third.recipient is None
    assert third.recipients is None
    assert done.leaks == 1


def test_posts_comments_and_prompts_stand_alone(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    s.mine(
        "a photo of the sea at dawn, the best morning of the year",
        at(0),
        platform="facebook",
        kind="post",
        conversation="audience:owner",
    )
    s.mine("can you check this function for me please?", at(1), platform="claude", kind="prompt", conversation="chat-1")
    build(db_session, s)
    post, prompt = rows(db_session)
    assert (post.medium, post.kind) == ("social", "post")
    assert (prompt.medium, prompt.kind) == ("prompt", "prompt")
    assert post.group_key != prompt.group_key


def test_trivial_copies_assisted_and_the_sample(
    db_session: Session, writing_source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = writing_source
    monkeypatch.setenv("STRATAVOICE_ASSISTANT_SINCE", "2020-01-06")
    s.mine("yep see you soon", at(0), conversation="a")
    s.mine("ok?", at(0, days=1), conversation="b")
    s.mine(LONGER, at(0, days=2), conversation="c")
    s.mine(LONGER, at(0, days=3), conversation="d")  # the same words again
    s.mine(LONGER + " then", at(0, days=4), conversation="e")  # nearly
    s.mine("something else entirely, written later on, with enough words", at(0, days=6), conversation="f")
    done = build(db_session, s)
    got = rows(db_session)
    assert [w.trivial for w in got] == [True, False, False, False, False, False]  # a question is never trivial
    assert [w.flags for w in got] == ["", "", "", "duplicate", "near-duplicate", ""]
    assert done.duplicates == 2
    assert done.trivial == 1
    assert len({w.split for w in got[2:5]}) == 1  # copies share a split
    assert [w.assisted for w in got] == [False, False, False, False, False, True]
    # The sample leaves out the trivial and the copies; its order is a fixed draw.
    sampled = sorted((w.sample, w.text) for w in got if w.sample is not None)
    assert [t for _, t in sampled] == sorted(
        [got[1].text, got[2].text, got[5].text],
        key=lambda t: split.draw("sample", next(w.key for w in got if w.text == t)),
    )
    assert all(w.words == len(w.text.split()) or w.trivial or "?" in w.text for w in got[2:])


def test_no_assistant_date_marks_nothing(
    db_session: Session, writing_source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STRATAVOICE_ASSISTANT_SINCE", "")
    writing_source.mine(LONG, at(0, days=5000))
    build(db_session, writing_source)
    assert [w.assisted for w in rows(db_session)] == [False]


def test_the_split_is_frozen_once_and_checks_survive_a_rebuild(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    for d in range(0, 900, 30):
        s.mine(unique(d), at(0, days=d), conversation=f"c{d}")
    done = build(db_session, s)
    rule = db_session.scalars(select(WritingSplit)).one()
    assert source.when(rule.cutoff) == at(0, days=870) - split.SEALED_SPAN
    assert done.cutoff == source.when(rule.cutoff)
    first = {w.key: w.split for w in rows(db_session)}
    assert first[next(k for k, v in first.items() if v == split.SEALED)] == split.SEALED
    assert {c.value for c in done.splits} >= {split.TRAIN, split.SEALED}
    target = rows(db_session)[0]
    corpus.check(db_session, target.id, "quote")
    # Newer writing arrives: the old rows keep their split (the cutoff does not move), the check stays.
    s.mine(unique(9999), at(0, days=2000), conversation="new")
    build(db_session, s)
    assert db_session.scalars(select(WritingSplit)).one().cutoff == rule.cutoff
    again = {w.key: w.split for w in rows(db_session)}
    assert {k: again[k] for k in first} == first
    assert again[max(again)] == split.SEALED or split.SEALED in again.values()
    kept = db_session.scalars(select(Writing).where(Writing.key == target.key)).one()
    assert kept.checked_as == "quote"
    assert kept.checked is not None


def test_a_build_with_nothing_to_read_is_refused(db_session: Session, writing_source: Source) -> None:
    with pytest.raises(ValueError, match="holds nothing"):
        build(db_session, writing_source)


@pytest.mark.parametrize(
    ("setting", "drop"), [("my_writing", "my_writing"), ("messages_all", "messages_all"), ("emails_all", "emails_all")]
)
def test_a_missing_table_names_itself_and_the_setting(
    db_session: Session, writing_source: Source, setting: str, drop: str
) -> None:
    s = writing_source
    s.mine("a chat line, long enough to be worth keeping here", at(0))
    s.mine("a mail", at(1), platform="email", kind="email", in_reply_to="<x>")
    with s.engine.begin() as c:
        c.execute(text(f"DROP TABLE {drop}"))
    with pytest.raises(source.SourceMissing, match=f"{setting} could not be read"):
        build(db_session, s)


def test_page_filters_and_order(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    s.mine("hi", at(0), conversation="a")
    s.mine(LONG, at(0, days=400), conversation="b")
    s.mine("a mail with some words in it to read", at(0, days=800), platform="email", kind="email", conversation="t")
    build(db_session, s)
    page = corpus.page(db_session, limit=2)
    assert [w.text for w in page.items] == ["a mail with some words in it to read", LONG]
    assert page.next is not None
    rest = corpus.page(db_session, after=int(page.next), limit=2)
    assert [w.text for w in rest.items] == ["hi"]
    assert rest.next is None
    assert [w.text for w in corpus.page(db_session, medium="email-personal").items] == [
        "a mail with some words in it to read"
    ]
    assert [w.text for w in corpus.page(db_session, year=2021).items] == [LONG]
    assert [w.text for w in corpus.page(db_session, trivial=True).items] == ["hi"]
    out = page.items[0]
    assert out.removed == []
    assert out.original is None
    assert out.flags == []


def test_check_marks_and_clears(db_session: Session, writing_source: Source) -> None:
    writing_source.mine(LONG, at(0))
    build(db_session, writing_source)
    (w,) = corpus.to_check(db_session, "chat-direct")
    assert w.sample == 0
    assert corpus.check(db_session, w.id, "clean").checked_as == "clean"
    assert corpus.to_check(db_session, "chat-direct") == []
    assert corpus.check(db_session, w.id, None).checked_as is None
    with pytest.raises(ValueError, match="not a verdict"):
        corpus.check(db_session, w.id, "fine")
    with pytest.raises(KeyError, match="no writing 999"):
        corpus.check(db_session, 999, "clean")


def test_summary(db_session: Session, writing_source: Source) -> None:
    empty = corpus.summary(db_session)
    assert (empty.rows, empty.built, empty.cutoff, empty.holdout, empty.job) == (0, None, None, 0, None)
    s = writing_source
    s.mail("<m1>", "please send me the minutes of the meeting we had on tuesday afternoon")
    s.mine("ok", at(0), conversation="a")
    s.mine(LONG, at(0, days=1), conversation="b")
    s.mine(
        "you asked: please send me the minutes of the meeting we had on tuesday",
        at(0, days=2),
        platform="email",
        kind="email",
        in_reply_to="<m1>",
    )
    build(db_session, s)
    w = corpus.to_check(db_session, "chat-direct")[0]
    corpus.check(db_session, w.id, "clean")
    got = corpus.summary(db_session)
    assert got.rows == 3
    chat = next(m for m in got.mediums if m.medium == "chat-direct")
    assert (chat.rows, chat.trivial, chat.sample, chat.checked, chat.clean) == (2, 1, 1, 1, 1)
    assert chat.words == len(LONG.split())
    assert chat.first == at(0)
    assert chat.last == at(0, days=1)
    assert [c.value for c in got.years] == ["2020"]
    assert [(c.value, c.rows) for c in got.flags] == [("leak", 1)]
    assert sum(c.rows for c in got.splits) == 3
    assert got.built is not None
    assert got.cutoff is not None


def test_export_leaves_out_copies_and_trivial_rows(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    s.mine("hi", at(0), conversation="a")
    s.mine(LONG, at(0, days=1), conversation="b")
    s.mine(LONG, at(0, days=2), conversation="c")
    build(db_session, s)
    lines = list(corpus.export(db_session))
    assert [json.loads(line)["text"] for line in lines] == [LONG]
    assert "original" not in json.loads(lines[0])
    assert [json.loads(line)["text"] for line in corpus.export(db_session, include_trivial=True)] == ["hi", LONG]


def test_run_build_reads_another_database_and_closes_it(db_engine: Any, writing_source: Source) -> None:
    writing_source.mine(LONG, at(0))
    assert corpus.run_build(db_engine).rows == 1


def test_run_build_reads_the_apps_own_database_when_no_url_is_set(
    db_engine: Any, writing_source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STRATAVOICE_WRITING_URL", "")
    # The app's own database has none of the views: the build says which one is missing.
    with pytest.raises(source.SourceMissing, match="my_writing could not be read"):
        corpus.run_build(db_engine)
    assert source.engine(db_engine) is db_engine


def test_a_run_ends_where_someone_else_has_the_last_word(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    s.mine("are you still coming tonight", at(0))
    s.theirs("sam", at(1))
    s.theirs("sam", at(0), conversation="not-mine")  # a conversation the person never wrote in is not read
    build(db_session, s)
    assert [w.text for w in rows(db_session)] == ["are you still coming tonight"]


def test_three_copies_are_one_cluster(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    for day in range(3):
        s.mine(LONGER, at(0, days=day), conversation=f"c{day}")
    build(db_session, s)
    got = rows(db_session)
    assert [w.flags for w in got] == ["", "duplicate", "duplicate"]
    assert len({w.split for w in got}) == 1


def test_a_reply_to_a_mail_with_no_body_is_not_checked_for_a_leak(db_session: Session, writing_source: Source) -> None:
    s = writing_source
    s.mail("<empty>", None)
    s.mine(LONG, at(0), platform="email", kind="email", conversation="t", in_reply_to="<empty>")
    build(db_session, s)
    (w,) = rows(db_session)
    assert w.flags == ""
