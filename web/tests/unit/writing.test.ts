import { describe, expect, it } from 'vitest'
import { flagName, mediumName, pieces, removedName, splitName } from '../../src/api'
import { task } from '../../src/mocks/fixtures'
import { writingPage } from '../../src/mocks/handlers'
import { manyWriting, writingNever, writingRows, writingSummary } from '../../src/mocks/writing-sample'
import { describeBuild, describeChecked, describeWriting } from '../../src/screens/WritingScreen'

const email = writingRows.find(w => w.id === 4)!

describe('pieces', () => {
  it('keeps a piece nothing was taken from whole', () => {
    expect(pieces(writingRows[0])).toEqual([{ text: writingRows[0].text, removed: null }])
  })
  it('puts the original back together, with each span taken out marked', () => {
    const got = pieces(email)
    expect(got.map(p => p.text).join('')).toBe(email.original)
    expect(got.map(p => p.removed)).toEqual([null, 'quote', null, 'signature'])
  })
  it('starts and ends with a span when cleaning took the first and last of it', () => {
    const w = { ...email, original: 'abcdef', removed: [{ kind: 'quote', start: 0, end: 2 }] }
    expect(pieces(w)).toEqual([
      { text: 'ab', removed: 'quote' },
      { text: 'cdef', removed: null },
    ])
  })
})

describe('words', () => {
  it('names mediums, splits, flags and what was taken out, and passes on a name it does not know', () => {
    expect(mediumName('chat-group')).toBe('Group chats')
    expect(mediumName('fax')).toBe('fax')
    expect(splitName('sealed')).toBe('Sealed')
    expect(splitName('later')).toBe('later')
    expect(flagName('leak')).toBe('Still holds the mail it answers')
    expect(flagName('odd')).toBe('odd')
    expect(removedName('client')).toBe('a mail app’s footer')
    expect(removedName('ink')).toBe('ink')
  })

  it('says what a build is doing or why it stopped', () => {
    expect(describeBuild(task(1, { state: 'failed', error: 'no view' }))).toBe('no view')
    expect(describeBuild(task(1, { state: 'failed', error: null }))).toBe('The build stopped.')
    expect(describeBuild(task(1, { state: 'queued', progress: null }))).toBe('Waiting to start.')
    expect(describeBuild(task(1, { state: 'running' }))).toBe('2 of 3 sentences kept')
  })

  it('says how far a sample is checked', () => {
    const m = writingSummary.mediums[0]
    expect(describeChecked({ ...m, sample: 0 })).toBe('No sample')
    expect(describeChecked({ ...m, checked: 0 })).toBe('50 to check')
    expect(describeChecked(m)).toBe('12 of 50 checked, 10 right')
  })

  it('says why nothing is read yet', () => {
    expect(describeWriting(writingNever)).toMatch(/^Nothing is read yet: build the corpus/)
    expect(describeWriting({ ...writingNever, job: task(1, { state: 'running' }) })).toBe(
      'Nothing is read yet: the first build is running.',
    )
    expect(describeWriting({ ...writingNever, job: task(1, { state: 'queued' }) })).toBe('Nothing is read yet: the first build is running.')
    expect(describeWriting({ ...writingNever, job: task(1, { state: 'failed' }) })).toBe('Nothing is read yet: the last build failed.')
  })

  it('leaves out what is sealed before a split is frozen', () => {
    expect(describeWriting({ ...writingSummary, cutoff: null })).toMatch(/set aside\.$/)
  })
})

describe('the mock server', () => {
  it('pages the writing by its cursor', () => {
    const first = writingPage('http://x/api/writing/page?limit=30', manyWriting)
    expect(first.items).toHaveLength(30)
    const next = writingPage(`http://x/api/writing/page?limit=30&after=${first.next}`, manyWriting)
    expect(next.items[0].id).toBe(Number(first.next) - 1)
    expect(writingPage('http://x/api/writing/page', manyWriting).items).toHaveLength(20)
  })
})
