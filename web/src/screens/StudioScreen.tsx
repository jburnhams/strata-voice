// The one question: "What do I say next, and did that take work?" The finding says how far through the
// starter set the speaker is; then the prompt itself, large, with how to say it; then the one control that
// matters at each moment (Record, Stop, Next prompt) as the view's one filled button.
//
// Patterns, each the Strata way:
// - the read is useLoad -> DataView, with a skeleton shaped like the prompt card;
// - nothing records before consent: the consent card's AsyncButton writes the `consented_on` setting;
// - a take is kept the moment it stops (useAsyncAction, so the upload has its pending, done and error
//   states), judged by the server before it answers (scoring.py: levels, then the words through strata-models),
//   then played back from the server, cropped to the speech, so what is heard is what was kept;
// - a take judged `retry` asks again at once: its problems in words, Record again as the one filled button, and
//   "Keep it anyway" for a take the speaker knows is right (a name the recogniser does not know);
// - skipping is a reversible removal (useUndoable -> UndoBar): the server's queue holds the next few
//   prompts, so the one after shows at once while Undo is still in reach;
// - the studio is worked from the keyboard (useHotkeys + KeysLegend from one Shortcut list): R records,
//   stops and records again, N moves on, K keeps a take judged for another anyway, S skips.
// The level meter and the verdict after a take are the microphone check: a speaker sees the level while
// talking and hears back what was kept, which is what a calibration step would have told them. Capture, the
// WAV, the meter and the verdict are strata-react's (useRecorder, InputLevel, TakeLevel).
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  Alert,
  AsyncButton,
  Button,
  ButtonLink,
  DataView,
  Done,
  EmptyState,
  format,
  InputLevel,
  KeysLegend,
  MediaPlayer,
  Metric,
  MetricStrip,
  PageHeader,
  type Recording,
  type Shortcut,
  Skeleton,
  SPEECH_RATES,
  Status,
  TakeLevel,
  UndoBar,
  useAsyncAction,
  useHotkeys,
  useLoad,
  useRecorder,
  useUndoable,
} from 'strata-react'
import {
  api,
  crop,
  keys,
  kindName,
  type Progress,
  type Prompt,
  postTake,
  type Studio,
  type Take,
  takeAudio,
  today,
  verdictWord,
} from '../api'

/** The page's finding: how far through the prompts, and how much speech is kept. */
export function describeProgress(p: Progress): string {
  if (p.takes === 0) return `Nothing recorded yet. The starter set is ${format.count(p.prompts, 'prompt')}, about ten minutes of speech.`
  const skipped = p.skipped ? `, ${format.integer(p.skipped)} skipped` : ''
  return `${format.integer(p.recorded)} of ${format.count(p.prompts, 'prompt')} recorded${skipped}. ${format.runningTime(p.seconds)} of speech kept.`
}

export function StudioScreen() {
  const load = useLoad({ queryKey: keys.studio, queryFn: () => api.get('/api/studio') })
  return (
    <>
      <PageHeader
        title="Studio"
        scope="Recorded and kept on this computer"
        finding={load.status === 'ready' && load.data.consented ? { text: describeProgress(load.data.progress) } : undefined}
      />
      <DataView
        state={load}
        isEmpty={() => false}
        skeleton={<StudioSkeleton />}
        empty={<EmptyState title="No studio">The server sent nothing.</EmptyState>}
      >
        {s => (s.consented ? <Booth studio={s} /> : <Consent />)}
      </DataView>
    </>
  )
}

/** Mirrors the booth: the figures, the prompt card, the buttons. */
function StudioSkeleton() {
  return (
    <div className="grid gap-8" aria-hidden>
      <Skeleton className="h-16 w-full" />
      <div className="grid gap-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-2/3" />
      </div>
      <Skeleton className="h-(--control-h) w-40" />
    </div>
  )
}

/** Asked once: what is kept, where, and how to take it back. Recording starts only after it. */
function Consent() {
  const queryClient = useQueryClient()
  const agree = useAsyncAction(async () => {
    await api.put('/api/settings', { json: { consented_on: today() } })
    await queryClient.invalidateQueries({ queryKey: keys.studio })
    await queryClient.invalidateQueries({ queryKey: keys.settings })
  })
  return (
    <section aria-labelledby="consent" className="grid max-w-2xl gap-4">
      <h2 id="consent" className="type-heading">
        Before you record
      </h2>
      <ul className="grid list-disc gap-2 pl-5 type-body">
        <li>Each take is kept as an uncompressed recording in the recordings folder on this computer, and sent nowhere else.</li>
        <li>
          The takes are for building a model of your own voice. A model like that can be used to make speech that sounds like you, so keep
          the folder private.
        </li>
        <li>You can listen to and remove any take on the Takes screen, and stop recording by withdrawing consent in Settings.</li>
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        <AsyncButton
          variant="default"
          phase={agree.phase}
          error={agree.error}
          onClick={() => void agree.run()}
          labels={{ idle: 'I agree to be recorded', pending: 'Saving…', done: 'Saved' }}
        />
        {agree.phase === 'error' && <p className="type-body-sm text-danger">{agree.error} Nothing was changed.</p>}
      </div>
    </section>
  )
}

/** The take just kept, held while the speaker listens back. */
type Review = { prompt: Prompt; take: Take; recording: Recording }

function Booth({ studio }: { studio: Studio }) {
  const queryClient = useQueryClient()
  const undoable = useUndoable()
  const [review, setReview] = useState<Review | null>(null)
  const prompt = review?.prompt ?? studio.queue.find(p => !undoable.isRemoved(String(p.id)))

  const skip = (p: Prompt) =>
    undoable.schedule({
      id: String(p.id),
      message: `Skipped “${p.text}”.`,
      failure: `“${p.text}” is back: skipping it did not go through.`,
      commit: async () => {
        // No body: the generated type asks for `json` on every POST, and `undefined` sends none.
        await api.post('/api/prompts/{prompt_id}/skip', { path: { prompt_id: p.id }, json: undefined })
        await queryClient.invalidateQueries({ queryKey: keys.studio })
      },
    })

  return (
    <div className="grid gap-8">
      <MetricStrip label="Recorded so far">
        <Metric
          label="Prompts recorded"
          value={format.integer(studio.progress.recorded)}
          note={`of ${format.integer(studio.progress.prompts)}`}
        />
        <Metric
          label="Speech kept"
          value={format.runningTime(studio.progress.seconds)}
          note={format.count(studio.progress.takes, 'take')}
        />
        <Metric label="Skipped" value={format.integer(studio.progress.skipped)} note="Can be put back later" />
      </MetricStrip>
      {prompt ? (
        <PromptCard
          key={prompt.id}
          prompt={prompt}
          review={review}
          onKept={setReview}
          onNext={() => setReview(null)}
          onSkip={skip}
          maxSeconds={studio.max_take_seconds}
        />
      ) : (
        <Done
          title="Recorded every prompt"
          next="Listen back to your takes and remove any you want to redo; a removed take's prompt comes back here."
          actions={
            <ButtonLink to="/takes" variant="default">
              Listen to the takes
            </ButtonLink>
          }
        />
      )}
      <UndoBar undoable={undoable} />
    </div>
  )
}

/** One prompt: the words, how to say them, and the take's whole life from Record to Next prompt. */
function PromptCard({
  prompt,
  review,
  onKept,
  onNext,
  onSkip,
  maxSeconds,
}: {
  prompt: Prompt
  review: Review | null
  onKept: (r: Review) => void
  onNext: () => void
  onSkip: (p: Prompt) => void
  maxSeconds: number
}) {
  const queryClient = useQueryClient()
  const recorder = useRecorder({ maxSeconds })
  // A take that stopped but did not reach the server: held so Try again sends the same recording.
  const [unsaved, setUnsaved] = useState<Recording | null>(null)

  const keep = useAsyncAction(async (recording: Recording) => {
    const take = await postTake(prompt.id, recording.wav, recording.device)
    await queryClient.invalidateQueries({ queryKey: keys.studio })
    await queryClient.invalidateQueries({ queryKey: keys.takes })
    await queryClient.invalidateQueries({ queryKey: keys.system })
    setUnsaved(null)
    onKept({ prompt, take, recording })
  })
  const keeping = keep.phase === 'pending'
  const busy = recorder.recording || keeping
  // Judged for another take, and not kept anyway: the studio asks again rather than moving on.
  const retryTake = review && review.take.verdict === 'retry' && !review.take.accepted ? review.take : undefined
  const retry = !!retryTake

  // Skipping a prompt whose take was judged for another lets the take go too: the studio moves on.
  const skip = () => {
    onSkip(prompt)
    if (review) onNext()
  }

  const keepAnyway = useAsyncAction(async (take: Take) => {
    await api.post('/api/takes/{take_id}/accept', { path: { take_id: take.id }, json: undefined })
    await queryClient.invalidateQueries({ queryKey: keys.studio })
    await queryClient.invalidateQueries({ queryKey: keys.takes })
    onNext()
  })

  const record = async () => {
    setUnsaved(null)
    const recording = await recorder.start()
    if (!recording) return
    setUnsaved(recording)
    await keep.run(recording)
  }

  const shortcuts: Shortcut[] = [
    {
      keys: ['r'],
      label: recorder.recording ? 'Stop' : review ? 'Record again' : 'Record',
      run: () => (recorder.recording ? recorder.stop() : void record()),
      disabled: keeping,
    },
    { keys: ['n'], label: 'Next prompt', run: onNext, disabled: !review || retry || busy },
    {
      keys: ['k'],
      label: 'Keep it anyway',
      run: () => void keepAnyway.run(retryTake as Take),
      disabled: !retry || busy || keepAnyway.phase === 'pending',
    },
    { keys: ['s'], label: 'Skip', run: skip, disabled: (!!review && !retry) || busy },
  ]
  useHotkeys(shortcuts)

  return (
    <section aria-labelledby="prompt" className="grid gap-6">
      <div className="grid gap-2">
        <p className="type-label text-muted-foreground">{kindName(prompt.kind)}</p>
        <h2 id="prompt" className="type-title">
          {prompt.text}
        </h2>
        {prompt.cue && <p className="type-body text-muted-foreground">Say it: {prompt.cue}</p>}
      </div>

      {recorder.state.phase === 'recording' && (
        <div className="grid max-w-xl gap-2">
          <InputLevel level={recorder.state.level} seconds={recorder.state.seconds} maxSeconds={maxSeconds} />
        </div>
      )}

      {review && !keeping && <TakeReview review={review} />}

      <div className="flex flex-wrap items-center gap-3">
        {recorder.recording ? (
          <Button variant="default" onClick={() => recorder.stop()}>
            Stop
          </Button>
        ) : keeping ? (
          <AsyncButton variant="default" phase="pending" labels={{ idle: 'Keep take', pending: 'Checking the take…', done: 'Kept' }} />
        ) : retry ? (
          <>
            <Button variant="default" onClick={() => void record()}>
              Record again
            </Button>
            <AsyncButton
              variant="outline"
              phase={keepAnyway.phase}
              error={keepAnyway.error}
              onClick={() => void keepAnyway.run(retryTake as Take)}
              labels={{ idle: 'Keep it anyway', pending: 'Keeping…', done: 'Kept' }}
            />
            <Button variant="ghost" onClick={skip}>
              Skip
            </Button>
          </>
        ) : review ? (
          <>
            <Button variant="default" onClick={onNext}>
              Next prompt
            </Button>
            <Button variant="outline" onClick={() => void record()}>
              Record again
            </Button>
          </>
        ) : (
          <>
            <Button variant="default" onClick={() => void record()}>
              Record
            </Button>
            <Button variant="ghost" onClick={skip}>
              Skip
            </Button>
          </>
        )}
      </div>

      {recorder.state.phase === 'failed' && (
        <Alert tone="danger" title="Nothing was recorded" announce>
          {recorder.state.reason}
        </Alert>
      )}
      {keepAnyway.phase === 'error' && (
        <Alert tone="danger" title="The take was not kept" announce>
          {keepAnyway.error} Try Keep it anyway again, or record it again.
        </Alert>
      )}
      {keep.phase === 'error' && unsaved && (
        <Alert
          tone="danger"
          title="The take was not kept"
          announce
          action={
            <Button variant="outline" onClick={() => void keep.run(unsaved)}>
              Try again
            </Button>
          }
        >
          {keep.error} The recording is still here: try again to keep it.
        </Alert>
      )}
      <KeysLegend shortcuts={shortcuts} label="Studio keys" />
    </section>
  )
}

/** The take as the server kept it, cropped to the speech, with what its level says and how it was judged. */
function TakeReview({ review }: { review: Review }) {
  const { take, prompt } = review
  const window = crop(take)
  return (
    <div className="grid max-w-xl gap-3">
      <MediaPlayer
        label={`Your take of “${prompt.text}”`}
        kind="audio"
        src={takeAudio(take.id)}
        rates={SPEECH_RATES}
        window={window}
        showFull={!!window}
      />
      <TakeLevel peak={review.recording.peak} lead={`Kept ${format.runningTime(take.seconds)}`} />
      <TakeVerdict take={take} prompt={prompt} />
    </div>
  )
}

/** What the server made of the take just kept: its words heard, or each problem and what to do about it. A take
 *  kept anyway is never shown here: keeping it moves the studio on. */
export function TakeVerdict({ take, prompt }: { take: Take; prompt: Prompt }) {
  if (take.verdict === 'retry') {
    return (
      <Alert tone="warning" title="Record it again" announce>
        {take.problems.map(p => p.sentence).join(' ')}
      </Alert>
    )
  }
  const { tone, word } = verdictWord(take)
  const said =
    take.verdict !== 'good'
      ? 'The words were not checked: the speech recogniser was not running. They are checked later (strata-voice score).'
      : prompt.kind === 'spontaneous'
        ? `Heard “${take.transcript}”.`
        : 'Every word was heard. Played from just before the first word to just after the last.'
  return (
    <p className="flex items-baseline gap-2 type-body-sm">
      <Status tone={tone}>{word}</Status>
      <span className="min-w-0 flex-1">{said}</span>
    </p>
  )
}
