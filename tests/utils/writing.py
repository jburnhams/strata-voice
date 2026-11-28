"""A stand-in for strata-takeout's views of what the person wrote, as a real SQLite file: the three tables
`writing/source.py` reads (`my_writing`, `messages_all`, `emails_all`, with strata-takeout's columns), filled by a
test with `mine`, `theirs` and `mail`. `Source.use(monkeypatch)` points the writing settings at it."""

from __future__ import annotations

import datetime
import itertools
from dataclasses import dataclass, field

import pytest
from sqlalchemy import Engine, create_engine, text

T0 = datetime.datetime(2020, 1, 1, 9, 0, tzinfo=datetime.UTC)

SCHEMA = (
    "CREATE TABLE my_writing (platform TEXT, source TEXT, account TEXT, kind TEXT, detail TEXT, work BOOLEAN, at TEXT, "
    "conversation_id TEXT, conversation_name TEXT, recipients TEXT, subject TEXT, text TEXT, has_attachment BOOLEAN, "
    "in_reply_to TEXT, source_id TEXT)",
    "CREATE TABLE messages_all (platform TEXT, source TEXT, account TEXT, conversation_id TEXT, conversation_name TEXT, "
    "sender TEXT, at TEXT, text TEXT, kind TEXT, has_attachment BOOLEAN, source_id TEXT)",
    "CREATE TABLE emails_all (message_id TEXT, in_reply_to TEXT, thread_id TEXT, at TEXT, sender TEXT, body_text TEXT)",
)


def at(minutes: float = 0, days: float = 0) -> datetime.datetime:
    return T0 + datetime.timedelta(minutes=minutes, days=days)


@dataclass
class Source:
    """The three tables in one SQLite file."""

    url: str
    engine: Engine
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    def use(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRATAVOICE_WRITING_URL", self.url)
        monkeypatch.setenv("STRATAVOICE_WRITING_SOURCE", "my_writing")
        monkeypatch.setenv("STRATAVOICE_WRITING_CONTEXT", "messages_all")
        monkeypatch.setenv("STRATAVOICE_WRITING_EMAILS", "emails_all")

    def _run(self, sql: str, **values: object) -> None:
        with self.engine.begin() as c:
            c.execute(text(sql), values)

    def mine(
        self,
        body: str,
        when: datetime.datetime,
        platform: str = "whatsapp",
        kind: str = "chat",
        conversation: str | None = "c1",
        recipients: str | None = None,
        subject: str | None = None,
        in_reply_to: str | None = None,
        work: bool = False,
        timeline: bool = True,
    ) -> str:
        """A row the person wrote; a chat line is also put in its conversation's timeline (`timeline=False` leaves
        it out, as a line the context view lacks). Returns its id."""
        sid = str(next(self.ids))
        self._run(
            "INSERT INTO my_writing VALUES (:p, 'test', 'a', :k, NULL, :w, :at, :c, NULL, :r, :s, :t, 0, :irt, :id)",
            p=platform,
            k=kind,
            w=work,
            at=when.isoformat(),
            c=conversation,
            r=recipients,
            s=subject,
            t=body,
            irt=in_reply_to,
            id=sid,
        )
        if kind == "chat" and timeline:
            self.theirs("me", when, platform, conversation or "", sid=sid)
        return sid

    def theirs(
        self,
        sender: str,
        when: datetime.datetime,
        platform: str = "whatsapp",
        conversation: str = "c1",
        sid: str | None = None,
    ) -> str:
        """A chat line in a conversation's timeline (someone else's, unless `sid` is one of the person's)."""
        sid = sid or str(next(self.ids))
        self._run(
            "INSERT INTO messages_all VALUES (:p, 'test', 'a', :c, NULL, :s, :at, 'x', 'chat', 0, :id)",
            p=platform,
            c=conversation,
            s=sender,
            at=when.isoformat(),
            id=sid,
        )
        return sid

    def mail(self, message_id: str, body: str | None, when: datetime.datetime = T0) -> None:
        """A mail anyone sent (the person's reply names it by `in_reply_to`)."""
        self._run(
            "INSERT INTO emails_all VALUES (:m, NULL, NULL, :at, 'them', :b)", m=message_id, at=when.isoformat(), b=body
        )


def source(path: str) -> Source:
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    with engine.begin() as c:
        for sql in SCHEMA:
            c.execute(text(sql))
    return Source(url, engine)
