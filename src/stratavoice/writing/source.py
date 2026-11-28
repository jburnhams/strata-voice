"""Where the person's writing is read from: three tables or views named in settings (`writing_source`,
`writing_context`, `writing_emails`), normally strata-takeout's `unified.my_writing`, `unified.messages_all` and
`unified.emails_all` in the shared database (their columns: strata-takeout's docs/unified.md).

strata-takeout already knows which accounts are the person's (its identities file) and loads every platform, so this
app does not parse an export: it reads rows. The three are read, never written, and the app's own records stay in
its own schema. The names come from settings and are checked to be plain identifiers before they reach SQL
(`settings.table_name`); every value is a bound parameter."""

import datetime
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from sqlalchemy import Engine, bindparam, create_engine, text
from sqlalchemy.exc import DBAPIError

from stratavoice import settings

# The platforms whose rows are chat lines (strata-takeout's `platform` values); mail is `email`.
CHAT_KINDS = ("chat",)
COLUMNS = "platform, source, kind, work, at, conversation_id, recipients, subject, text, in_reply_to, source_id"
BATCH = 500  # message ids per query for the mails replied to


class SourceMissing(ValueError):
    """A table or view the writing is read from is not in the database (a 400 with the sentence)."""


@dataclass(frozen=True)
class Written:
    """One row of what the person wrote (`writing_source`): a mail, a chat line, a post or a comment."""

    platform: str
    source: str
    kind: str
    work: bool
    at: datetime.datetime
    conversation_id: str | None
    recipients: str | None
    subject: str | None
    text: str
    in_reply_to: str | None
    source_id: str


@dataclass(frozen=True)
class Line:
    """One chat line of anyone's (`writing_context`): enough to place it in its conversation's timeline."""

    platform: str
    conversation_id: str
    at: datetime.datetime
    sender: str | None
    source_id: str


def engine(own: Engine) -> Engine:
    """The database to read from: the `writing_url` setting, else the app's own (`own`). The caller disposes of a
    new one (`own` is returned as it is, so compare before disposing)."""
    url = settings.writing_url()
    return create_engine(url) if url else own


def when(v: object) -> datetime.datetime:
    """A time from the database as an aware UTC datetime: Postgres gives a datetime, SQLite text."""
    t = v if isinstance(v, datetime.datetime) else datetime.datetime.fromisoformat(str(v))
    return t.replace(tzinfo=datetime.UTC) if t.tzinfo is None else t.astimezone(datetime.UTC)


def _missing(table: str, setting: str, e: DBAPIError) -> SourceMissing:
    return SourceMissing(
        f"{table} could not be read ({type(e.orig).__name__}): build it with strata-takeout "
        f"(`strata-takeout-unified build`), or set `{setting}` to the table that holds it."
    )


def written(src: Engine) -> Iterator[Written]:
    """Everything the person wrote, oldest first (ties by platform and id, so the order is the same every time)."""
    table = settings.writing_tables()[0]
    sql = f"SELECT {COLUMNS} FROM {table} WHERE text IS NOT NULL ORDER BY at, platform, source_id"  # noqa: S608 - checked name
    q = text(sql)
    try:
        with src.connect() as c:
            for r in c.execute(q).yield_per(2000):
                yield Written(
                    platform=str(r[0]),
                    source=str(r[1] or ""),
                    kind=str(r[2]),
                    work=bool(r[3]),
                    at=when(r[4]),
                    conversation_id=None if r[5] is None else str(r[5]),
                    recipients=None if r[6] is None else str(r[6]),
                    subject=None if r[7] is None else str(r[7]),
                    text=str(r[8]),
                    in_reply_to=None if r[9] is None else str(r[9]),
                    source_id=str(r[10]),
                )
    except DBAPIError as e:
        raise _missing(table, "writing_source", e) from e


def timelines(src: Engine, conversations: set[tuple[str, str]]) -> dict[tuple[str, str], list[Line]]:
    """Every line, anyone's, of the given (platform, conversation) pairs, each conversation's in time order."""
    table = settings.writing_tables()[1]
    out: dict[tuple[str, str], list[Line]] = {}
    platforms = sorted({p for p, _ in conversations})
    if not platforms:
        return out
    q = text(
        f"SELECT platform, conversation_id, at, sender, source_id FROM {table} "  # noqa: S608 - a checked identifier
        "WHERE platform IN :platforms ORDER BY platform, conversation_id, at, source_id"
    ).bindparams(bindparam("platforms", expanding=True))
    try:
        with src.connect() as c:
            for r in c.execute(q, {"platforms": platforms}).yield_per(5000):
                key = (str(r[0]), str(r[1]))
                if key in conversations:
                    line = Line(key[0], key[1], when(r[2]), None if r[3] is None else str(r[3]), str(r[4]))
                    out.setdefault(key, []).append(line)
    except DBAPIError as e:
        raise _missing(table, "writing_context", e) from e
    return out


def replied_to(src: Engine, message_ids: Iterable[str]) -> dict[str, str]:
    """The text of each mail named by its Message-ID (the mails the person's replies answer), where it has one."""
    table = settings.writing_tables()[2]
    ids = sorted(set(message_ids))
    out: dict[str, str] = {}
    q = text(f"SELECT message_id, body_text FROM {table} WHERE message_id IN :ids").bindparams(  # noqa: S608 - a checked identifier
        bindparam("ids", expanding=True)
    )
    try:
        with src.connect() as c:
            for i in range(0, len(ids), BATCH):
                for r in c.execute(q, {"ids": ids[i : i + BATCH]}):
                    if r[1]:
                        out[str(r[0])] = str(r[1])
    except DBAPIError as e:
        raise _missing(table, "writing_emails", e) from e
    return out
