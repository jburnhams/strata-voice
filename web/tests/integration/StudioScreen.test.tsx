import { expectOneFilledButton, fakeMicrophone } from 'strata-react/testing'
import { describe, expect, it } from 'vitest'
import { initialPrompts } from '../../src/mocks/fixtures'
import { consentFails, keepFails, skipFails, studioDone, studioError, studioNotConsented } from '../../src/mocks/handlers'
import { openApp, screen, waitFor, within } from '../utils/render'
import { mock, server } from '../utils/server'

// The first three prompts have takes in the healthy mock, so the queue starts at the fourth.
const fourth = initialPrompts[3]
const fifth = initialPrompts[4]

describe('Studio', () => {
  it('shows the next prompt with how far the speaker has got', async () => {
    openApp('/')
    expect(await screen.findByRole('heading', { level: 2, name: fourth.text })).toBeInTheDocument()
    expect(screen.getByText('Read aloud')).toBeInTheDocument()
    expect(screen.getByText(/^3 of 8\sprompts recorded\. 0:\d\d of speech kept\.$/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Record' })).toBeInTheDocument()
    expectOneFilledButton()
  })

  it('records a take, keeps it, plays it back, and moves on', async () => {
    const { user } = openApp('/')
    await user.click(await screen.findByRole('button', { name: 'Record' }))
    const meter = await screen.findByRole('meter', { name: 'Input level' })
    await waitFor(() => expect(meter).toHaveAttribute('aria-valuetext', '-10\u00a0dBFS')) // the fake's tone, 0.3 of full scale
    expectOneFilledButton()
    await user.click(screen.getByRole('button', { name: 'Stop' }))

    expect(await screen.findByRole('button', { name: 'Next prompt' })).toBeInTheDocument()
    expect(screen.getByText('Good level')).toBeInTheDocument()
    expect(screen.getByText(/^Kept 0:\d\d, peak -10\sdBFS\./)).toBeInTheDocument()
    expect(screen.getByRole('group', { name: `Your take of “${fourth.text}”` })).toBeInTheDocument()
    const kept = mock.takes[0]
    expect([kept.prompt_id, kept.sample_rate, kept.device]).toEqual([fourth.id, 16_000, 'Fake USB microphone'])
    expect(kept.seconds).toBeGreaterThan(0)
    expectOneFilledButton()

    await user.click(screen.getByRole('button', { name: 'Record again' }))
    await user.click(await screen.findByRole('button', { name: 'Stop' }))
    await user.click(await screen.findByRole('button', { name: 'Next prompt' }))
    expect(mock.takes.filter(t => t.prompt_id === fourth.id)).toHaveLength(2)
    expect(await screen.findByRole('heading', { level: 2, name: fifth.text })).toBeInTheDocument()
    expect(screen.getByText('Say it: dry, sarcastic')).toBeInTheDocument()
  })

  it('is worked from the keyboard: R records, stops and records again, N moves on, S skips', async () => {
    const { user } = openApp('/')
    await screen.findByRole('heading', { level: 2, name: fourth.text })
    expect(screen.getByLabelText('Studio keys')).toHaveTextContent('Record')
    await user.keyboard('r')
    await screen.findByRole('meter', { name: 'Input level' })
    await user.keyboard('r')
    await screen.findByRole('button', { name: 'Record again' })
    await user.keyboard('r')
    await screen.findByRole('button', { name: 'Stop' })
    await user.keyboard('r')
    await screen.findByRole('button', { name: 'Next prompt' })
    expect(mock.takes.filter(t => t.prompt_id === fourth.id)).toHaveLength(2) // a retry is another take
    await user.keyboard('n')
    await screen.findByRole('heading', { level: 2, name: fifth.text })
    await user.keyboard('s')
    expect(await screen.findByRole('heading', { level: 2, name: initialPrompts[5].text })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Undo' })) // nothing left to commit after the test
  })

  it('skips a prompt with Undo in reach, and commits the skip when the window closes', async () => {
    const { user } = openApp('/')
    await user.click(await screen.findByRole('button', { name: 'Skip' }))
    expect(await screen.findByRole('heading', { level: 2, name: fifth.text })).toBeInTheDocument()
    expect(screen.getByText(`Skipped “${fourth.text}”.`)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByRole('heading', { level: 2, name: fourth.text })).toBeInTheDocument()
    expect(mock.prompts[3].skipped).toBe(false)

    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(await screen.findByRole('button', { name: 'Skip' })) // a second skip commits the first
    await waitFor(() => expect(mock.prompts[3].skipped).toBe(true))
    expect(mock.prompts[4].skipped).toBe(false) // still inside its window
    await user.click(screen.getByRole('button', { name: 'Undo' }))
  })

  it('brings a skipped prompt back when the skip did not go through', async () => {
    server.use(skipFails)
    const { user } = openApp('/')
    await user.click(await screen.findByRole('button', { name: 'Skip' }))
    await user.click(await screen.findByRole('button', { name: 'Skip' })) // commits the first, which fails
    // The failed skip brings its prompt back to the front of the queue, ahead of the one still pending.
    expect(await screen.findByRole('heading', { level: 2, name: fourth.text })).toBeInTheDocument()
    expect(mock.prompts[3].skipped).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Undo' }))
  })

  it('holds a take the server did not keep, and keeps it on Try again', async () => {
    server.use(keepFails)
    const { user } = openApp('/')
    await user.click(await screen.findByRole('button', { name: 'Record' }))
    await screen.findByRole('meter', { name: 'Input level' })
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The take was not kept')
    expect(alert).toHaveTextContent('The server could not answer (503). The recording is still here')
    server.resetHandlers()
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('button', { name: 'Next prompt' })).toBeInTheDocument()
    expect(mock.takes[0].prompt_id).toBe(fourth.id)
  })

  it('says why the microphone did not open, in words a person can act on', async () => {
    const refuse = 'The browser was not allowed to use the microphone. Allow it from the address bar, then try again.'
    const { user } = openApp('/', { microphone: fakeMicrophone({ refuse }) })
    await user.click(await screen.findByRole('button', { name: 'Record' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(refuse)
    expect(screen.getByRole('button', { name: 'Record' })).toBeInTheDocument()
  })

  it('says what failed when the microphone breaks in a way it does not explain', async () => {
    const { user } = openApp('/', { microphone: fakeMicrophone({ crash: true }) })
    await user.click(await screen.findByRole('button', { name: 'Record' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The microphone could not be opened (TypeError: audio graph exploded).')
  })

  it('stops on its own at the longest take, and judges a quiet one', async () => {
    mock.settings.max_take_seconds = 1
    const { user } = openApp('/', { microphone: fakeMicrophone({ amplitude: 0.01, device: null }) })
    await user.click(await screen.findByRole('button', { name: 'Record' }))
    expect(await screen.findByRole('button', { name: 'Next prompt' })).toBeInTheDocument()
    expect(screen.getByText('Too quiet')).toBeInTheDocument()
    expect(mock.takes[0].seconds).toBe(1)
    expect(mock.takes[0].device).toBeNull()
  })

  it('asks for consent before anything is recorded', async () => {
    server.use(studioNotConsented)
    mock.settings.consented_on = ''
    const { user } = openApp('/')
    expect(await screen.findByRole('heading', { name: 'Before you record' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Record' })).toBeNull()
    server.resetHandlers()
    await user.click(screen.getByRole('button', { name: 'I agree to be recorded' }))
    expect(await screen.findByRole('button', { name: 'Record' })).toBeInTheDocument()
    expect(mock.settings.consented_on).toMatch(/^\d{4}-\d\d-\d\d$/)
  })

  it('says when consent could not be saved', async () => {
    server.use(studioNotConsented, consentFails)
    const { user } = openApp('/')
    await user.click(await screen.findByRole('button', { name: 'I agree to be recorded' }))
    expect(await screen.findByText('The server could not answer (503). Nothing was changed.')).toBeInTheDocument()
  })

  it('marks the end of the queue and points to the takes', async () => {
    server.use(studioDone)
    openApp('/')
    expect(await screen.findByRole('heading', { name: 'Recorded every prompt' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Listen to the takes' })).toHaveAttribute('href', '/takes')
  })

  it('says the server could not answer', async () => {
    server.use(studioError)
    openApp('/')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not answer (503)')
  })
})
