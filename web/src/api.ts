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
import { createTypedApi, fetchJson, format, type Tone } from 'strata-react'
import type { paths, Schema } from './api.generated'

export type Settings = Schema<'StratavoiceSettings'>
export type Studio = Schema<'Studio'>
export type Prompt = Schema<'PromptOut'>
// The studio's own Progress; FastAPI names it by its module, as strata-python's job Progress (in a Task) has the name too.
export type Progress = Schema<'stratavoice__studio__Progress'>
export type Take = Schema<'TakeOut'>
export type TakePage = Schema<'Page_TakeOut_'>
export type PromptPage = Schema<'Page_PromptOut_'>
export type Folder = Schema<'Folder'>
export type Coverage = Schema<'Coverage'>
export type CoverageGroup = Schema<'Group'>
export type Written = Schema<'Written'>
export type Upload = Schema<'UploadOut'>
export type UploadPage = Schema<'Page_UploadOut_'>
export type Task = Schema<'Task'>
/** `GET /api/system`: strata-python's SystemInfo plus this app's own numbers (src/stratavoice/system.py
 *  AppNumbers). Those are extra fields on the shared model, so the schema does not name them. */
export type SystemStatus = Schema<'SystemInfo'> & { takes: number; seconds: number; recordings_bytes: number }

export const api = createTypedApi<paths>()

/** The query keys the screens share, so a write can invalidate every read it changes. */
export const keys = {
  system: ['system'],
  settings: ['settings'],
  studio: ['studio'],
  // Under `studio`, so every write that invalidates the studio (a take kept or removed, a skip) refreshes the queue too.
  queue: ['studio', 'queue'],
  takes: ['takes'],
  coverage: ['coverage'],
  uploads: ['uploads'],
  job: (id: number | string) => ['jobs', String(id)] as const,
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

/** Brings in a recording (the Upload screen): the file itself as the body, whatever its format; the server reads
 *  what it is with ffprobe and refuses with a sentence what it cannot use. */
export function postUpload(file: File, signal?: AbortSignal): Promise<Upload> {
  return fetchJson<Upload>(api.url(`/api/uploads?name=${encodeURIComponent(file.name)}`), {
    method: 'POST',
    body: file,
    headers: { 'Content-Type': 'application/octet-stream' },
    signal,
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

/** A take's verdict as a status word, the same on every screen. A sentence cut from an upload cannot be recorded
 *  again, so a `retry` there is left out of the dataset: by someone else's voice, or for its other problems. */
export function verdictWord(t: Take): { tone: Tone; word: string } {
  if (t.verdict === 'good') return { tone: 'success', word: 'Good take' }
  if (t.verdict === 'retry' && t.accepted) return { tone: 'info', word: 'Kept anyway' }
  if (t.verdict === 'retry' && t.upload_id !== null)
    return t.problems.some(p => p.code === 'speaker') ? { tone: 'neutral', word: 'Someone else' } : { tone: 'warning', word: 'Left out' }
  if (t.verdict === 'retry') return { tone: 'warning', word: 'Record again' }
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
  found: 'From an upload',
}

/** A prompt's group in words; a group this build does not know yet (from a newer server) shows as the server names it. */
export const kindName = (kind: string) => kindNames[kind] ?? kind

/** An upload's job as a status word (src/stratavoice/ingest.py runs it on strata-python's queue). A queued job with an
 *  error is one waiting to be tried again: strata-models was not there to hear it. */
export function uploadWord(u: Upload): { tone: Tone; word: string; active: boolean } {
  const job = u.job
  if (job === null) return { tone: 'success', word: 'Done', active: false }
  if (job.state === 'running') return { tone: 'info', word: 'Working', active: true }
  if (job.state === 'queued')
    return job.error ? { tone: 'warning', word: 'Waiting for models', active: true } : { tone: 'info', word: 'Waiting', active: true }
  if (job.state === 'failed') return { tone: 'danger', word: 'Failed', active: false }
  if (job.state === 'cancelled') return { tone: 'neutral', word: 'Stopped', active: false }
  return { tone: 'success', word: 'Done', active: false }
}

/** The upload's job while it is queued or running (the "Working on" section polls it), else null. */
export const activeJob = (u: Upload): Task | null => (uploadWord(u).active ? u.job : null)

/** What an upload gave, in a sentence: "2 of 3 sentences kept, 0:04 of speech; 1 someone else’s." */
export function uploadSummary(u: Upload): string {
  if (u.job?.state === 'failed') return u.job.error ?? 'It could not be brought in.'
  const job = activeJob(u)
  if (job) {
    if (job.state === 'queued' && job.error) return 'strata-models is not running or is busy; it will be tried again.'
    return job.progress?.text || 'Waiting to start.'
  }
  if (u.sentences === 0) return 'No speech was found in it.'
  const parts = [`${u.kept} of ${format.count(u.sentences, 'sentence')} kept, ${format.runningTime(u.kept_seconds)} of speech`]
  if (u.other_voice) parts.push(`${u.other_voice} someone else’s`)
  if (u.retry) parts.push(`${u.retry} left out for noise or a cut word`)
  if (u.speaker_reference === null) parts.push('voices not checked')
  return `${parts.join('; ')}.`
}
