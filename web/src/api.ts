// The server's endpoints, typed from the server itself. `./strata-voice openapi` writes web/openapi.json from the
// FastAPI routes, and `npm run api-types` (strata-react's strata-api-types) turns it into
// api.generated.ts, which is committed and never edited: a route or model change on the Python side
// shows up here as a type error, and CI fails a stale file on both sides (`strata-voice openapi --check`,
// `npm run api-types:check`).
//
// Reads go through useLoad / useInfiniteLoad and writes through useAsyncAction; both call `api`, a
// createTypedApi over the generated paths, so the path, its {params}, the query, the JSON body and the
// answer are all checked. It puts the app's base before every path (the server gives every page a
// relative <base> back to its root, so the app works behind a reverse proxy at /<prefix>/), and a
// non-2xx answer throws HttpError with the server's own sentence (`detail`) as its `reason`. The one
// body that is not JSON, a take's WAV, goes through `postTake`.
import { createTypedApi, fetchJson, type Tone } from 'strata-react'
import type { paths, Schema } from './api.generated'

export type Settings = Schema<'StratavoiceSettings'>
export type Studio = Schema<'Studio'>
export type Prompt = Schema<'PromptOut'>
export type Progress = Schema<'Progress'>
export type Take = Schema<'TakeOut'>
export type TakePage = Schema<'Page_TakeOut_'>
export type Folder = Schema<'Folder'>
export type Coverage = Schema<'Coverage'>
export type CoverageGroup = Schema<'Group'>
export type Written = Schema<'Written'>
/** `GET /api/system`: strata-python's SystemInfo plus this app's own numbers (src/stratavoice/system.py
 *  AppNumbers). Those are extra fields on the shared model, so the schema does not name them. */
export type SystemStatus = Schema<'SystemInfo'> & { takes: number; seconds: number; recordings_bytes: number }

export const api = createTypedApi<paths>()

/** The query keys the screens share, so a write can invalidate every read it changes. */
export const keys = {
  system: ['system'],
  settings: ['settings'],
  studio: ['studio'],
  takes: ['takes'],
  coverage: ['coverage'],
} as const

/** Keeps a take: the WAV itself as the body (not JSON, so no base64), with the microphone's name when the browser gave one. */
export function postTake(promptId: number, wav: Blob, device: string | null): Promise<Take> {
  const query = device ? `?device=${encodeURIComponent(device)}` : ''
  return fetchJson<Take>(api.url(`/api/prompts/${promptId}/takes${query}`), {
    method: 'POST',
    body: wav,
    headers: { 'Content-Type': 'audio/wav' },
  })
}

/** Where a take's WAV is served, for a player's `src`. */
export const takeAudio = (id: number) => api.url(`/api/takes/${id}/audio`)

/** A take's crop (scoring.py's `speech_start`..`speech_end`) as a player's `window`, or undefined before it is scored:
 *  playback starts at the first word and stops after the last, while the master on disk stays whole. */
export function crop(t: Take): { start: number; end: number } | undefined {
  return t.speech_start === null || t.speech_end === null ? undefined : { start: t.speech_start, end: t.speech_end }
}

/** Whether a take counts for its prompt: anything but a `retry` the speaker did not keep anyway (studio._usable). */
export const usable = (t: Take) => t.verdict !== 'retry' || t.accepted

/** A take's verdict as a status word, the same on every screen. */
export function verdictWord(t: Take): { tone: Tone; word: string } {
  if (t.verdict === 'good') return { tone: 'success', word: 'Good take' }
  if (t.verdict === 'retry') return t.accepted ? { tone: 'info', word: 'Kept anyway' } : { tone: 'warning', word: 'Record again' }
  return { tone: 'neutral', word: 'Not checked' }
}

/** Today as the server's settings write a date (YYYY-MM-DD), in the person's own time zone. */
export function today(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** The curriculum's groups, in the words the studio shows above a prompt (src/stratavoice/curriculum.py). */
const kindNames: Record<string, string> = {
  phonetic: 'Read aloud',
  prosodic: 'Read with this delivery',
  expressive: 'Read with feeling',
  evaluation: 'Held out for testing',
}

/** A prompt's group in words; a group this build does not know yet (from a newer server) shows as the server names it. */
export const kindName = (kind: string) => kindNames[kind] ?? kind
