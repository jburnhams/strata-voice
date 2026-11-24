# Implementation plan

Agreed with Jonathan on 2026-11-23. Each step ends with something he can use.

- [x] **1. Studio shell** (2026-11-23): consent, a prompt card with Record, Stop, playback, Record again and Skip (keys R, N, S), the live input level and a level verdict, lossless WAV takes kept under `recordings/human/`, a Takes screen, and a JSONL manifest. The en-GB starter set (about ten minutes of speech) is seeded from `curriculum.py`. The capture, WAV and level code is shared: strata-react's `useRecorder`/`InputLevel`/`TakeLevel` and strata-python's `wav.read_wav`.
- [x] **2. Auto-crop and score** (2026-11-24): the crop from Whisper's word timings (through strata-models' `transcribe` role), clipping, level and noise floor (strata-python's `wav.measure`), the word error rate against the prompt (strata-python's `wer`), and the studio asking again at once for a take that fails, with Keep it anyway. A take the models service cannot hear yet is kept as `unchecked`, and `strata-voice score` judges it later. Importing existing audio waits: Jonathan has little yet and will gather it (2026-11-24).
- [ ] **3. Prompt generation and coverage**: a cloud model (Claude by default, through strata-models) writes prompts; a local en-GB phoneme, diphone and style coverage ranker orders them, re-ranked every 5 to 10 takes.
- [ ] **4. Pilot**: a session of about 8 to 10 minutes, then tune the thresholds from what it shows.

The app was made from python-app-template on 2026-11-23; the template's milestones are in its own repository.
