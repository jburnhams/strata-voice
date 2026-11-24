// Sample data for the mock server (handlers.ts): the same records answer the unit and integration
// tests, every Storybook story and the visual suite's screenshots, so a screen looks the same in
// each. Dates are fixed, so screenshots do not change from day to day. The prompts are a few of the
// real starter curriculum's (src/stratavoice/curriculum.py).
import type { Prompt, Settings, SystemStatus, Take, Written } from '../api'

export const defaultSettings: Settings = {
  recordings_dir: '/home/ada/.stratavoice/recordings',
  consented_on: '2026-11-23',
  max_take_seconds: 60,
  espeak: '',
}

const seeds: [string, string, string, string | null, string, string | null][] = [
  ['spont-01', 'spontaneous', 'Talk for about thirty seconds about what you did last weekend.', null, 'train', null],
  ['spont-02', 'spontaneous', 'Describe the room you are sitting in, as if to someone on the phone.', null, 'train', null],
  ['phon-01', 'phonetic', 'The thick fog over the harbour cleared just before the ferry left.', null, 'train', 'neutral'],
  ['phon-02', 'phonetic', 'She measured the beige fabric twice before cutting the pleasure boat’s sail.', null, 'train', 'neutral'],
  ['pros-07', 'prosodic', 'Well, that went better than expected.', 'dry, sarcastic', 'train', 'sarcastic'],
  ['expr-01', 'expressive', 'Oh, you’re joking! That’s brilliant news.', 'delighted', 'train', 'excited'],
  ['expr-07', 'expressive', 'Shh, the baby’s finally asleep.', 'whispered', 'train', 'whispered'],
  ['eval-01', 'evaluation', 'The library closes early on Saturdays during the summer.', null, 'eval', 'neutral'],
]

/** The queue: every prompt, none recorded or skipped. The starter set's, in its order. */
export const initialPrompts: Prompt[] = seeds.map(([key, kind, text, cue, partition, style], i) => ({
  id: i + 1,
  key,
  kind,
  text,
  cue,
  partition,
  takes: 0,
  skipped: false,
  style,
  source: 'starter',
  score: null,
}))

/** What a batch from the prompt writer comes back as (`POST /api/prompts/write`). */
export const written: Written = { offered: 40, added: 37, writer: 'claude-sonnet-5-5-api', cost_usd: 0.031, waiting: 49 }

/** How the server judges a take that went well (scoring.py): every word heard, cropped a fifth of a second in from
 *  each end, at a good level in a quiet room. */
export function goodScore(
  p: Prompt,
  seconds: number,
): Pick<
  Take,
  | 'verdict'
  | 'problems'
  | 'accepted'
  | 'transcript'
  | 'asr_model'
  | 'wer'
  | 'peak_db'
  | 'noise_db'
  | 'speech_db'
  | 'clipped'
  | 'speech_start'
  | 'speech_end'
> {
  const read = p.kind !== 'spontaneous'
  return {
    verdict: 'good',
    problems: [],
    accepted: false,
    transcript: read ? p.text : 'Last weekend I walked along the canal and ended up at a market I had never seen before.',
    asr_model: 'whisper-large-v3-turbo',
    wer: read ? 0 : null,
    peak_db: -8.4,
    noise_db: -63.1,
    speech_db: -19.6,
    clipped: 0,
    speech_start: 0.2,
    speech_end: Math.round((seconds - 0.2) * 1000) / 1000,
  }
}

/** The same take judged `retry` because the reading missed words, as scoring.problems words it. */
export function misreadScore(p: Prompt, seconds: number): ReturnType<typeof goodScore> {
  const words = p.text.split(' ')
  const heard = words.slice(0, -2).join(' ')
  const missed = words.slice(-2).map(w => `“${w.replace(/[.,!?]/g, '').toLowerCase()}”`)
  return {
    ...goodScore(p, seconds),
    verdict: 'retry',
    problems: [{ code: 'words', sentence: `Some words were not the prompt's: ${missed.join(', ')}. It heard “${heard}”.` }],
    transcript: heard,
    wer: 2 / words.length,
  }
}

/** The same take before strata-models could hear it: levels fine, words not checked. */
export function uncheckedScore(p: Prompt, seconds: number): ReturnType<typeof goodScore> {
  return {
    ...goodScore(p, seconds),
    verdict: 'unchecked',
    transcript: null,
    asr_model: null,
    wer: null,
    speech_start: null,
    speech_end: null,
  }
}

/** `n` takes, newest first, one every 3 minutes back from 09:12 UTC on 23 November 2026, cycling through the prompts. */
export function makeTakes(n: number): Take[] {
  const newest = Date.UTC(2026, 10, 23, 9, 12)
  return Array.from({ length: n }, (_, i) => {
    const id = n - i
    const p = initialPrompts[(id - 1) % initialPrompts.length]
    const seconds = 2 + ((id * 7) % 11) + 0.25
    // Every seventh take misread and every eleventh not checked, so the list shows each verdict.
    const score = id % 7 === 0 ? misreadScore : id % 11 === 0 ? uncheckedScore : goodScore
    return {
      id,
      prompt_id: p.id,
      prompt_text: p.text,
      kind: p.kind,
      seconds,
      sample_rate: 48_000,
      sample_width: 2,
      size_bytes: 400_000 + id * 1000,
      device: 'USB Audio Device',
      created: new Date(newest - i * 3 * 60_000).toISOString(),
      ...score(p, seconds),
    }
  })
}

/** What the server holds in the healthy state: three takes, of the first three prompts. */
export const initialTakes = makeTakes(3)

/** A long list, for paging: 50 takes, so the Takes screen needs three pages of 20. */
export const manyTakes = makeTakes(50)

export const GB = 1e9

const folders = (total: number, free: number) => [
  { name: 'home', path: '/home/ada/.stratavoice', exists: true, total_bytes: total, free_bytes: free },
  { name: 'recordings', path: '/home/ada/.stratavoice/recordings', exists: true, total_bytes: total, free_bytes: free },
]

export const systemStatus: SystemStatus = {
  version: '0.1.0',
  commit: '1427b94c0ffee5ea1d2b3c4d5e6f708192a3b4c5',
  python: '3.13.1',
  platform: 'Linux-6.8.0-x86_64-with-glibc2.39',
  started_at: '2026-11-23T08:00:00Z',
  folders: folders(512 * GB, 210.4 * GB),
  services: [],
  takes: 3,
  seconds: 25.5,
  recordings_bytes: 2_448_000,
}

/** The same server with its disk past the "nearly full" threshold. */
export const systemNearlyFull: SystemStatus = { ...systemStatus, recordings_bytes: 2.4 * GB, folders: folders(512 * GB, 20 * GB) }

/** A short, silent WAV (16 kHz mono, a tenth of a second): what `GET /api/takes/{id}/audio` answers. */
export function silentWav(): ArrayBuffer {
  const frames = 1600
  const view = new DataView(new ArrayBuffer(44 + frames * 2))
  const text = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i))
  }
  text(0, 'RIFF')
  view.setUint32(4, 36 + frames * 2, true)
  text(8, 'WAVEfmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, 16_000, true)
  view.setUint32(28, 32_000, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, frames * 2, true)
  return view.buffer
}
