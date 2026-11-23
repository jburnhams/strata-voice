// Sample data for the mock server (handlers.ts): the same records answer the unit and integration
// tests, every Storybook story and the visual suite's screenshots, so a screen looks the same in
// each. Dates are fixed, so screenshots do not change from day to day. The prompts are a few of the
// real starter curriculum's (src/stratavoice/curriculum.py).
import type { Prompt, Settings, SystemStatus, Take } from '../api'

export const defaultSettings: Settings = {
  recordings_dir: '/home/ada/.stratavoice/recordings',
  consented_on: '2026-11-23',
  max_take_seconds: 60,
}

const seeds: [string, string, string, string | null, string][] = [
  ['spont-01', 'spontaneous', 'Talk for about thirty seconds about what you did last weekend.', null, 'train'],
  ['spont-02', 'spontaneous', 'Describe the room you are sitting in, as if to someone on the phone.', null, 'train'],
  ['phon-01', 'phonetic', 'The thick fog over the harbour cleared just before the ferry left.', null, 'train'],
  ['phon-02', 'phonetic', 'She measured the beige fabric twice before cutting the pleasure boat’s sail.', null, 'train'],
  ['pros-07', 'prosodic', 'Well, that went better than expected.', 'dry, sarcastic', 'train'],
  ['expr-01', 'expressive', 'Oh, you’re joking! That’s brilliant news.', 'delighted', 'train'],
  ['expr-07', 'expressive', 'Shh, the baby’s finally asleep.', 'whispered', 'train'],
  ['eval-01', 'evaluation', 'The library closes early on Saturdays during the summer.', null, 'eval'],
]

/** The queue: every prompt, none recorded or skipped. */
export const initialPrompts: Prompt[] = seeds.map(([key, kind, text, cue, partition], i) => ({
  id: i + 1,
  key,
  kind,
  text,
  cue,
  partition,
  takes: 0,
  skipped: false,
}))

/** `n` takes, newest first, one every 3 minutes back from 09:12 UTC on 23 November 2026, cycling through the prompts. */
export function makeTakes(n: number): Take[] {
  const newest = Date.UTC(2026, 10, 23, 9, 12)
  return Array.from({ length: n }, (_, i) => {
    const id = n - i
    const p = initialPrompts[(id - 1) % initialPrompts.length]
    return {
      id,
      prompt_id: p.id,
      prompt_text: p.text,
      kind: p.kind,
      seconds: 2 + ((id * 7) % 11) + 0.25,
      sample_rate: 48_000,
      sample_width: 2,
      size_bytes: 400_000 + id * 1000,
      device: 'USB Audio Device',
      created: new Date(newest - i * 3 * 60_000).toISOString(),
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
