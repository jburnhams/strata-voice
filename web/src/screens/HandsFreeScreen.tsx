// The one question: "What do I read now?" Hands-free: the microphone stays open (strata-react's useAutoRecorder
// cuts each stretch of speech out as its own take), the take goes to the prompt showing when the speaker started
// it, and the screen moves to the next prompt at once, so a session is read straight through without a click.
//
// Patterns, each the Strata way:
// - the studio read (consent, the longest take, progress) is useLoad -> DataView, as on the Studio screen, and
//   nothing listens before consent (the same consent card);
// - the prompts still to read are a cursor-paged read (useInfiniteLoad over GET /api/queue -> InfiniteList), the
//   "infinite scroll" asked for: the prompt being read sits above it, and prompts already said this visit are
//   hidden from it (`isRemoved`) until the server's queue catches up;
// - takes are kept one after another in the background (a promise chain, so they reach the server in the order they
//   were said, which the pilot report and "the newest take is the one in use" both read), each a row under "Said
//   this visit" that goes from Checking to its verdict. A take judged `retry` is not kept for its prompt, so the
//   server's queue has the prompt again: it shows up in the list after the one being read (the current prompt never
//   jumps while the speaker reads it). A row offers Keep it anyway, and Try again when the upload failed;
// - the prompt a take belongs to is fixed when the speaker starts talking, not when the take ends, since the screen
//   has moved on by then;
// - skipping is a reversible removal (useUndoable -> UndoBar), as in the studio;
// - keys (useHotkeys + KeysLegend from one Shortcut list): L starts and stops listening, P pauses, S skips.
import { useQueryClient } from '@tanstack/react-query'
import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from 'react'
import {
  Alert,
  type AutoTake,
  apiPage,
  Button,
  ButtonLink,
  DataView,
  Done,
  describeActionError,
  EmptyState,
  format,
  InfiniteList,
  KeysLegend,
  ListeningLevel,
  PageHeader,
  RowAction,
  type Shortcut,
  Skeleton,
  Status,
  type Tone,
  UndoBar,
  useAutoRecorder,
  useHotkeys,
  useInfiniteLoad,
  useLoad,
  useUndoable,
} from 'strata-react'
import { api, keys, kindName, type Prompt, postTake, type Studio, type Take, verdictWord } from '../api'
import { Consent } from './StudioScreen'

/** Prompts per page of the queue. */
export const QUEUE_PAGE = 20

/** One take said this visit, from the moment it was cut to its verdict. */
export type Said = {
  n: number
  prompt: Prompt
  recording: AutoTake
  phase: 'saving' | 'saved' | 'failed'
  take?: Take
  error?: string
}

/** Whether a said take holds its prompt (kept, or on its way): such a prompt is not offered again. */
export const holds = (s: Said) =>
  s.phase === 'saving' || (s.phase === 'saved' && !!s.take && (s.take.verdict !== 'retry' || s.take.accepted))

/** A said take's status word: Checking while it is kept and judged, then the studio's own words. */
export function saidWord(s: Said): { tone: Tone; word: string } {
  if (s.phase === 'saving') return { tone: 'neutral', word: 'Checking…' }
  if (!s.take) return { tone: 'danger', word: 'Not kept' } // failed: a saved take always has its answer
  if (s.take.verdict === 'retry' && !s.take.accepted) return { tone: 'warning', word: 'Back in the queue' }
  return verdictWord(s.take)
}

/** Why a write did not go through, in the words the rest of the app uses. */
export const failed = (e: unknown) => describeActionError(e) ?? 'It did not go through.'

/** The page's finding: what this visit has said so far. */
export function describeVisit(said: readonly Said[]): string | undefined {
  if (!said.length) return undefined
  const count = (f: (s: Said) => boolean) => said.filter(f).length
  const good = count(s => s.phase === 'saved' && holds(s))
  const back = count(s => s.phase === 'saved' && !holds(s))
  const checking = count(s => s.phase === 'saving')
  const failed = count(s => s.phase === 'failed')
  const parts = [
    `${format.integer(good)} kept`,
    back ? `${format.integer(back)} back in the queue` : '',
    checking ? `${format.integer(checking)} being checked` : '',
    failed ? `${format.integer(failed)} not kept` : '',
  ].filter(Boolean)
  return `${format.count(said.length, 'take')} said this visit: ${parts.join(', ')}.`
}

export function HandsFreeScreen() {
  const load = useLoad({ queryKey: keys.studio, queryFn: () => api.get('/api/studio') })
  // Held here, above the booth, so the header's finding can say what this visit has said.
  const [said, setSaid] = useState<Said[]>([])
  const finding = describeVisit(said)
  return (
    <>
      <PageHeader
        title="Hands-free"
        scope="Read each prompt aloud; the next one follows by itself"
        finding={finding ? { text: finding } : undefined}
      />
      <DataView
        state={load}
        isEmpty={() => false}
        skeleton={<BoothSkeleton />}
        empty={<EmptyState title="No studio">The server sent nothing.</EmptyState>}
      >
        {s => (s.consented ? <HandsFree studio={s} said={said} setSaid={setSaid} /> : <Consent />)}
      </DataView>
    </>
  )
}

/** Mirrors the booth: the controls and level, the prompt, the list. */
function BoothSkeleton() {
  return (
    <div className="grid gap-8" aria-hidden>
      <Skeleton className="h-(--control-h) w-48" />
      <div className="grid gap-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-10 w-full" />
      </div>
      <RowsSkeleton rows={5} />
    </div>
  )
}

function RowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 py-3">
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-28" />
        </div>
      ))}
    </div>
  )
}

function HandsFree({ studio, said, setSaid }: { studio: Studio; said: Said[]; setSaid: Dispatch<SetStateAction<Said[]>> }) {
  const queryClient = useQueryClient()
  const undoable = useUndoable()
  const [currentId, setCurrentId] = useState<number | null>(null)
  // The last skip: the prompt skipped and the one pinned in its place, so Undo can bring the skipped one back.
  const [skipped, setSkipped] = useState<{ from: number; to: number | null } | null>(null)
  const [paused, setPaused] = useState(false)

  const queue = useInfiniteLoad({
    queryKey: keys.queue,
    queryFn: ({ cursor, signal }) => api.get('/api/queue', { query: { after: cursor ?? null, limit: QUEUE_PAGE }, signal }),
    itemKey: (p: Prompt) => String(p.id),
    ...apiPage<Prompt>(),
  })
  const held = new Set(said.filter(holds).map(s => s.prompt.id))
  const open = (p: Prompt) => !held.has(p.id) && !undoable.isRemoved(String(p.id))
  const waiting = queue.status === 'ready' ? queue.data.filter(open) : []
  // Undone: the skipped prompt is shown again while its replacement is still the one showing.
  const undone =
    skipped && skipped.to === currentId && !undoable.isRemoved(String(skipped.from)) ? waiting.find(p => p.id === skipped.from) : undefined
  const current = undone ?? waiting.find(p => p.id === currentId) ?? waiting[0]
  const finished = queue.status === 'ready' && !current && !queue.more.hasMore && !said.some(s => s.phase === 'saving')

  // The prompt a take is for, fixed when the speaker started saying it.
  const saying = useRef<Prompt | undefined>(undefined)
  const chain = useRef<Promise<void>>(Promise.resolve())
  const next = useRef(1)

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: keys.studio }) // the queue too: its key is under the studio's
    await queryClient.invalidateQueries({ queryKey: keys.coverage })
    await queryClient.invalidateQueries({ queryKey: keys.takes })
    await queryClient.invalidateQueries({ queryKey: keys.system })
  }

  const update = (n: number, change: Partial<Said>) => setSaid(all => all.map(s => (s.n === n ? { ...s, ...change } : s)))

  // Kept in the order said: each upload waits for the one before.
  const send = (n: number, prompt: Prompt, recording: AutoTake) => {
    chain.current = chain.current.then(async () => {
      update(n, { phase: 'saving', error: undefined })
      try {
        const take = await postTake(prompt.id, recording.wav, recording.device)
        update(n, { phase: 'saved', take })
      } catch (e) {
        update(n, { phase: 'failed', error: failed(e) })
      }
      await refresh()
    })
  }

  const onTake = (recording: AutoTake) => {
    const prompt = saying.current
    saying.current = undefined
    // Set when the speaker started (below), and the recorder is paused while no prompt shows, so a take always has
    // one; the guard is for the type.
    /* v8 ignore next -- @preserve */
    if (!prompt) return
    const n = next.current++
    setSaid(all => [{ n, prompt, recording, phase: 'saving' }, ...all])
    // On to the first prompt still waiting: the next in order, or one an earlier take put back in the queue.
    setCurrentId(waiting.find(p => p.id !== prompt.id)?.id ?? null)
    send(n, prompt, recording)
  }

  const recorder = useAutoRecorder({ maxSeconds: studio.max_take_seconds, paused: paused || !current, onTake })
  const state = recorder.state
  const speaking = state.phase === 'listening' && state.speaking
  useEffect(() => {
    if (speaking && !saying.current) saying.current = current
  }, [speaking, current])

  const keepAnyway = async (s: Said, kept: Take) => {
    try {
      const take = await api.post('/api/takes/{take_id}/accept', { path: { take_id: kept.id } })
      update(s.n, { take })
    } catch (e) {
      update(s.n, { error: failed(e) })
    }
    await refresh()
  }

  const skip = (p: Prompt) => {
    // Pinned by id, so a take that comes back as a retry while this skip is open does not take the replacement's
    // place; Undo brings this one back to the front (`undone` above).
    const to = waiting.find(w => w.id !== p.id)?.id ?? null
    setCurrentId(to)
    setSkipped({ from: p.id, to })
    undoable.schedule({
      id: String(p.id),
      message: `Skipped “${p.text}”.`,
      failure: `“${p.text}” is back: skipping it did not go through.`,
      commit: async () => {
        await api.post('/api/prompts/{prompt_id}/skip', { path: { prompt_id: p.id } })
        await refresh()
      },
    })
  }

  const shortcuts: Shortcut[] = [
    {
      keys: ['l'],
      label: recorder.listening ? 'Stop listening' : 'Start listening',
      run: () => (recorder.listening ? recorder.stop() : void recorder.start()),
      disabled: finished,
    },
    { keys: ['p'], label: paused ? 'Resume' : 'Pause', run: () => setPaused(p => !p), disabled: !recorder.listening },
    { keys: ['s'], label: 'Skip', run: () => current && skip(current), disabled: !current || speaking },
  ]
  useHotkeys(shortcuts)
  return (
    <div className="grid gap-8">
      <div className="grid gap-8">
        {finished ? (
          <Done
            title="Read every prompt"
            next="Each take is on the Takes screen, where you can listen back and remove any you want to read again."
            actions={
              <ButtonLink to="/takes" variant="default">
                Listen to the takes
              </ButtonLink>
            }
          />
        ) : (
          <section aria-labelledby="now" className="grid gap-6">
            <div className="flex flex-wrap items-center gap-3">
              {recorder.listening ? (
                <>
                  <Button variant="default" onClick={() => setPaused(p => !p)}>
                    {paused ? 'Resume' : 'Pause'}
                  </Button>
                  <Button variant="outline" onClick={recorder.stop}>
                    Stop listening
                  </Button>
                </>
              ) : (
                <Button variant="default" onClick={() => void recorder.start()} disabled={!current}>
                  Start listening
                </Button>
              )}
              {current && (
                <Button variant="ghost" onClick={() => skip(current)} disabled={speaking}>
                  Skip
                </Button>
              )}
            </div>
            {state.phase === 'listening' && (
              <div className="grid max-w-xl gap-2">
                <ListeningLevel state={state} maxSeconds={studio.max_take_seconds} />
              </div>
            )}
            {state.phase === 'failed' && (
              <Alert tone="danger" title="Not listening" announce>
                {state.reason}
              </Alert>
            )}
            {current ? (
              <div className="grid gap-2">
                <p className="type-label text-muted-foreground">
                  {state.phase === 'listening' && !state.paused ? 'Say this now' : 'Next to say'} · {kindName(current.kind)}
                </p>
                <h2 id="now" className="type-title">
                  {current.text}
                </h2>
                {current.cue && <p className="type-body text-muted-foreground">Say it: {current.cue}</p>}
              </div>
            ) : (
              <h2 id="now" className="type-heading text-muted-foreground">
                {queue.status === 'ready' ? 'Waiting for the last takes to be checked…' : 'Finding the next prompt…'}
              </h2>
            )}
          </section>
        )}

        {said.length > 0 && (
          <SaidList said={said} onRetry={s => send(s.n, s.prompt, s.recording)} onKeep={(s, take) => void keepAnyway(s, take)} />
        )}

        <section aria-labelledby="next-up" className="grid gap-2">
          <h2 id="next-up" className="type-heading">
            Next up
          </h2>
          <InfiniteList
            state={queue}
            label="Prompts still to read, in order"
            moreLabel="Show more prompts"
            skeleton={<RowsSkeleton rows={6} />}
            moreSkeleton={<RowsSkeleton />}
            empty={<p className="type-body-sm text-muted-foreground">Nothing after this one.</p>}
            end="That is every prompt still to read."
            estimateSize={41}
          >
            {p =>
              !open(p) || p.id === current?.id ? null : (
                <div className="flex items-center gap-4 py-2 type-body-sm">
                  <span className="min-w-0 flex-1 truncate">{p.text}</span>
                  <span className="hidden w-40 shrink-0 text-muted-foreground sm:block">{kindName(p.kind)}</span>
                  <RowAction label="Read now" subject={p.text} onClick={() => setCurrentId(p.id)} disabled={speaking} />
                </div>
              )
            }
          </InfiniteList>
        </section>
      </div>
      <KeysLegend shortcuts={shortcuts} label="Hands-free keys" />
      <UndoBar undoable={undoable} />
    </div>
  )
}

/** The takes said this visit, newest first: each prompt, its status, and what to do about a take not kept. */
function SaidList({ said, onRetry, onKeep }: { said: Said[]; onRetry: (s: Said) => void; onKeep: (s: Said, take: Take) => void }) {
  return (
    <section aria-labelledby="said" className="grid gap-2">
      <h2 id="said" className="type-heading">
        Said this visit
      </h2>
      <ol className="grid divide-y divide-border" aria-label="Takes said this visit, newest first">
        {said.map(s => {
          const { tone, word } = saidWord(s)
          // A take judged for another and not kept anyway: its prompt is back in the queue.
          const back = s.phase === 'saved' && !holds(s) ? s.take : undefined
          return (
            <li key={s.n} className="grid gap-1 py-2 type-body-sm">
              <div className="flex items-center gap-4">
                <span className="min-w-0 flex-1 truncate">{s.prompt.text}</span>
                <span className="w-12 shrink-0 text-right tabular-nums">{format.runningTime(s.recording.seconds)}</span>
                <span className="w-40 shrink-0">
                  <Status tone={tone}>{word}</Status>
                </span>
                <span className="flex w-28 shrink-0 justify-end gap-1">
                  {s.phase === 'failed' && <RowAction label="Try again" subject={s.prompt.text} onClick={() => onRetry(s)} />}
                  {back && <RowAction label="Keep it anyway" subject={s.prompt.text} onClick={() => onKeep(s, back)} />}
                </span>
              </div>
              {back && <p className="text-muted-foreground">{back.problems.map(p => p.sentence).join(' ')}</p>}
              {s.recording.cut && <p className="text-muted-foreground">Cut at the longest take: say it again if it ran on.</p>}
              {s.error && <p className="text-danger">{s.error} The recording is still here.</p>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
