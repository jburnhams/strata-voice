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
import type { Progress, Prompt, Settings, Studio, Take, TakePage } from '../api'
import {
  defaultSettings,
  initialPrompts,
  initialTakes,
  manyTakes,
  systemNearlyFull as nearlyFull,
  silentWav,
  systemStatus,
} from './fixtures'

/** What the mock server holds. Writes change it, so a test can keep a take and see the queue move on. */
export const mock = {
  settings: { ...defaultSettings } as Settings,
  prompts: initialPrompts.map(p => ({ ...p })) as Prompt[],
  takes: [...initialTakes] as Take[],
}

/** Back to the healthy state: call between tests and stories. */
export function resetMock() {
  mock.settings = { ...defaultSettings }
  mock.prompts = initialPrompts.map(p => ({ ...p }))
  mock.takes = [...initialTakes]
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
  takesPage: '/api/takes/page',
  take: '/api/takes/:id',
  takeAudio: '/api/takes/:id/audio',
} as const

const withTakes = (p: Prompt): Prompt => ({ ...p, takes: mock.takes.filter(t => t.prompt_id === p.id).length })

/** `GET /api/studio` from what the mock holds, as studio.studio does. */
export function studioOf(state = mock): Studio {
  const recorded = new Set(state.takes.map(t => t.prompt_id))
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

/** Serves `GET /api/takes/page?after=<id>&limit=<n>` from a list, as studio.takes_page does: a Page with the server's own `next` cursor. */
export function takePage(url: string, list: Take[]): TakePage {
  const params = new URL(url).searchParams
  const after = params.get('after')
  const limit = Number(params.get('limit') ?? 20)
  const rest = after === null ? list : list.filter(t => t.id < Number(after))
  const items = rest.slice(0, limit)
  return { items, next: rest.length > limit ? String(items[items.length - 1].id) : null, total: null }
}

const refused = (detail: string, status = 400) => HttpResponse.json({ detail, payload: null }, { status })
const down = () => new HttpResponse(null, { status: 503, statusText: 'Service Unavailable' })

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
  http.post(at(paths.takesOf), async ({ request, params }) => {
    if (!mock.settings.consented_on) return refused('Agree to be recorded first: nothing is kept until you do.')
    const p = mock.prompts.find(x => x.id === Number(params.id))
    if (!p) return refused(`There is no prompt ${String(params.id)}.`, 404)
    const body = await request.arrayBuffer()
    const rate = new DataView(body).getUint32(24, true)
    const id = Math.max(0, ...mock.takes.map(t => t.id)) + 1
    const take: Take = {
      id,
      prompt_id: p.id,
      prompt_text: p.text,
      kind: p.kind,
      seconds: (body.byteLength - 44) / 2 / rate,
      sample_rate: rate,
      sample_width: 2,
      size_bytes: body.byteLength,
      device: new URL(request.url).searchParams.get('device'),
      created: '2026-11-23T09:30:00Z',
    }
    mock.takes = [take, ...mock.takes]
    return HttpResponse.json(take)
  }),
  http.post(at(paths.skip), ({ params }) => {
    const p = mock.prompts.find(x => x.id === Number(params.id))
    if (!p) return refused(`There is no prompt ${String(params.id)}.`, 404)
    p.skipped = true
    return HttpResponse.json(withTakes(p))
  }),
  http.get(at(paths.takesPage), ({ request }) => HttpResponse.json(takePage(request.url, mock.takes))),
  http.get(at(paths.takeAudio), () => new HttpResponse(silentWav(), { headers: { 'Content-Type': 'audio/wav' } })),
  http.delete(at(paths.take), ({ params }) => {
    const found = mock.takes.find(t => t.id === Number(params.id))
    if (!found) return refused(`There is no take ${String(params.id)}.`, 404)
    mock.takes = mock.takes.filter(t => t !== found)
    return HttpResponse.json(found)
  }),
]

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
export const skipFails = http.post(at(paths.skip), down)
export const consentFails = http.put(at(paths.settings), down)

export const takesLoading = http.get(at(paths.takesPage), () => delay('infinite'))
export const takesEmpty = http.get(at(paths.takesPage), () => HttpResponse.json({ items: [], next: null, total: null }))
export const takesError = http.get(at(paths.takesPage), down)
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
