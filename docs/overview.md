# Design brief

## 1. Goal

Capture a person's voice well enough to build a model of it: spoken first, written later. The material is mostly text archives with some audio. Step one is a recording studio that asks for the right sentences, keeps every take as a lossless master, and (in later steps) crops, recognises and scores each take so it can ask again for the ones that fall short.

Constraints: local first. The takes never leave the speaker's computer. Cloud models (Claude, OpenAI, Gemini) may write prompts; recognition and scoring run locally. Model hosting and evaluation belong to [strata-models](https://github.com/jburnhams/strata-models); this app orchestrates (asks for prompts, sends takes to be scored, decides what to ask for next).

## 2. Architecture

- **Python CLI and HTTP server (`src/stratavoice/`)** on [strata-python](https://github.com/jburnhams/strata-python), which provides settings, the server skeleton and error answers, `/api/system`, the database layer, the CLI's common commands, the test fixtures, the gate and the WAV check (`strata_python.wav`).
  - `cli.py`: `doctor` (with espeak-ng), `prompts`, `takes`, `score`, `manifest`, `coverage`, `write`, `rank`, `set`, `serve` (port 8370), `openapi`; the `strata-voice` console script.
  - `server/app.py`: the studio's typed `/api/*` routes (studio state, prompts, raw `audio/wav` take upload, skip and unskip, a cursor-paged takes list, take audio, removal, the JSONL manifest) and the built web app at every other path.
  - `settings.py`: `recordings_dir`, `consented_on` (the date the speaker agreed; blank withdraws), `max_take_seconds`, `espeak` (the program, when not on the PATH).
  - `models.py`, `migrations/`, `strata-db.toml`, `db.py`: prompts (key, text, kind, cue, partition, source, position, skipped; style, phonemes, writer, rank score) and takes (file path, rate, width, frames, size, sha256, device, and the verdict: levels, transcript, word error rate, crop, kept anyway).
  - `curriculum.py`: the en-GB starter set (spontaneous, phonetic, prosodic and expressive prompts, plus a held-out evaluation partition).
  - `studio.py`: the queue (the first prompt with no usable take and not skipped), keeping a take (consent, then `read_wav`, then an atomic write named by the row's id), judging it, keeping one anyway, paging and removing takes, and the manifest.
  - `phonemes.py`: British (RP) phonemes of a text from espeak-ng (`en-gb-x-rp`), kept on the prompt, read back as words with stress patterns.
  - `coverage.py`: what the recordings cover (phonemes, phoneme pairs, stress patterns, length, sentence type, style) and the ranker that orders written prompts by new coverage per second, every 5 usable takes.
  - `writer.py`: a batch of prompts from strata-models' `write` role, briefed with what is missing, each checked (length, no digits, a known kind and style) before it is kept.
  - `scoring.py`: a take's verdict (`good`, `retry` with each problem in words, or `unchecked`): clipping, level and noise floor here (`wav.measure`), the words through strata-models' `transcribe` role (word error rate against the prompt, `wer`), and the crop from the word timings. The master is never cut.
  - `system.py`: the app's numbers on the shared System page (takes, seconds of speech, size of the recordings).
- **React web app (`web/`)** on [strata-react](https://github.com/jburnhams/strata-react):
  - Screens: Studio (consent, the prompt, Record/Stop/Next with R, N and S, the live input level, the take played back from the server cropped to the speech, with its level and verdict; a take judged `retry` asks again at once, with Keep it anyway on K; undoable skip), Takes (every take, newest first, with its verdict, listen and undoable remove), Coverage (what is said and still missing in each group, least said first, and Write more prompts), System and Settings.
  - Recording is strata-react's `useRecorder` (an AudioWorklet with the browser's processing off, written as 16-bit PCM WAV), `InputLevel` and `TakeLevel`; the device comes from `MicrophoneContext`, so tests, stories and screenshots use `fakeMicrophone`.
  - Types from the server: `uv run strata-voice openapi` writes `web/openapi.json`, `npm run api-types` writes `web/src/api.generated.ts`, and `createTypedApi<paths>()` checks every call.
  - MSW handlers for every endpoint (`web/src/mocks/`) serve the jsdom tests, Storybook and the visual suite.
  - `npm run build` writes into `src/stratavoice/server/static/`.

## 3. Principles

- **Masters are lossless and never overwritten**: mono PCM WAV at the microphone's rate; a retry is another take, and the newest take of a prompt is the one in use.
- **Nothing is recorded before consent**, and the consent card says what is kept, where, and how to take it back.
- **What is heard is what was kept**: playback after a take comes from the server's copy.
- **Hermetic tests**, real WAV bytes through real servers, and coverage floors that only ratchet up.
