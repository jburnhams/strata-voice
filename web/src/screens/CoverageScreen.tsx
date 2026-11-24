// The one question: "What have my recordings not covered yet, and what will the studio ask for next?"
// The finding answers with the sounds and styles still missing (or said least), read from GET /api/coverage
// (src/stratavoice/coverage.py, counted over every prompt with a usable take). Then, in the order a person asks:
// what waits in the queue and a way to get more (the prompt writer, the view's one filled button, since it is the
// only action here), then each group of what speech covers: how much of its inventory has been said (a Meter where
// the set is known, a count where it is open) and its least said units, which are what the ranker reaches for.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  AsyncButton,
  DataView,
  describeActionError,
  EmptyState,
  format,
  HttpError,
  Meter,
  PageHeader,
  Skeleton,
  useAsyncAction,
  useLoad,
} from 'strata-react'
import { api, type Coverage, type CoverageGroup, keys, type Written } from '../api'

/** How many prompts one press asks the writer for (writer.DEFAULT_COUNT). */
export const BATCH = 40
/** How many of each group's least said units are listed. */
export const LEAST = 10

const quote = (s: string) => `“${s}”`
const group = (c: Coverage, key: string) => c.groups.find(g => g.key === key) as CoverageGroup

/** A unit as a person reads it: a phoneme between slashes with a word that has it, anything else as it is. */
export function unitName(g: CoverageGroup, u: CoverageGroup['units'][number]): string {
  if (g.key === 'phoneme') return `/${u.value}/ as in ${quote(String(u.example))}` // every phoneme has its word
  // Primary stress loud, secondary half (Da), none quiet: folding secondary into "da" would print 02, 20 and 00 as
  // three identical "da da" rows.
  if (g.key === 'stress')
    return u.value
      .replace(/1/g, 'DA')
      .replace(/2/g, 'Da')
      .replace(/0/g, 'da')
      .replace(/(da|DA|Da)(?=d|D)/g, '$1 ')
  return u.value
}

/** The page's finding: the sounds and styles still missing, or said least. */
export function describeCoverage(c: Coverage): string {
  if (c.prompts === 0) return 'Nothing is recorded yet, so every sound and style is still to say.'
  const sounds = group(c, 'phoneme')
  const styles = group(c, 'style')
  const missing = (g: CoverageGroup) => g.units.filter(u => u.count === 0)
  let first: string
  if (!c.phonemised) first = 'Sounds are not counted: espeak-ng is not installed on the server.'
  else if (missing(sounds).length > 0) {
    const names = missing(sounds)
      .slice(0, 3)
      .map(u => unitName(sounds, u))
      .join(', ')
    first = `${sounds.covered} of ${sounds.inventory} sounds said; not yet ${names}${missing(sounds).length > 3 ? ' and more' : ''}.`
  } else {
    const least = sounds.units[0]
    first = `Every sound has been said; the least is ${unitName(sounds, least)}, ${format.count(least.count, 'time')}.`
  }
  return `${first} ${styles.covered} of ${styles.inventory} styles said.`
}

/** What a batch did, in words. */
export function describeWritten(w: Written): string {
  return `${w.writer ?? 'The writer'} wrote ${w.offered}; ${format.count(w.added, 'new prompt')} kept. ${format.count(w.waiting, 'written prompt')} now wait.`
}

function CoverageSkeleton() {
  return (
    <div className="grid gap-10" aria-hidden>
      <Skeleton className="h-20 w-full max-w-xl" />
      <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
        {[0, 1, 2, 3].map(i => (
          <Skeleton key={i} className="h-48" />
        ))}
      </div>
    </div>
  )
}

function Next({ coverage }: { coverage: Coverage }) {
  const queryClient = useQueryClient()
  const [last, setLast] = useState<Written | null>(null)
  const write = useAsyncAction(
    async () => {
      setLast(null)
      setLast(await api.post('/api/prompts/write', { json: { count: BATCH } }))
      await queryClient.invalidateQueries({ queryKey: keys.coverage })
      await queryClient.invalidateQueries({ queryKey: keys.studio })
    },
    {
      // strata-models down is a 503 whose reason says what to do (start it); the default would say only the status.
      describeError: (e: unknown) => (e instanceof HttpError && e.reason) || describeActionError(e),
    },
  )
  return (
    <section aria-labelledby="next" className="grid max-w-2xl gap-3">
      <h2 id="next" className="type-heading">
        What comes next
      </h2>
      <p className="type-body">
        {coverage.waiting === 0
          ? 'No written prompts wait. After the starter set the studio asks for these, the ones that add the most first.'
          : `${format.count(coverage.waiting, 'written prompt')} wait after the starter set, the ones that add the most first. The order is worked out again every five takes.`}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <AsyncButton
          variant="default"
          phase={write.phase}
          error={write.error}
          onClick={() => void write.run()}
          labels={{ idle: `Write ${BATCH} more prompts`, pending: 'Writing…', done: 'Written' }}
        />
        <span className="type-body-sm text-muted-foreground">
          A cloud model writes them from what is missing; only the prompts’ words are sent.
        </span>
      </div>
      {last && <p className="type-body-sm">{describeWritten(last)}</p>}
      {write.phase === 'error' && <p className="type-body-sm text-danger">{write.error} No prompts were added.</p>}
    </section>
  )
}

function Group({ g }: { g: CoverageGroup }) {
  const id = `group-${g.key}`
  const least = g.units.slice(0, LEAST)
  return (
    <section aria-labelledby={id} className="grid content-start gap-3">
      <h2 id={id} className="type-heading">
        {g.title}
      </h2>
      {g.inventory === null ? (
        <p className="type-body-sm">{format.count(g.covered, 'different one')} said so far.</p>
      ) : (
        <Meter label={`${g.title} said at least once`} value={g.covered} max={g.inventory} valueText={`${g.covered} of ${g.inventory}`} />
      )}
      {least.length > 0 && (
        <table className="type-body-sm">
          <caption className="text-left text-muted-foreground">Least said</caption>
          <tbody>
            {least.map(u => (
              <tr key={u.value}>
                <th scope="row" className="py-0.5 pr-6 text-left font-normal">
                  {unitName(g, u)}
                </th>
                <td className="py-0.5 text-right tabular-nums">{u.count === 0 ? 'Not yet' : format.integer(u.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export function CoverageScreen() {
  const load = useLoad({ queryKey: keys.coverage, queryFn: () => api.get('/api/coverage') })
  return (
    <>
      <PageHeader
        title="Coverage"
        scope={load.status === 'ready' ? `Over ${format.count(load.data.prompts, 'recorded prompt')}` : 'Over the recorded prompts'}
        finding={load.status === 'ready' ? { text: describeCoverage(load.data) } : undefined}
      />
      <DataView
        state={load}
        isEmpty={() => false}
        skeleton={<CoverageSkeleton />}
        empty={<EmptyState title="Nothing to count">The server sent no coverage.</EmptyState>}
      >
        {c => (
          <div className="grid gap-10">
            <Next coverage={c} />
            <div className="grid grid-cols-1 gap-x-12 gap-y-10 md:grid-cols-2">
              {c.groups.map(g => (
                <Group key={g.key} g={g} />
              ))}
            </div>
          </div>
        )}
      </DataView>
    </>
  )
}
