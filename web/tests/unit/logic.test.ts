import { readFileSync } from 'node:fs'
import { colorSchemeScript, format } from 'strata-react'
import { describe, expect, it } from 'vitest'
import { crop, kindName, today, usable, verdictWord } from '../../src/api'
import { coverageSample } from '../../src/mocks/coverage-sample'
import {
  initialPrompts,
  makeTakes,
  misreadScore,
  silentWav,
  systemNearlyFull,
  systemStatus,
  uncheckedScore,
} from '../../src/mocks/fixtures'
import { mock, studioOf, takePage } from '../../src/mocks/handlers'
import { describeCoverage, describeWritten, unitName } from '../../src/screens/CoverageScreen'
import { describeVisit, failed, type Said, saidWord } from '../../src/screens/HandsFreeScreen'
import { secondsProblem } from '../../src/screens/SettingsScreen'
import { describeProgress } from '../../src/screens/StudioScreen'
import { describeDisk, ofSize, recordingsDisk } from '../../src/screens/SystemScreen'

describe('the studio finding', () => {
  it("names a prompt's group, and a group it does not know as the server names it", () => {
    expect(kindName('phonetic')).toBe('Read aloud')
    expect(kindName('scenario')).toBe('scenario')
  })

  it('says how far through the prompts and how much speech is kept', () => {
    expect(describeProgress({ prompts: 44, recorded: 0, skipped: 0, takes: 0, seconds: 0 })).toBe(
      `Nothing recorded yet. The starter set is ${format.count(44, 'prompt')}, about ten minutes of speech.`,
    )
    expect(describeProgress({ prompts: 44, recorded: 3, skipped: 0, takes: 4, seconds: 65 })).toBe(
      `3 of ${format.count(44, 'prompt')} recorded. 1:05 of speech kept.`,
    )
    expect(describeProgress({ prompts: 44, recorded: 3, skipped: 2, takes: 4, seconds: 65 })).toBe(
      `3 of ${format.count(44, 'prompt')} recorded, 2 skipped. 1:05 of speech kept.`,
    )
  })

  it("writes today's date as the settings do, in the person's own zone", () => {
    expect(today(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05')
  })
})

describe("a take's verdict", () => {
  const [good] = makeTakes(1)
  const misread = { ...good, ...misreadScore(initialPrompts[0], good.seconds) }
  const unchecked = { ...good, ...uncheckedScore(initialPrompts[0], good.seconds) }

  it('reads the same word on every screen', () => {
    expect(verdictWord(good)).toEqual({ tone: 'success', word: 'Good take' })
    expect(verdictWord(misread)).toEqual({ tone: 'warning', word: 'Record again' })
    expect(verdictWord({ ...misread, accepted: true })).toEqual({ tone: 'info', word: 'Kept anyway' })
    expect(verdictWord(unchecked)).toEqual({ tone: 'neutral', word: 'Not checked' })
    expect(verdictWord({ ...good, verdict: null })).toEqual({ tone: 'neutral', word: 'Not checked' })
  })

  it('counts a take for its prompt unless it is to be recorded again', () => {
    expect([good, misread, { ...misread, accepted: true }, unchecked].map(usable)).toEqual([true, false, true, true])
  })

  it('plays a scored take from just before its first word to just after its last', () => {
    expect(crop(good)).toEqual({ start: 0.2, end: good.seconds - 0.2 })
    expect(crop(unchecked)).toBeUndefined()
  })
})

describe('settings', () => {
  it("refuses a longest take outside the server's range", () => {
    expect(secondsProblem('60')).toBeUndefined()
    expect(secondsProblem('4')).toBe('Enter a whole number of seconds from 5 to 300.')
    expect(secondsProblem('12.5')).toBe('Enter a whole number of seconds from 5 to 300.')
    expect(secondsProblem('')).toBe('Enter a whole number of seconds from 5 to 300.')
  })
})

describe('the System finding', () => {
  it("reads the recordings folder's disk and names the threshold crossed", () => {
    expect(recordingsDisk(systemStatus)).toEqual({ size: 512e9, used: 512e9 - 210.4e9, free: 210.4e9 })
    expect(
      recordingsDisk({
        ...systemStatus,
        folders: [{ name: 'recordings', path: '/x', exists: false, total_bytes: null, free_bytes: null }],
      }),
    ).toBeUndefined()
    expect(ofSize(301.6e9, 512e9)).toBe(`${format.bytes(301.6e9, 'GB')} of ${format.bytes(512e9, 'GB')}`)
    expect(describeDisk(systemStatus)).toBe(`Everything is running. The recordings disk is 59% full, with ${format.bytes(210.4e9)} free.`)
    expect(describeDisk(systemNearlyFull)).toMatch(/^The recordings disk is 96% full, .* Free space before takes stop saving\.$/)
    const filling = { ...systemStatus, folders: [{ name: 'recordings', path: '/x', exists: true, total_bytes: 100, free_bytes: 15 }] }
    expect(describeDisk(systemStatus, false)).toBe(
      `The server is not answering. When last read, the recordings disk was 59% full, with ${format.bytes(210.4e9)} free.`,
    )
    expect(describeDisk(filling)).toBe(`The recordings disk is 85% full, with ${format.bytes(15)} free. Nothing needs doing yet.`)
    const unread = { ...systemStatus, folders: [] }
    expect(describeDisk(unread)).toBe('Everything is running. The recordings disk could not be read.')
    expect(describeDisk(unread, false)).toBe('The server is not answering.')
  })
})

describe('the mock server', () => {
  it("pages takes after a cursor with the server's own next, as studio.takes_page does", () => {
    const list = makeTakes(5) // ids 5..1, newest first
    const url = (q: string) => `http://x/api/takes/page?${q}`
    expect(takePage(url('limit=2'), list)).toEqual({ items: list.slice(0, 2), next: '4', total: null })
    expect(takePage(url('after=2&limit=2'), list)).toEqual({ items: list.slice(4), next: null, total: null })
    expect(takePage(url(''), list).items).toHaveLength(5)
  })

  it('works out the queue and progress from what it holds, as studio.studio does', () => {
    const s = studioOf()
    expect(s.consented).toBe(true)
    expect(s.queue.map(p => p.id)).toEqual(initialPrompts.slice(3).map(p => p.id)) // the first three have takes
    expect(s.progress).toMatchObject({ prompts: 8, recorded: 3, skipped: 0, takes: 3 })
    const skipped = studioOf({
      ...mock,
      prompts: mock.prompts.map((p, i) => ({ ...p, skipped: i === 3 })),
      settings: { ...mock.settings, consented_on: '' },
    })
    expect([skipped.consented, skipped.queue[0].id, skipped.progress.skipped]).toEqual([false, 5, 1])
  })

  it('answers a take with a real, tiny WAV', () => {
    const view = new DataView(silentWav())
    expect([view.getUint32(24, true), view.getUint32(40, true)]).toEqual([16_000, 3200])
  })
})

describe('index.html', () => {
  it('inlines the colour-scheme script ThemeProvider expects, so a dark page does not flash light', () => {
    const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8')
    expect(html).toContain(`<script>${colorSchemeScript()}</script>`)
  })
})

describe('the coverage finding', () => {
  const sounds = coverageSample.groups[0]
  const withSounds = (counts: number[]) => ({
    ...coverageSample,
    groups: coverageSample.groups.map(g =>
      g.key === 'phoneme'
        ? {
            ...g,
            covered: g.units.length - counts.filter(n => n === 0).length,
            units: g.units.map((u, i) => ({ ...u, count: counts[i] ?? 5 })),
          }
        : g,
    ),
  })

  it('names the sounds never said, three at most', () => {
    expect(describeCoverage(withSounds([0, 0, 4]))).toBe(
      `41 of 43 sounds said; not yet ${unitName(sounds, sounds.units[0])}, ${unitName(sounds, sounds.units[1])}. 5 of 23 styles said.`,
    )
    expect(describeCoverage(withSounds([0, 0, 0, 0]))).toMatch(/^39 of 43 sounds said; not yet .+, .+, .+ and more\./)
  })

  it('writes a phoneme with a word that has it, and a stress pattern as beats, secondary stress apart', () => {
    expect(unitName(sounds, { value: 'ʒ', count: 0, example: 'measure' })).toBe('/ʒ/ as in “measure”')
    const stress = coverageSample.groups[2]
    expect(unitName(stress, { value: '010', count: 1, example: null })).toBe('da DA da')
    expect(unitName(stress, { value: '102', count: 1, example: null })).toBe('DA da Da')
    expect(unitName(coverageSample.groups[5], { value: 'happy', count: 0, example: null })).toBe('happy')
  })
})

describe('a batch of written prompts', () => {
  it('names the writer, or says "the writer" when the service did not', () => {
    const w = { offered: 3, added: 1, writer: null, cost_usd: null, waiting: 1 }
    expect(describeWritten(w)).toBe(
      `The writer wrote 3; ${format.count(1, 'new prompt')} kept. ${format.count(1, 'written prompt')} now wait.`,
    )
  })
})

describe('hands-free', () => {
  const s = (phase: Said['phase'], take?: Partial<Said['take']>) => ({ phase, take }) as Said

  it('says nothing before a take, then counts each state', () => {
    expect(describeVisit([])).toBeUndefined()
    expect(describeVisit([s('saving'), s('failed')])).toBe(
      `${format.count(2, 'take')} said this visit: 0 kept, 1 being checked, 1 not kept.`,
    )
  })

  it("words each take: checking, not kept, back in the queue, or the studio's own word", () => {
    expect(saidWord(s('saving')).word).toBe('Checking…')
    expect(saidWord(s('failed')).word).toBe('Not kept')
    expect(saidWord(s('saved', { verdict: 'retry', accepted: false })).word).toBe('Back in the queue')
    expect(saidWord(s('saved', { verdict: 'retry', accepted: true })).word).toBe('Kept anyway')
    expect(saidWord(s('saved', { verdict: 'good', accepted: false })).word).toBe('Good take')
  })

  it('says why a write failed, with words for something that is not an error', () => {
    expect(failed(new Error('Gone.'))).toBe('Gone.')
    expect(failed(42)).toBe('It did not go through.')
  })
})
