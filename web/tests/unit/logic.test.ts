import { readFileSync } from 'node:fs'
import { colorSchemeScript, format } from 'strata-react'
import { describe, expect, it } from 'vitest'
import { kindName, today } from '../../src/api'
import { initialPrompts, makeTakes, silentWav, systemNearlyFull, systemStatus } from '../../src/mocks/fixtures'
import { mock, studioOf, takePage } from '../../src/mocks/handlers'
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
