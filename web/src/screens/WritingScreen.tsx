// The one question: "Is what I wrote read, cleaned and split right, so the written voice can learn from it and be
// tested fairly?" The corpus (src/stratavoice/writing/corpus.py) is built in the background from strata-takeout's view of
// everything the person sent (emails, chats, posts, prompts to assistants): mails lose the quoted text and signatures,
// a run of chat lines becomes one piece, short replies are set aside as trivial, copies are flagged, and every piece
// falls in a split frozen on the first build (the newest year and some correspondents sealed for testing). The finding
// says how much there is and what is sealed. Then three tabs, in the order a person asks (in the URL, so a reload keeps
// one): what it holds and a way to build it again; the pieces themselves, filtered, with what cleaning took out struck
// through; and the cleaning sample, checked from the keyboard, because the cleaning is only trusted once a person
// has read enough of it (each mark can be undone for a few seconds, then is sent).
import { useQueryClient } from '@tanstack/react-query'
import {
  AsyncButton,
  apiPage,
  Button,
  CompositionBar,
  DataTable,
  DataView,
  EmptyState,
  Field,
  format,
  InfiniteList,
  JobStatus,
  KeysLegend,
  Meter,
  NativeSelect,
  PageHeader,
  type Shortcut,
  Skeleton,
  Status,
  TableSkeleton,
  Tabs,
  UndoBar,
  useAsyncAction,
  useHotkeys,
  useInfiniteLoad,
  useJob,
  useLoad,
  useSearchParam,
  useUndoable,
} from 'strata-react'
import {
  api,
  flagName,
  keys,
  type MediumCount,
  mediumName,
  pieces,
  removedName,
  splitName,
  type Task,
  verdicts,
  type Writing,
  type WritingSummary,
} from '../api'

/** Pieces per page. */
export const PAGE_SIZE = 30

const tabs = [
  { value: 'overview', label: 'Overview' },
  { value: 'browse', label: 'Browse' },
  { value: 'check', label: 'Check cleaning' },
]

const running = (t: Task | null) => t !== null && (t.state === 'queued' || t.state === 'running')
const year = (iso: string) => new Date(iso).getUTCFullYear()

/** The page's finding: how much writing there is, how much counts, and what is sealed for testing. */
export function describeWriting(s: WritingSummary): string {
  if (s.rows === 0) {
    if (s.job?.state === 'failed') return 'Nothing is read yet: the last build failed.'
    if (running(s.job)) return 'Nothing is read yet: the first build is running.'
    return 'Nothing is read yet: build the corpus from strata-takeout’s view of what you sent.'
  }
  const trivial = s.mediums.reduce((n, m) => n + m.trivial, 0)
  const words = s.mediums.reduce((n, m) => n + m.words, 0)
  const first = Math.min(...s.mediums.map(m => year(m.first)))
  const last = Math.max(...s.mediums.map(m => year(m.last)))
  const kept = `${format.count(s.rows - trivial, 'piece', 'pieces', { compact: true })} of writing from ${first} to ${last}, ${format.count(words, 'word', 'words', { compact: true })}; ${format.count(trivial, 'short reply', 'short replies', { compact: true })} set aside.`
  if (s.cutoff === null) return kept
  return `${kept} Everything since ${format.date(s.cutoff)} and ${format.count(s.holdout, 'correspondent')} are sealed for testing.`
}

/** What a build is doing, or why it stopped. */
export function describeBuild(t: Task): string {
  if (t.state === 'failed') return t.error ?? 'The build stopped.'
  return t.progress?.text || 'Waiting to start.'
}

/** A medium's row in the overview's sample column: how far the check has got. */
export function describeChecked(m: MediumCount): string {
  if (m.sample === 0) return 'No sample'
  if (m.checked === 0) return `${m.sample} to check`
  return `${m.checked} of ${m.sample} checked, ${m.clean} right`
}

export function WritingScreen() {
  const load = useLoad({ queryKey: keys.writing, queryFn: () => api.get('/api/writing') })
  return (
    <>
      <PageHeader
        title="My writing"
        scope="What you sent, from strata-takeout: cleaned, joined and split for the written voice"
        finding={load.status === 'ready' ? { text: describeWriting(load.data) } : undefined}
      />
      <DataView
        state={load}
        isEmpty={() => false}
        skeleton={<OverviewSkeleton />}
        empty={<EmptyState title="Nothing to show">The server sent no summary.</EmptyState>}
      >
        {s =>
          s.rows === 0 ? (
            <Build summary={s} />
          ) : (
            <Tabs param="tab" items={tabs} label="My writing">
              {tab => (tab === 'browse' ? <Browse summary={s} /> : tab === 'check' ? <Check summary={s} /> : <Overview summary={s} />)}
            </Tabs>
          )
        }
      </DataView>
    </>
  )
}

function OverviewSkeleton() {
  return (
    <div className="grid gap-8" aria-hidden>
      <Skeleton className="h-10 w-72" />
      <TableSkeleton rows={6} columns={6} />
    </div>
  )
}

/** Build again (or the first time), and the newest build's job while it runs or when it failed. */
function Build({ summary }: { summary: WritingSummary }) {
  const queryClient = useQueryClient()
  const start = useAsyncAction(async () => {
    await api.post('/api/writing/build')
    await queryClient.invalidateQueries({ queryKey: keys.writing })
  })
  const job = summary.job
  const busy = running(job)
  return (
    <section aria-labelledby="build" className="grid max-w-2xl gap-3">
      <h2 id="build" className="type-heading">
        {summary.built ? 'Build again' : 'Build the corpus'}
      </h2>
      <p className="type-body">
        {summary.built
          ? `Last built ${format.dateTime(summary.built)}. Building again reads the view afresh and keeps the split and your checks.`
          : 'Reads every email, chat, post and prompt you sent from strata-takeout’s view, cleans and joins them, and freezes the split. Nothing leaves this server.'}
      </p>
      {job && (busy || job.state === 'failed') ? (
        <BuildJob initial={job} />
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <AsyncButton
            variant="default"
            phase={start.phase}
            error={start.error}
            onClick={() => void start.run()}
            labels={{ idle: summary.built ? 'Build again' : 'Build the corpus', pending: 'Starting…', done: 'Started' }}
          />
        </div>
      )}
    </section>
  )
}

function BuildJob({ initial }: { initial: Task }) {
  const queryClient = useQueryClient()
  const job = useJob({
    queryKey: keys.job(initial.id),
    queryFn: ({ signal }) => api.get('/api/jobs/{job_id}', { path: { job_id: Number(initial.id) }, signal }),
    initialData: initial,
    isRunning: (t: Task) => running(t),
    invalidates: [keys.writing],
  })
  /* v8 ignore next -- @preserve: started from initialData, so the read is always ready */
  const task = job.status === 'ready' ? job.data : initial
  const p = task.progress
  const retry = async () => {
    await api.post('/api/jobs/{job_id}/retry', { path: { job_id: Number(task.id) } })
    await queryClient.invalidateQueries({ queryKey: keys.writing })
    job.poll()
  }
  return (
    <div className="grid gap-2">
      <JobStatus
        label="Building the corpus"
        running={job.running}
        words={{
          running: task.state === 'queued' ? 'Waiting' : 'Building',
          finished: 'Built',
          failed: 'Could not build it',
          cancelled: 'Stopped',
        }}
        summary={describeBuild(task)}
        progress={p?.total ? { done: p.done, total: p.total } : undefined}
        failed={task.state === 'failed'}
        cancelled={task.state === 'cancelled'}
        onCancel={() => void api.post('/api/jobs/{job_id}/cancel', { path: { job_id: Number(task.id) } }).then(() => job.poll())}
        cancelLabel="Stop"
      />
      {task.state === 'failed' && (
        <div>
          <Button variant="default" onClick={() => void retry()}>
            Try the build again
          </Button>
        </div>
      )}
    </div>
  )
}

function Overview({ summary }: { summary: WritingSummary }) {
  return (
    <div className="grid gap-10">
      <Build summary={summary} />
      <section aria-labelledby="mediums" className="grid gap-3">
        <h2 id="mediums" className="type-heading">
          By medium
        </h2>
        <DataTable
          caption="Writing by medium"
          rows={summary.mediums}
          rowKey={m => m.medium}
          columns={[
            { key: 'medium', header: 'Medium', value: m => mediumName(m.medium) },
            { key: 'rows', header: 'Pieces', numeric: true, value: m => m.rows - m.trivial, cell: m => format.integer(m.rows - m.trivial) },
            { key: 'trivial', header: 'Short replies', numeric: true, value: m => m.trivial, cell: m => format.integer(m.trivial) },
            { key: 'words', header: 'Words', numeric: true, value: m => m.words, cell: m => format.compact(m.words) },
            { key: 'span', header: 'Years', value: m => year(m.first), cell: m => `${year(m.first)}–${year(m.last)}` },
            { key: 'checked', header: 'Cleaning sample', value: m => m.checked, cell: describeChecked },
          ]}
        />
      </section>
      <section aria-labelledby="split" className="grid max-w-2xl gap-3">
        <h2 id="split" className="type-heading">
          The split
        </h2>
        <p className="type-body">
          Frozen on the first build, before anything learns from it. Train is what a model learns from, dev what it is tuned on, sealed what
          it is tested on once at the end; the buffer is the week before the sealed year, left out so a conversation does not straddle the
          line.
        </p>
        <CompositionBar
          label="Pieces by split"
          parts={summary.splits.map(c => ({ key: c.value, label: splitName(c.value), value: c.rows }))}
          formatValue={n => format.integer(n)}
          partHeader="Split"
          valueHeader="Pieces"
        />
        {summary.assisted > 0 && (
          <p className="type-body-sm text-muted-foreground">
            {format.count(summary.assisted, 'piece was', 'pieces were', { compact: true })} written since chat assistants came out. They
            count, and are marked so the reference set can leave out any written with help.
          </p>
        )}
      </section>
      {summary.flags.length > 0 && (
        <section aria-labelledby="flags" className="grid max-w-md gap-3">
          <h2 id="flags" className="type-heading">
            Flagged
          </h2>
          <DataTable
            caption="Pieces flagged"
            rows={summary.flags}
            rowKey={c => c.value}
            columns={[
              { key: 'flag', header: 'Flag', value: c => flagName(c.value) },
              { key: 'rows', header: 'Pieces', numeric: true, value: c => c.rows, cell: c => format.integer(c.rows) },
            ]}
          />
        </section>
      )}
    </div>
  )
}

/** A piece's text with what cleaning took out struck through and named. */
function Text({ w }: { w: Writing }) {
  return (
    <p className="type-body whitespace-pre-wrap break-words">
      {pieces(w).map((p, i) =>
        p.removed === null ? (
          <span key={i}>{p.text}</span>
        ) : (
          <del key={i} className="text-muted-foreground" title={`Taken out: ${removedName(p.removed)}`}>
            {p.text}
          </del>
        ),
      )}
    </p>
  )
}

/** The facts under a piece: when, where, its split, and anything marked about it. */
function Facts({ w }: { w: Writing }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 type-body-sm text-muted-foreground">
      <span className="tabular-nums">{format.dateTime(w.at)}</span>
      <span>{mediumName(w.medium)}</span>
      {w.subject && <span className="min-w-0 truncate">{w.subject}</span>}
      {w.parts > 1 && <span>{format.count(w.parts, 'message')} joined</span>}
      <Status tone={w.split === 'sealed' ? 'info' : 'neutral'}>{splitName(w.split)}</Status>
      {w.trivial && <Status tone="neutral">Short reply</Status>}
      {w.assisted && <Status tone="neutral">Assistants out</Status>}
      {w.flags.map(f => (
        <Status key={f} tone="warning">
          {flagName(f)}
        </Status>
      ))}
    </div>
  )
}

function RowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="grid gap-2 py-3">
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="h-3 w-64" />
        </div>
      ))}
    </div>
  )
}

const shows = ['kept', 'trivial', 'all'] as const
type Show = (typeof shows)[number]

function Browse({ summary }: { summary: WritingSummary }) {
  const [medium] = useSearchParam('medium', { default: '', parse: raw => summary.mediums.some(m => m.medium === raw) })
  const [yearParam] = useSearchParam('year', { default: '', parse: raw => summary.years.some(y => y.value === raw) })
  const [show] = useSearchParam<Show>('show', { default: 'kept', parse: (raw): raw is Show => (shows as readonly string[]).includes(raw) })
  const trivial = show === 'all' ? null : show === 'trivial'
  const query = { medium: medium || null, year: yearParam ? Number(yearParam) : null, trivial }
  const rows = useInfiniteLoad({
    queryKey: [...keys.writingPage, query],
    queryFn: ({ cursor, signal }) =>
      api.get('/api/writing/page', { query: { after: cursor === undefined ? null : Number(cursor), limit: PAGE_SIZE, ...query }, signal }),
    itemKey: (w: Writing) => String(w.id),
    ...apiPage<Writing>(),
  })
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap gap-4">
        <Field label="Medium" className="w-56">
          <NativeSelect param="medium" paramDefault="">
            <option value="">Every medium</option>
            {summary.mediums.map(m => (
              <option key={m.medium} value={m.medium}>
                {mediumName(m.medium)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Year" className="w-36">
          <NativeSelect param="year" paramDefault="">
            <option value="">Every year</option>
            {[...summary.years].reverse().map(y => (
              <option key={y.value} value={y.value}>
                {y.value}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Show" className="w-48">
          <NativeSelect param="show" paramDefault="kept">
            <option value="kept">What counts</option>
            <option value="trivial">Short replies</option>
            <option value="all">Everything</option>
          </NativeSelect>
        </Field>
      </div>
      <InfiniteList
        state={rows}
        label="Your writing, newest first"
        moreLabel="Show older writing"
        skeleton={<RowsSkeleton rows={5} />}
        moreSkeleton={<RowsSkeleton />}
        empty={<EmptyState title="Nothing here">Nothing you wrote matches these filters: choose another medium or year.</EmptyState>}
        end="That is everything that matches."
        scroll="page"
        listClassName="grid divide-y divide-border"
      >
        {w => (
          <article className="grid gap-2 py-3">
            <Text w={w} />
            <Facts w={w} />
          </article>
        )}
      </InfiniteList>
    </div>
  )
}

function Check({ summary }: { summary: WritingSummary }) {
  const queryClient = useQueryClient()
  const undoable = useUndoable()
  // Rows are there (the tabs show only then), so there is a first medium.
  const first = (summary.mediums.find(m => m.checked < m.sample) ?? summary.mediums[0]).medium
  const [medium] = useSearchParam('medium', { default: first, parse: raw => summary.mediums.some(m => m.medium === raw) })
  const count = summary.mediums.find(m => m.medium === medium) as MediumCount
  const load = useLoad({
    queryKey: [...keys.writingCheck, medium],
    queryFn: ({ signal }) => api.get('/api/writing/check', { query: { medium }, signal }),
  })
  const left = load.status === 'ready' ? load.data.filter(w => !undoable.isRemoved(String(w.id))) : []
  const current = left[0] ?? null

  const answer = (w: Writing, verdict: (typeof verdicts)[number]) => {
    undoable.schedule({
      id: String(w.id),
      message: `Marked “${verdict.label}”.`,
      failure: 'That piece is back: the mark did not go through.',
      commit: async () => {
        await api.post('/api/writing/{writing_id}/check', { path: { writing_id: w.id }, json: { verdict: verdict.value } })
        await queryClient.invalidateQueries({ queryKey: keys.writing })
      },
    })
  }
  // No keys while nothing is left to check.
  const shortcuts: Shortcut[] = current ? verdicts.map(v => ({ keys: [v.key], label: v.label, run: () => answer(current, v) })) : []
  useHotkeys(shortcuts)

  return (
    <div className="grid max-w-3xl gap-6">
      <div className="flex flex-wrap items-end gap-4">
        <Field label="Medium" className="w-56">
          <NativeSelect param="medium" paramDefault={first}>
            {summary.mediums.map(m => (
              <option key={m.medium} value={m.medium}>
                {mediumName(m.medium)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        {count.sample > 0 && (
          <Meter
            className="w-64"
            label="Sample checked"
            value={count.checked}
            max={count.sample}
            valueText={`${count.checked} of ${count.sample}`}
          />
        )}
      </div>
      <p className="type-body-sm text-muted-foreground">
        A fixed sample of each medium, drawn the same way every build. Read each piece: struck-through text is what cleaning took out. Say
        whether it got it right; ten wrong in fifty means the cleaning needs work before anything learns from it.
      </p>
      <DataView
        state={load}
        isEmpty={() => current === null}
        skeleton={<RowsSkeleton rows={2} />}
        empty={
          <EmptyState title={`${mediumName(medium)}: ${count.sample > 0 ? 'all checked' : 'nothing to check'}`}>
            {count.sample > 0
              ? `${count.clean} of ${count.sample} were cleaned right. Choose another medium to check its sample.`
              : 'This medium has no sample to check.'}
          </EmptyState>
        }
      >
        {() => {
          // Shown only while a piece is left (isEmpty above).
          const w = current as Writing
          return (
            <section aria-labelledby="checking" className="grid gap-4">
              <h2 id="checking" className="type-heading">
                {w.subject ?? `${mediumName(w.medium)}, ${format.date(w.at)}`}
              </h2>
              <div className="rounded-surface border border-border p-4">
                <Text w={w} />
              </div>
              <Facts w={w} />
              <div className="flex flex-wrap gap-2">
                {verdicts.map(v => (
                  <Button key={v.value} variant="outline" onClick={() => answer(w, v)}>
                    {v.label}
                  </Button>
                ))}
              </div>
              <KeysLegend shortcuts={shortcuts} label="Keys for checking" />
            </section>
          )
        }}
      </DataView>
      <UndoBar undoable={undoable} />
    </div>
  )
}
