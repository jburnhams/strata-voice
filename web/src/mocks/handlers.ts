// The mock server: MSW handlers for every endpoint the app calls, answering like a healthy server.
// One set serves the jsdom tests (Node, tests/utils/server.ts), Storybook (a service worker,
// .storybook/preview.tsx) and the visual suite (Node, strata-visual.config.ts), so the app's real
// fetch, query and DataView code runs in all three and nothing is a module mock.
//
// The named handlers below each replace one route to put a test, story or screenshot into another
// state: `server.use(studioError)` in a test, `msw.use(studioError)` in a story's beforeEach,
// `states: { error: [studioError] }` in the visual config. The studio's answer is worked out from what the
// mock holds, as src/stratavoice/studio.py works it out from the database, so keeping or removing a take
// moves the queue on here too.
import { delay, HttpResponse, http } from 'msw'
import {
  type Coverage,
  type Progress,
  type Prompt,
  type PromptPage,
  type Settings,
  type Studio,
  type Take,
  type TakePage,
  type Upload,
  type UploadPage,
  usable,
  type Writing,
  type WritingPage,
  type WritingSummary,
} from '../api'
import { coverageSample } from './coverage-sample'
import {
  defaultSettings,
  failedUpload,
  goodScore,
  initialPrompts,
  initialTakes,
  kitchenSentences,
  kitchenUpload,
  makeTakes,
  manyTakes,
  misreadScore,
  systemNearlyFull as nearlyFull,
  silentWav,
  systemStatus,
  talkUpload,
  task,
  uncheckedScore,
  written,
} from './fixtures'
import { buildJob, manyWriting, runningBuild, writingBare, writingNever, writingRows, writingSummary } from './writing-sample'

/** What the mock server holds. Writes change it, so a test can keep a take and see the queue move on. */
export const mock = {
  settings: { ...defaultSettings } as Settings,
  prompts: initialPrompts.map(p => ({ ...p })) as Prompt[],
  takes: [...initialTakes] as Take[],
  coverage: { ...coverageSample } as Coverage,
  uploads: [kitchenUpload] as Upload[],
  sentences: [...kitchenSentences] as Take[],
  writing: { ...writingSummary } as WritingSummary,
  writingRows: writingRows.map(w => ({ ...w })) as Writing[],
}

/** Back to the healthy state: call between tests and stories. */
export function resetMock() {
  mock.settings = { ...defaultSettings }
  mock.prompts = initialPrompts.map(p => ({ ...p }))
  mock.takes = [...initialTakes]
  mock.coverage = { ...coverageSample }
  mock.uploads = [kitchenUpload]
  mock.sentences = [...kitchenSentences]
  mock.writing = { ...writingSummary }
  mock.writingRows = writingRows.map(w => ({ ...w }))
}

// Matched as paths, so they answer whatever origin and base the app runs under.
const at = (path: string) => `*${path}`

/** The endpoints, as the server's paths (src/stratavoice/server/app.py; the same keys as api.generated.ts). */
export const paths = {
  health: '/api/health',
  system: '/api/system',
  settings: '/api/settings',
  studio: '/api/studio',
  prompts: '/api/prompts',
  takesOf: '/api/prompts/:id/takes',
  skip: '/api/prompts/:id/skip',
  queue: '/api/queue',
  takesPage: '/api/takes/page',
  take: '/api/takes/:id',
  accept: '/api/takes/:id/accept',
  score: '/api/takes/:id/score',
  takeAudio: '/api/takes/:id/audio',
  coverage: '/api/coverage',
  write: '/api/prompts/write',
  uploads: '/api/uploads',
  uploadsPage: '/api/uploads/page',
  upload: '/api/uploads/:id',
  job: '/api/jobs/:id',
  jobCancel: '/api/jobs/:id/cancel',
  jobRetry: '/api/jobs/:id/retry',
  writing: '/api/writing',
  writingBuild: '/api/writing/build',
  writingPage: '/api/writing/page',
  writingCheck: '/api/writing/check',
  writingMark: '/api/writing/:id/check',
} as const

const withTakes = (p: Prompt): Prompt => ({ ...p, takes: mock.takes.filter(t => t.prompt_id === p.id).length })

/** `GET /api/studio` from what the mock holds, as studio.studio does. */
export function studioOf(state = mock): Studio {
  const recorded = new Set(state.takes.filter(usable).map(t => t.prompt_id))
  const progress: Progress = {
    prompts: state.prompts.length,
    recorded: recorded.size,
    skipped: state.prompts.filter(p => p.skipped).length,
    takes: state.takes.length,
    seconds: state.takes.reduce((n, t) => n + t.seconds, 0),
  }
  const queue = state.prompts.filter(p => !p.skipped && !recorded.has(p.id)).slice(0, 10)
  return { consented: state.settings.consented_on !== '', queue, progress, max_take_seconds: state.settings.max_take_seconds }
}

/** Serves `GET /api/queue?after=<position.id>&limit=<n>` as studio.queue_page does: the prompts still to record, in
 *  order, a page at a time. The mock's list order is the position. */
export function queuePage(url: string, state = mock): PromptPage {
  const params = new URL(url).searchParams
  const after = params.get('after')
  const limit = Number(params.get('limit') ?? 20)
  const recorded = new Set(state.takes.filter(usable).map(t => t.prompt_id))
  const placed = state.prompts.map((p, i) => ({ p, i })).filter(({ p }) => !p.skipped && !recorded.has(p.id))
  const rest = after === null ? placed : placed.filter(({ i }) => i > Number(after.split('.')[0]))
  const page = rest.slice(0, limit)
  const last = page[page.length - 1]
  return { items: page.map(({ p }) => p), next: rest.length > limit && last ? `${last.i}.${last.p.id}` : null, total: null }
}

/** Serves `GET /api/takes/page?after=<id>&limit=<n>` from a list, as studio.takes_page does: a Page with the server's own `next` cursor.
 *  With `upload=<id>`, the sentences of that upload from `mock.sentences`, oldest first. */
export function takePage(url: string, list: Take[]): TakePage {
  const params = new URL(url).searchParams
  const after = params.get('after')
  const limit = Number(params.get('limit') ?? 20)
  const upload = params.get('upload')
  if (upload !== null) {
    const of = mock.sentences.filter(t => t.upload_id === Number(upload))
    const rest = after === null ? of : of.filter(t => t.id > Number(after))
    const items = rest.slice(0, limit)
    return { items, next: rest.length > limit ? String(items[items.length - 1].id) : null, total: null }
  }
  const rest = after === null ? list : list.filter(t => t.id < Number(after))
  const items = rest.slice(0, limit)
  return { items, next: rest.length > limit ? String(items[items.length - 1].id) : null, total: null }
}

/** Serves `GET /api/uploads/page`, newest first, as ingest.uploads_page does. */
export function uploadPage(url: string, list: Upload[]): UploadPage {
  const params = new URL(url).searchParams
  const after = params.get('after')
  const limit = Number(params.get('limit') ?? 20)
  const sorted = [...list].sort((a, b) => b.id - a.id)
  const rest = after === null ? sorted : sorted.filter(u => u.id < Number(after))
  const items = rest.slice(0, limit)
  return { items, next: rest.length > limit ? String(items[items.length - 1].id) : null, total: null }
}

/** Serves `GET /api/writing/page`, newest first and filtered, as corpus.page does. */
export function writingPage(url: string, list: Writing[]): WritingPage {
  const params = new URL(url).searchParams
  const after = params.get('after')
  const limit = Number(params.get('limit') ?? 20)
  const medium = params.get('medium')
  const year = params.get('year')
  const trivial = params.get('trivial')
  const rest = [...list]
    .sort((a, b) => b.id - a.id)
    .filter(w => after === null || w.id < Number(after))
    .filter(w => !medium || w.medium === medium)
    .filter(w => !year || w.at.startsWith(year))
    .filter(w => trivial === null || String(w.trivial) === trivial)
  const items = rest.slice(0, limit)
  return { items, next: rest.length > limit ? String(items[items.length - 1].id) : null, total: null }
}

/** Marks a row as corpus.check does, and moves its medium's count of checked rows. */
function mark(id: number, verdict: string | null) {
  const found = mock.writingRows.find(w => w.id === id)
  if (!found) return refused(`There is no writing ${id}.`, 404)
  const changed = { ...found, checked_as: verdict }
  mock.writingRows = mock.writingRows.map(w => (w === found ? changed : w))
  const step = Number(verdict !== null) - Number(found.checked_as !== null)
  mock.writing = {
    ...mock.writing,
    mediums: mock.writing.mediums.map(m => (m.medium === found.medium ? { ...m, checked: m.checked + step } : m)),
  }
  return HttpResponse.json(changed)
}

const refused = (detail: string, status = 400) => HttpResponse.json({ detail, payload: null }, { status })
const down = () => new HttpResponse(null, { status: 503, statusText: 'Service Unavailable' })

/** Keeps a take as studio.add_take then scoring.score do: the WAV's length from its header, judged by `score`
 *  (good by default; the keepMisread and keepUnchecked states pass another). */
async function keep(request: Request, promptId: string | readonly string[] | undefined, score = goodScore) {
  if (!mock.settings.consented_on) return refused('Agree to be recorded first: nothing is kept until you do.')
  const p = mock.prompts.find(x => x.id === Number(promptId))
  if (!p) return refused(`There is no prompt ${String(promptId)}.`, 404)
  const body = await request.arrayBuffer()
  const rate = new DataView(body).getUint32(24, true)
  const id = Math.max(0, ...mock.takes.map(t => t.id)) + 1
  const seconds = (body.byteLength - 44) / 2 / rate
  const take: Take = {
    id,
    prompt_id: p.id,
    prompt_text: p.text,
    kind: p.kind,
    seconds,
    sample_rate: rate,
    sample_width: 2,
    size_bytes: body.byteLength,
    device: new URL(request.url).searchParams.get('device'),
    created: '2026-11-23T09:30:00Z',
    ...score(p, seconds),
  }
  mock.takes = [take, ...mock.takes]
  return HttpResponse.json(take)
}

export const handlers = [
  http.get(at(paths.health), () => HttpResponse.json({ ok: true, version: systemStatus.version, commit: systemStatus.commit })),
  http.get(at(paths.system), () => HttpResponse.json({ ...systemStatus, takes: mock.takes.length, seconds: studioOf().progress.seconds })),
  http.get(at(paths.settings), () => HttpResponse.json(mock.settings)),
  http.put(at(paths.settings), async ({ request }) => {
    const body = (await request.json()) as Partial<Settings>
    if (body.max_take_seconds !== undefined && (body.max_take_seconds < 5 || body.max_take_seconds > 300))
      return refused('max_take_seconds: must be a whole number from 5 to 300')
    mock.settings = { ...mock.settings, ...body }
    return HttpResponse.json(mock.settings)
  }),
  http.get(at(paths.studio), () => HttpResponse.json(studioOf())),
  http.get(at(paths.prompts), () => HttpResponse.json(mock.prompts.map(withTakes))),
  http.post(at(paths.takesOf), ({ request, params }) => keep(request, params.id)),
  http.post(at(paths.skip), ({ params }) => {
    const p = mock.prompts.find(x => x.id === Number(params.id))
    if (!p) return refused(`There is no prompt ${String(params.id)}.`, 404)
    p.skipped = true
    return HttpResponse.json(withTakes(p))
  }),
  http.get(at(paths.queue), ({ request }) => HttpResponse.json(queuePage(request.url))),
  http.get(at(paths.takesPage), ({ request }) => HttpResponse.json(takePage(request.url, mock.takes))),
  http.get(at(paths.takeAudio), () => new HttpResponse(silentWav(), { headers: { 'Content-Type': 'audio/wav' } })),
  http.post(at(paths.accept), ({ params }) => accept(Number(params.id), true)),
  http.delete(at(paths.accept), ({ params }) => accept(Number(params.id), false)),
  http.get(at(paths.coverage), () => HttpResponse.json(mock.coverage)),
  http.post(at(paths.write), async ({ request }) => {
    const { count = 40 } = (await request.json()) as { count?: number }
    if (count < 1 || count > 100) return refused('Ask for between 1 and 100 prompts at a time.')
    const added = Math.min(count, written.added)
    mock.coverage = { ...mock.coverage, waiting: mock.coverage.waiting + added }
    return HttpResponse.json({ ...written, offered: count, added, waiting: mock.coverage.waiting })
  }),
  http.get(at(paths.uploadsPage), ({ request }) => HttpResponse.json(uploadPage(request.url, mock.uploads))),
  http.post(at(paths.uploads), async ({ request }) => {
    if (!mock.settings.consented_on) return refused('Agree to be recorded first: nothing is kept until you do.')
    const name = new URL(request.url).searchParams.get('name') ?? 'recording'
    const body = await request.arrayBuffer()
    if (mock.uploads.some(u => u.name === name)) return refused(`${name} was brought in already, as ${name} on 2026-11-25.`)
    const id = Math.max(0, ...mock.uploads.map(u => u.id)) + 1
    const queued = task(id, { state: 'queued', started_at: null, finished_at: null, progress: null })
    const up: Upload = { ...talkUpload, id, name, size_bytes: body.byteLength, created: '2026-11-26T08:00:00Z', job: queued }
    mock.uploads = [...mock.uploads, up]
    return HttpResponse.json(up)
  }),
  http.get(at(paths.upload), ({ params }) => {
    const found = mock.uploads.find(u => u.id === Number(params.id))
    return found ? HttpResponse.json(found) : refused(`There is no upload ${String(params.id)}.`, 404)
  }),
  http.delete(at(paths.upload), ({ params }) => {
    const found = mock.uploads.find(u => u.id === Number(params.id))
    if (!found) return refused(`There is no upload ${String(params.id)}.`, 404)
    mock.uploads = mock.uploads.filter(u => u !== found)
    mock.sentences = mock.sentences.filter(t => t.upload_id !== found.id)
    return HttpResponse.json(found)
  }),
  http.get(at(paths.job), ({ params }) => {
    // A build the mock was asked for finishes as soon as it is asked about.
    if (params.id === String(buildJob.id) && mock.writing.job) {
      mock.writing = { ...mock.writing, job: buildJob }
      return HttpResponse.json(buildJob)
    }
    // The build a story or shot shows part way through stays there.
    if (params.id === String(runningBuild.id)) return HttpResponse.json(runningBuild)
    // The every-state fixtures too, which a story serves from its own handler rather than from `mock`.
    const found = [...mock.uploads, talkUpload, failedUpload].find(u => u.job && String(u.job.id) === params.id)?.job
    return found ? HttpResponse.json(found) : refused(`there is no job ${String(params.id)}`, 404)
  }),
  http.post(at(paths.jobCancel), ({ params }) => jobTo(String(params.id), { state: 'cancelled', finished_at: '2026-11-26T08:01:00Z' })),
  http.post(at(paths.jobRetry), ({ params }) => jobTo(String(params.id), { state: 'queued', error: null, finished_at: null })),
  http.get(at(paths.writing), () => HttpResponse.json(mock.writing)),
  http.post(at(paths.writingBuild), () => {
    const queued = { ...buildJob, state: 'queued' as const, started_at: null, finished_at: null, progress: null }
    mock.writing = { ...mock.writing, job: queued }
    return HttpResponse.json(queued)
  }),
  http.get(at(paths.writingPage), ({ request }) => HttpResponse.json(writingPage(request.url, mock.writingRows))),
  http.get(at(paths.writingCheck), ({ request }) => {
    const medium = new URL(request.url).searchParams.get('medium')
    return HttpResponse.json(
      mock.writingRows
        .filter(w => w.medium === medium && w.sample !== null && w.checked_as === null)
        .sort((a, b) => Number(a.sample) - Number(b.sample)),
    )
  }),
  http.post(at(paths.writingMark), async ({ request, params }) => {
    const { verdict } = (await request.json()) as { verdict: string }
    return mark(Number(params.id), verdict)
  }),
  http.delete(at(paths.writingMark), ({ params }) => mark(Number(params.id), null)),
  http.delete(at(paths.take), ({ params }) => {
    const found = mock.takes.find(t => t.id === Number(params.id))
    if (!found) return refused(`There is no take ${String(params.id)}.`, 404)
    mock.takes = mock.takes.filter(t => t !== found)
    return HttpResponse.json(found)
  }),
]

/** Keeps a take judged `retry` anyway, or takes that back, as studio.accept_take does (a studio take or a sentence
 *  of an upload, whose upload then counts it as kept). */
function accept(id: number, accepted: boolean) {
  const found = mock.takes.find(t => t.id === id) ?? mock.sentences.find(t => t.id === id)
  if (!found) return refused(`There is no take ${id}.`, 404)
  const changed = { ...found, accepted }
  mock.takes = mock.takes.map(t => (t === found ? changed : t))
  mock.sentences = mock.sentences.map(t => (t === found ? changed : t))
  if (found.upload_id !== null && found.verdict === 'retry' && accepted !== found.accepted) {
    const n = accepted ? 1 : -1
    mock.uploads = mock.uploads.map(u => (u.id === found.upload_id ? { ...u, kept: u.kept + n, other_voice: u.other_voice - n } : u))
  }
  return HttpResponse.json(changed)
}

/** Moves an upload's job to another state, as the queue's cancel and retry do. */
function jobTo(id: string, change: Partial<NonNullable<Upload['job']>>) {
  const found = mock.uploads.find(u => u.job && String(u.job.id) === id)
  if (id === String(buildJob.id) && mock.writing.job) {
    const job = { ...mock.writing.job, ...change }
    mock.writing = { ...mock.writing, job }
    return HttpResponse.json(job)
  }
  if (id === String(runningBuild.id)) return HttpResponse.json({ ...runningBuild, ...change })
  if (!found?.job) return refused(`there is no job ${id}`, 404)
  const job = { ...found.job, ...change }
  mock.uploads = mock.uploads.map(u => (u === found ? { ...u, job } : u))
  return HttpResponse.json(job)
}

// States. A request that never answers is "loading"; 503 is a server that is down. The app's query
// client retries once, so an error shows after about a second (tests turn retries off).

export const studioLoading = http.get(at(paths.studio), () => delay('infinite'))
export const studioError = http.get(at(paths.studio), down)
/** Before the speaker has agreed: the studio asks first. */
export const studioNotConsented = http.get(at(paths.studio), () =>
  HttpResponse.json(studioOf({ ...mock, settings: { ...mock.settings, consented_on: '' } })),
)
/** Every prompt recorded: the studio's done moment. */
export const studioDone = http.get(at(paths.studio), () =>
  HttpResponse.json(
    studioOf({ ...mock, takes: [...mock.takes, ...mock.prompts.map((p, i) => ({ ...initialTakes[0], id: 100 + i, prompt_id: p.id }))] }),
  ),
)
export const keepFails = http.post(at(paths.takesOf), down)
/** The next take kept is judged `retry`: words were missed, so the studio asks for it again. */
export const keepMisread = http.post(at(paths.takesOf), ({ request, params }) => keep(request, params.id, misreadScore))
/** The next take kept could not be heard: strata-models is not running, so its words are not checked. */
export const keepUnchecked = http.post(at(paths.takesOf), ({ request, params }) => keep(request, params.id, uncheckedScore))
export const acceptFails = http.post(at(paths.accept), down)
export const skipFails = http.post(at(paths.skip), down)
export const consentFails = http.put(at(paths.settings), down)

export const queueLoading = http.get(at(paths.queue), () => delay('infinite'))
export const queueError = http.get(at(paths.queue), down)

export const takesLoading = http.get(at(paths.takesPage), () => delay('infinite'))
export const takesEmpty = http.get(at(paths.takesPage), () => HttpResponse.json({ items: [], next: null, total: null }))
export const takesError = http.get(at(paths.takesPage), down)
/** Eleven takes: take 7 missed words and take 11 was not checked, so the list shows each verdict. */
export const takesJudged = http.get(at(paths.takesPage), ({ request }) => HttpResponse.json(takePage(request.url, makeTakes(11))))
/** 50 takes, three pages of 20. */
export const takesMany = http.get(at(paths.takesPage), ({ request }) => HttpResponse.json(takePage(request.url, manyTakes)))
export const removeFails = http.delete(at(paths.take), down)

export const systemLoading = http.get(at(paths.system), () => delay('infinite'))
export const systemError = http.get(at(paths.system), down)
export const systemNearlyFull = http.get(at(paths.system), () => HttpResponse.json(nearlyFull))

export const settingsLoading = http.get(at(paths.settings), () => delay('infinite'))
export const settingsError = http.get(at(paths.settings), down)
export const saveSettingsFails = http.put(at(paths.settings), down)
/** Consent not given yet: the Settings screen says so and points to the studio. */
export const settingsNotConsented = http.get(at(paths.settings), () => HttpResponse.json({ ...mock.settings, consented_on: '' }))
/** A server installed from a wheel (no source commit) whose folders' disk could not be read. */
export const systemUnread = http.get(at(paths.system), () => HttpResponse.json({ ...systemStatus, commit: null, folders: [] }))

export const coverageLoading = http.get(at(paths.coverage), () => delay('infinite'))
export const coverageError = http.get(at(paths.coverage), down)
/** Nothing recorded yet: every unit of every group unsaid. */
export const coverageNothing = http.get(at(paths.coverage), () =>
  HttpResponse.json({
    ...coverageSample,
    prompts: 0,
    waiting: 0,
    groups: coverageSample.groups.map(g => ({
      ...g,
      covered: 0,
      units: g.inventory === null ? [] : g.units.map(u => ({ ...u, count: 0 })),
    })),
  }),
)
/** espeak-ng is not installed: phonemes, pairs and stress are not counted. */
export const coverageNoEspeak = http.get(at(paths.coverage), () =>
  HttpResponse.json({
    ...coverageSample,
    phonemised: false,
    groups: coverageSample.groups.map(g =>
      ['phoneme', 'pair', 'stress'].includes(g.key)
        ? { ...g, covered: 0, units: g.inventory === null ? [] : g.units.map(u => ({ ...u, count: 0 })) }
        : g,
    ),
  }),
)
/** strata-models is not running: the writer cannot be asked. */
export const writeDown = http.post(at(paths.write), () =>
  refused('strata-models is not running, so no prompts can be written: start it and try again. (connection refused)', 503),
)
/** The server fails with no reason given. */
export const writeFails = http.post(at(paths.write), down)

export const uploadsLoading = http.get(at(paths.uploadsPage), () => delay('infinite'))
export const uploadsEmpty = http.get(at(paths.uploadsPage), () => HttpResponse.json({ items: [], next: null, total: null }))
export const uploadsError = http.get(at(paths.uploadsPage), down)
/** One recording of each state: ingested, still being worked on, and failed. */
export const uploadsEveryState = http.get(at(paths.uploadsPage), ({ request }) =>
  HttpResponse.json(uploadPage(request.url, [kitchenUpload, talkUpload, failedUpload])),
)
/** The server refuses a file ffprobe cannot read. */
export const uploadRefused = http.post(at(paths.uploads), ({ request }) =>
  refused(`${new URL(request.url).searchParams.get('name')} is not a recording ffmpeg can read.`),
)

export const writingLoading = http.get(at(paths.writing), () => delay('infinite'))
export const writingError = http.get(at(paths.writing), down)
/** Never built: the screen offers the first build. */
export const writingNeverBuilt = http.get(at(paths.writing), () => HttpResponse.json(writingNever))
/** A build waiting to run. */
export const writingBuilding = http.get(at(paths.writing), () => HttpResponse.json({ ...mock.writing, job: runningBuild }))
/** The newest build failed: the views were not there. */
export const writingBuildFailed = http.get(at(paths.writing), () =>
  HttpResponse.json({
    ...writingNever,
    job: {
      ...buildJob,
      state: 'failed',
      error:
        'unified.my_writing could not be read (no such table): build it with strata-takeout (`strata-takeout-unified build`), or set `writing_source`.',
    },
  }),
)
export const writingPageEmpty = http.get(at(paths.writingPage), () => HttpResponse.json({ items: [], next: null, total: null }))
export const writingPageError = http.get(at(paths.writingPage), down)
export const writingCheckError = http.get(at(paths.writingCheck), down)
export const writingMarkFails = http.post(at(paths.writingMark), down)
/** Built with no sample to check, no flags and nothing assisted. */
export const writingNoSample = http.get(at(paths.writing), () => HttpResponse.json(writingBare))
/** 70 pieces of chat: three pages. */
export const writingMany = http.get(at(paths.writingPage), ({ request }) => HttpResponse.json(writingPage(request.url, manyWriting)))
