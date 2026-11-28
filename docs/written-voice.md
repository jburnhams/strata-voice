# The written voice: step 1, the corpus

The written voice learns how the speaker writes from what they sent. Before anything learns from it, step 1 gathers every piece, takes out what is not theirs, and freezes the split that later steps are judged on. The plan and its reasons are in the voice-research repository (`voice-design/written.md`, `experiments.md`); this page says what the code does.

## Where the writing comes from

strata-voice does not parse exports. strata-takeout loads them into the shared Postgres and keeps three views that strata-voice reads (settings, all overridable with `strata-voice set`):

| Setting | Default | What it is |
| --- | --- | --- |
| `writing_source` | `unified.my_writing` | One row per thing the person wrote: emails, chat lines, posts, comments, prompts to assistants. Which addresses and accounts are theirs is decided there, not here. |
| `writing_context` | `unified.messages_all` | Every chat line, anyone's, so a run of the person's lines can be cut where someone else speaks. |
| `writing_emails` | `unified.emails_all` | Every mail, so a reply can be checked against the mail it answers. |
| `writing_url` | (blank) | The database holding those views. Blank reads the app's own database, which is the shared Postgres in a deployment. |
| `assistant_since` | (blank) | Pieces written on or after this day are marked `assisted`: they may have been written with help, so they stay in, but out of the reference set. Blank, the default, marks nothing: the speaker wrote their mail and chats without AI help (Jonathan, 2026-11-28). |

A view that cannot be read fails the build with its name, the strata-takeout command that builds it and the setting that points elsewhere.

## What a build does (`writing/corpus.py`)

`strata-voice writing build` (or Build on the My writing screen, a job on the app's queue) reads everything first, then writes the `writing` table in one transaction.

1. **Chat lines are joined** into one piece while nobody else writes in between and each line follows the last within 5 minutes (`JOIN_GAP`), keeping the line breaks. A line the context view lacks stands alone. A chat with more than one other sender is `chat-group`, else `chat-direct`.
2. **Mail is cleaned** (`writing/clean.py`), as spans over the original so the screen can show what went: quoted replies and their attribution lines (also wrapped onto two lines, and with no `>` when HTML was flattened), Outlook header blocks and "Original Message", forwarded mail, `-- ` signatures, mail-app footers ("Sent from my iPhone"), and signatures learnt from the person's own mail (a closing block seen at least 20 times that is three lines or more, or has contact details). A sign-off ("Cheers, J") stays. Then lines a mail client broke at a fixed width (the longest line 60 to 80 characters, and the next word would have fitted) are joined with a space; a client that cut mid-word at the column (most long lines exactly the width) is joined with nothing between, mending the word; format=flowed lines (ending in a space) are joined. Blank lines, list items and the person's own short lines stay. The original keeps the breaks. A reply that still holds eight words in a row of the mail it answers is flagged `leak`. Work mail (strata-takeout's `work` column) is `email-work`, else `email-personal`.
3. **Posts and comments** are `social`; **prompts to assistants** are `prompt`.
4. **Short replies are set aside**: under 6 words with no question mark is `trivial`. They are kept (for counts) but left out of examples, tasks and the export.
5. **Copies are flagged**: the same words again are `duplicate`; 20 words or more with a shingle overlap of 0.8 or more (MinHash, 16 hashes in 4 bands) are `near-duplicate`. A cluster of copies takes its most held-out split, so a sealed piece never has a copy in train.
6. **The split is frozen on the first build** (`writing/split.py`) and kept in `writing_splits`; later builds reuse it, and each piece keeps its check mark by its key.
   - **Sealed**: everything in the newest year (from the last piece back 365 days), and every piece to about 5% of correspondents, drawn among the middling ones (never the ten largest, never one with under 5 pieces), so a test can ask about a person the model has never seen.
   - **Buffer**: the 7 days before the sealed year, left out so one conversation does not straddle the line.
   - **Dev** and **train**: the rest, 10% dev by a fixed draw per group. A group is a mail thread, or a chat session (lines in one conversation with no gap over 6 hours), so a conversation never lands on both sides.
7. **A cleaning sample** of 50 pieces per medium is drawn the same way every build (not trivial, not flagged), for the person to check.

## Checking it

The My writing screen (`web/src/screens/WritingScreen.tsx`) has three tabs: counts by medium with the split and what is flagged, Browse (filtered by medium, year and short replies, with what cleaning took out struck through), and Check cleaning, one sample piece at a time, answered with keys 1 to 5 (cleaned right, quoted text left in, signature left in, not my words, something else). Each mark can be undone for a few seconds. Ten wrong in fifty means the cleaning needs work before step 2.

`strata-voice writing corpus [--json]` prints the same counts; `strata-voice writing export [-o PATH] [--trivial]` writes the pieces as JSON lines, copies left out.

## Next

Step 2 is the preregistered pilot in the plan: reply tasks drawn from dev, generated replies from several ways of showing the model the person's writing, judged blind against the real reply.
