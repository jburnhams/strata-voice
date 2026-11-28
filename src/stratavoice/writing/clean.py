"""Taking out of a mail what the person did not write, and nothing else.

A mail body as exported holds the reply and, below or between its lines, other people's words: the quoted message
(`> ` lines, or everything after "On <date>, <name> wrote:" or an Outlook "From: / Sent:" header), a forwarded
message, the person's signature (contact details pasted the same way every time) and a mail client's footer ("Sent
from my iPhone"). Quotes in what a model learns from leak third parties' words and make a draft look like the person
because it copies the person's correspondents (voice-research written.md W-D9), so they go; the rest of the text is
kept exactly as written, because spelling, casing, emoji and line breaks are the voice (W-D1).

Everything is a span of the original (`kind, start, end`), never a rewrite, so the screen can show the original with
what was taken out struck through, and the person can check the rules (corpus.SAMPLE_SIZE per medium).

One exception to "never a rewrite": a line break the mail client put in. Plain-text mail was wrapped at a fixed width
(about 70 to 78 characters) when it was sent, so a paragraph arrives cut into lines the person never typed. When a
mail's kept lines look wrapped (`wrap_width`), each such break is a `wrap` span (the spaces around it and the line end)
and is put back as one space; a break the person typed (a short line, a blank line, a list item) stays.

A sign-off ("Thanks,\\nJonathan") is part of a voice and stays. A signature is told from it by repetition and shape:
the same trailing lines in at least `SIGNATURE_REPEATS` of the person's mails (`learn_signatures`) that are three or
more lines, or hold contact details (a phone number, an address, a web or mail address)."""

import re
from collections import Counter
from collections.abc import Iterable
from itertools import pairwise

QUOTE = "quote"
FORWARD = "forward"
SIGNATURE = "signature"
CLIENT = "client"
WRAP = "wrap"  # a line break the mail client added at a fixed width: rejoined with one space

Span = tuple[str, int, int]

SIGNATURE_REPEATS = 20
SIGNATURE_LINES = 6  # the longest trailing block counted as a signature
LEAK_WORDS = 8  # a run of this many words also in the mail replied to is a quote left in

ATTRIBUTION = re.compile(r"\s*On\b.{0,300}\bwrote:\s*", re.S)
ORIGINAL = re.compile(r"\s*-{2,}\s*Original Message\s*-{2,}\s*", re.I)
FORWARDED = re.compile(r"\s*(-{3,}\s*Forwarded message\s*-{3,}|Begin forwarded message:)\s*", re.I)
HEADER_FROM = re.compile(r"\s*\*?From:\*?\s", re.I)
HEADER_NEXT = re.compile(r"\s*\*?(Sent|Date|To|Subject|Cc):\*?\s", re.I)
QUOTED = re.compile(r"\s*>")
SIG_DASH = re.compile(r"-- ?")
CLIENT_LINE = re.compile(
    r"\s*(Sent from my [\w\- ]{1,40}|Sent from (Mail|Outlook|Yahoo Mail) for [\w ]{1,20}|Get Outlook for [\w ]{1,20}"
    r"|Sent (via|from) (my )?BlackBerry.{0,60})\s*",
    re.I,
)
CONTACT = re.compile(r"@|www\.|https?://|\d[\d ()+\-]{7,}\d|\b(tel|mob|mobile|fax|ltd|limited)\b", re.I)
WORD = re.compile(r"\w+")

WRAP_WIDTHS = (40, 100)  # the widths a mail client wraps plain text at
WRAP_NEAR = 12  # a wrapped line ends within this many characters of the width
WRAP_SHARE = 0.4  # of a mail's lines with a space in them, at least this share must end near the width
LONG_WORD = 20  # a word this long (a link) moves to the next line whatever the line's length
NOT_WRAPPED = re.compile(r"\s|[>*•\-]|\d+[.)]\s")  # a line starting like this was started by the person


def _lines(text: str) -> list[tuple[int, str]]:
    """Each line with its offset in the text (line ends kept off the line itself)."""
    out: list[tuple[int, str]] = []
    at = 0
    for raw in text.splitlines(keepends=True):
        out.append((at, raw.rstrip("\r\n")))
        at += len(raw)
    return out


def _block_end(ls: list[tuple[int, str]], i: int) -> int:
    """The first line after the quoted block that starts at `i` (blank lines inside it belong to it)."""
    while i < len(ls) and (QUOTED.match(ls[i][1]) or not ls[i][1].strip()):
        i += 1
    return i


def _header(ls: list[tuple[int, str]], i: int) -> bool:
    """An Outlook-style quoted header: `From:` followed within three lines by `Sent:`, `To:` and the like."""
    return bool(HEADER_FROM.match(ls[i][1])) and any(
        HEADER_NEXT.match(ls[j][1]) for j in range(i + 1, min(len(ls), i + 4))
    )


def _attribution(ls: list[tuple[int, str]], i: int) -> int:
    """How many lines the attribution starting at `i` takes ("On ... wrote:" may be wrapped onto a second line), or
    0 when it is not one."""
    line = ls[i][1]
    if ATTRIBUTION.fullmatch(line):
        return 1
    if line.lstrip().startswith("On ") and i + 1 < len(ls) and ATTRIBUTION.fullmatch(f"{line} {ls[i + 1][1].strip()}"):
        return 2
    return 0


def _merge(spans: list[Span]) -> list[Span]:
    out: list[Span] = []
    for kind, start, end in sorted(spans, key=lambda s: (s[1], s[2])):
        if end <= start:
            continue
        if out and start <= out[-1][2]:
            k, s0, e0 = out[-1]
            out[-1] = (k, s0, max(e0, end))
        else:
            out.append((kind, start, end))
    return out


def _trailing(text: str, spans: list[Span]) -> list[tuple[int, int, str]]:
    """The kept lines of the text (start, end, stripped words), outside every span, blank ones left out."""
    kept: list[tuple[int, int, str]] = []
    for at, line in _lines(text):
        end = at + len(line)
        if line.strip() and not any(s <= at < e for _, s, e in spans):
            kept.append((at, end, line.strip()))
    return kept


def wrap_width(lines: Iterable[str]) -> int | None:
    """The width the lines were wrapped at, or None when they do not look wrapped: of the lines with a space (a line
    without one, such as a link, cannot be wrapped), at least `WRAP_SHARE` end within `WRAP_NEAR` of the longest."""
    body = [line.rstrip() for line in lines if " " in line.strip()]
    if len(body) < 3:
        return None
    w = max(len(line) for line in body)
    if not WRAP_WIDTHS[0] <= w <= WRAP_WIDTHS[1]:
        return None
    near = sum(1 for line in body if len(line) >= w - WRAP_NEAR)
    return w if near >= max(2, WRAP_SHARE * len(body)) else None


def _soft(line: str, nxt: str, width: int) -> bool:
    """Whether the break between `line` and `nxt` is the client's: `nxt` starts with a word, and that word would not
    have fitted on `line` (a long line, or a long word such as a link)."""
    a = line.rstrip()
    if not a or not nxt.strip() or NOT_WRAPPED.match(nxt):
        return False
    first = nxt.split()[0]
    return len(a) + 1 + len(first) > width - 2 and (len(a) >= width - WRAP_NEAR - 3 or len(first) >= LONG_WORD)


def _wraps(text: str, spans: list[Span]) -> list[Span]:
    """The `wrap` spans of the text's kept lines (outside every span in `spans`)."""

    def taken(at: int) -> bool:
        return any(s <= at < e for _, s, e in spans)

    ls = [(at, line) for at, line in _lines(text) if not taken(at)]
    width = wrap_width(line for _, line in ls)
    if width is None:
        return []
    out: list[Span] = []
    for (at, line), (nat, nxt) in pairwise(ls):
        end = at + len(line)
        if nat > end + 2 or taken(end) or not _soft(line, nxt, width):  # another line between them: not a pair
            continue
        start = at + len(line.rstrip())
        out.append((WRAP, start, nat + len(nxt) - len(nxt.lstrip())))
    return out


def clean_email(
    text: str, signatures: frozenset[tuple[str, ...]] = frozenset(), rejoin: bool = True
) -> tuple[str, list[Span]]:
    """The person's own words of a mail body and the spans taken out of it (see the module docstring). `signatures`
    are the trailing blocks `learn_signatures` found in their mail; `rejoin` puts the client's line breaks back
    together (off when learning signatures, which are matched line by line)."""
    ls = _lines(text)
    spans: list[Span] = []
    cut: tuple[int, str] | None = None  # everything from this line on is someone else's
    i = 0
    while i < len(ls):
        line = ls[i][1]
        if FORWARDED.fullmatch(line):
            cut = (i, FORWARD)
            break
        if ORIGINAL.fullmatch(line) or _header(ls, i):
            cut = (i, QUOTE)
            break
        n = _attribution(ls, i)
        if n:
            j = i + n
            while j < len(ls) and not ls[j][1].strip():
                j += 1
            if j < len(ls) and QUOTED.match(ls[j][1]):
                e = _block_end(ls, j)  # an inline reply: the quote ends, the person's words go on
                spans.append((QUOTE, ls[i][0], ls[e][0] if e < len(ls) else len(text)))
                i = e
                continue
            cut = (i, QUOTE)  # a quote without `>` (a mail client's HTML flattened): the rest is it
            break
        if QUOTED.match(line):
            e = _block_end(ls, i)
            spans.append((QUOTE, ls[i][0], ls[e][0] if e < len(ls) else len(text)))
            i = e
            continue
        if SIG_DASH.fullmatch(line):
            cut = (i, SIGNATURE)
            break
        i += 1
    if cut is not None:
        spans.append((cut[1], ls[cut[0]][0], len(text)))
    kept = _trailing(text, spans)
    while kept and CLIENT_LINE.fullmatch(kept[-1][2]):
        spans.append((CLIENT, kept[-1][0], kept[-1][1]))
        kept.pop()
    for k in range(min(SIGNATURE_LINES, len(kept)), 0, -1):
        if tuple(w for _, _, w in kept[-k:]) in signatures:
            spans.append((SIGNATURE, kept[-k][0], kept[-1][1]))
            break
    spans = _merge(spans)
    if rejoin:
        spans = sorted(spans + _wraps(text, spans), key=lambda s: s[1])
    out: list[str] = []
    at = 0
    for kind, start, end in spans:
        out.append(text[at:start])
        if kind == WRAP:
            out.append(" ")
        at = end
    out.append(text[at:])
    return "".join(out).rstrip(), spans


def learn_signatures(texts: Iterable[str]) -> frozenset[tuple[str, ...]]:
    """The trailing blocks of lines that end at least `SIGNATURE_REPEATS` of the mails (already cleaned of quotes)
    and look like a signature rather than a sign-off: three or more lines, or contact details."""
    counts: Counter[tuple[str, ...]] = Counter()
    for t in texts:
        tail = [line.strip() for line in t.splitlines() if line.strip()][-SIGNATURE_LINES:]
        for k in range(1, len(tail) + 1):
            counts[tuple(tail[-k:])] += 1
    return frozenset(
        block
        for block, n in counts.items()
        if n >= SIGNATURE_REPEATS and (len(block) >= 3 or any(CONTACT.search(line) for line in block))
    )


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def leaks(text: str, replied: str) -> bool:
    """Whether `text` holds a run of `LEAK_WORDS` words that is also in the mail it answers: a quote the rules
    missed, or the person pasting the other side's words."""
    theirs = words(replied)
    if len(theirs) < LEAK_WORDS:
        return False
    grams = {tuple(theirs[i : i + LEAK_WORDS]) for i in range(len(theirs) - LEAK_WORDS + 1)}
    mine = words(text)
    return any(tuple(mine[i : i + LEAK_WORDS]) in grams for i in range(len(mine) - LEAK_WORDS + 1))
