import { expectOneFilledButton } from 'strata-react/testing'
import { describe, expect, it } from 'vitest'
import { coverageError, coverageNoEspeak, coverageNothing, writeDown, writeFails } from '../../src/mocks/handlers'
import { openApp, screen, within } from '../utils/render'
import { server } from '../utils/server'

describe('Coverage', () => {
  it('answers with the sounds and styles said, and lists each group least said first', async () => {
    openApp('/coverage')
    expect(await screen.findByText(/^Every sound has been said; the least is \/ɜː\/ as in “nurse”, 2\stimes\./)).toBeInTheDocument()
    expect(screen.getByText(/5 of 23 styles said\.$/)).toBeInTheDocument()
    expect(screen.getByText(/^Over 25\srecorded prompts$/)).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Phonemes said at least once' })).toHaveAttribute('aria-valuenow', '43')
    const styles = screen.getByRole('region', { name: 'Styles' })
    expect(within(styles).getByRole('rowheader', { name: 'happy' })).toBeInTheDocument()
    expect(within(styles).getAllByText('Not yet')).toHaveLength(10)
    const stress = screen.getByRole('region', { name: 'Stress patterns' })
    expect(within(stress).getByText(/12\sdifferent ones said so far/)).toBeInTheDocument()
    expect(within(stress).getAllByRole('rowheader')[0]).toHaveTextContent(/^(da|DA)( (da|DA))+$/)
    expect(screen.getByText(/^12\swritten prompts wait after the starter set/)).toBeInTheDocument()
    expectOneFilledButton()
  })

  it('writes more prompts and says what came of it', async () => {
    const { user } = openApp('/coverage')
    await user.click(await screen.findByRole('button', { name: 'Write 40 more prompts' }))
    expect(
      await screen.findByText(/^claude-sonnet-5-5-api wrote 40; 37\snew prompts kept\. 49\swritten prompts now wait\.$/),
    ).toBeInTheDocument()
    expect(await screen.findByText(/^49\swritten prompts wait after the starter set/)).toBeInTheDocument()
    expectOneFilledButton()
  })

  it('says why no prompts were written when strata-models is not running', async () => {
    server.use(writeDown)
    const { user } = openApp('/coverage')
    await user.click(await screen.findByRole('button', { name: 'Write 40 more prompts' }))
    expect(
      await screen.findByText(/^strata-models is not running, so no prompts can be written.* No prompts were added\.$/),
    ).toBeInTheDocument()
  })

  it('falls back to the status when the server gives no reason', async () => {
    server.use(writeFails)
    const { user } = openApp('/coverage')
    await user.click(await screen.findByRole('button', { name: 'Write 40 more prompts' }))
    expect(await screen.findByText(/^The server could not answer \(503\)\. No prompts were added\.$/)).toBeInTheDocument()
  })

  it('says everything is still to say before anything is recorded', async () => {
    server.use(coverageNothing)
    openApp('/coverage')
    expect(await screen.findByText('Nothing is recorded yet, so every sound and style is still to say.')).toBeInTheDocument()
    expect(screen.getByText(/^No written prompts wait/)).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Phoneme pairs' })).queryByRole('table')).toBeNull()
  })

  it('says when sounds cannot be counted, and names the ones never said', async () => {
    server.use(coverageNoEspeak)
    openApp('/coverage')
    expect(await screen.findByText(/^Sounds are not counted: espeak-ng is not installed on the server\./)).toBeInTheDocument()
  })

  it('says the server could not answer', async () => {
    server.use(coverageError)
    openApp('/coverage')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not answer (503)')
  })
})
