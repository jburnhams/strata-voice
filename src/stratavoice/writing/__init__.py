"""The written voice: what the person wrote, gathered from every platform, cleaned and split before anything learns
from it (step 1 of the written voice plan, docs/written-voice.md).

- `source.py` reads it: strata-takeout's views of the person's own writing, every chat line and every mail.
- `clean.py` takes out what is not theirs: quoted replies, forwarded mail, signatures and mail-client footers.
- `split.py` freezes the train, dev and sealed sets, grouped by thread or chat session and by time.
- `corpus.py` builds the `writing` table from those, and answers the screen and the commands."""
