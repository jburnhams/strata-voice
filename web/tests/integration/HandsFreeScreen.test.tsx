import { delay, HttpResponse, http } from 'msw'
import { expectOneFilledButton, fakeMicrophone, speechScript } from 'strata-react/testing'
import { describe, expect, it } from 'vitest'
import { initialPrompts } from '../../src/mocks/fixtures'
import { acceptFails, keepFails, keepMisread, queueError, studioNotConsented } from '../../src/mocks/handlers'
import { openApp, screen, waitFor, within } from '../utils/render'
import { mock, server } from '../utils/server'

// The hands-free studio over the fake microphone reading a script (speech, then quiet, for each take), twenty
// times faster than real time. The first three prompts have takes in the healthy mock, so the queue starts at the
// fourth.
const [, , , fourth, fifth, sixth] = initialPrompts
const reader = (takes: number) => fakeMicrophone({ script: speechScript(takes, { speak: 1, gap: 1.2 }), speed: 20 })
const said = () => within(screen.getByRole('list', { name: 'Takes said this visit, newest first' }))
/** The said list, once the first take has been cut (the fake reads its first prompt in about a tenth of a second). */
const saidSoon = async () => within(await screen.findByRole('list', { name: 'Takes said this visit, newest first' }, { timeout: 3000 }))
const nextUp = () => screen.getByRole('grid', { name: 'Prompts still to read, in order' })

describe('Hands-free', () => {
  it('waits for a press, then reads prompt after prompt and keeps each take in the order said', async () => {
    const { user } = openApp('/hands-free', { microphone: reader(2) })
    expect(await screen.findByRole('heading', { level: 2, name: fourth.text })).toBeInTheDocument()
    expect(screen.getByText(/^Next to say · Read aloud$/)).toBeInTheDocument()
    expectOneFilledButton()
    await user.click(screen.getByRole('button', { name: 'Start listening' }))
    expect(await screen.findByRole('meter', { name: 'Input level' })).toBeInTheDocument()
    expectOneFilledButton()

    expect(await screen.findByRole('heading', { level: 2, name: sixth.text }, { timeout: 3000 })).toBeInTheDocument()
    await waitFor(() => expect(said().getAllByText('Good take')).toHaveLength(2))
    expect(
      said()
        .getAllByRole('listitem')
        .map(li => li.textContent?.slice(0, 20)),
    ).toEqual([fifth.text, fourth.text].map(t => t.slice(0, 20)))
    expect(mock.takes.slice(0, 2).map(t => t.prompt_id)).toEqual([fifth.id, fourth.id])
    expect(screen.getByText(/^2\stakes said this visit: 2 kept\.$/)).toBeInTheDocument()
    expect(within(nextUp()).queryByText(fourth.text)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Pause' }))
    expect(screen.getByRole('meter', { name: 'Input level' })).toHaveAccessibleDescription(/^Paused/)
    await user.click(screen.getByRole('button', { name: 'Stop listening' }))
    expect(screen.getByRole('button', { name: 'Start listening' })).toBeInTheDocument()
  })

  it('puts a misread prompt back in the queue after the one being read, and keeps it anyway when asked', async () => {
    server.use(keepMisread)
    const { user } = openApp('/hands-free', { microphone: reader(1) })
    await user.click(await screen.findByRole('button', { name: 'Start listening' }))
    expect(await (await saidSoon()).findByText('Back in the queue', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(said().getByText(/^Some words were not the prompt's/)).toBeInTheDocument()
    // The prompt being read does not jump back; the misread one is next.
    expect(screen.getByRole('heading', { level: 2, name: fifth.text })).toBeInTheDocument()
    await waitFor(() => expect(within(nextUp()).getAllByRole('row')[0]).toHaveTextContent(fourth.text))
    expect(screen.getByText(/1 take said this visit: 0 kept, 1 back in the queue\./)).toBeInTheDocument()

    await user.click(said().getByRole('button', { name: `Keep it anyway ${fourth.text}` }))
    expect(await said().findByText('Kept anyway')).toBeInTheDocument()
    await waitFor(() => expect(within(nextUp()).queryByText(fourth.text)).not.toBeInTheDocument())
  })

  it('says when keeping it anyway failed', async () => {
    server.use(keepMisread, acceptFails)
    const { user } = openApp('/hands-free', { microphone: reader(1) })
    await user.click(await screen.findByRole('button', { name: 'Start listening' }))
    await user.click(await (await saidSoon()).findByRole('button', { name: `Keep it anyway ${fourth.text}` }, { timeout: 3000 }))
    expect(await said().findByText('The server could not answer (503). The recording is still here.')).toBeInTheDocument()
  })

  it('holds a take the server did not keep, and keeps it on Try again', async () => {
    server.use(keepFails)
    const { user } = openApp('/hands-free', { microphone: reader(1) })
    await user.click(await screen.findByRole('button', { name: 'Start listening' }))
    expect(await (await saidSoon()).findByText('Not kept', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText(/1 take said this visit: 0 kept, 1 not kept\./)).toBeInTheDocument()
    // Not held: the prompt is offered again, after the one being read.
    expect(screen.getByRole('heading', { level: 2, name: fifth.text })).toBeInTheDocument()
    await waitFor(() => expect(within(nextUp()).getAllByRole('row')[0]).toHaveTextContent(fourth.text))
    server.resetHandlers()
    await user.click(said().getByRole('button', { name: `Try again ${fourth.text}` }))
    expect(await said().findByText('Good take')).toBeInTheDocument()
    expect(mock.takes[0].prompt_id).toBe(fourth.id)
  })

  it('is worked from the keyboard: S skips with Undo in reach, L listens, P pauses', async () => {
    const { user } = openApp('/hands-free', { microphone: fakeMicrophone({ silent: true }) })
    await screen.findByRole('heading', { level: 2, name: fourth.text })
    await user.keyboard('s')
    expect(await screen.findByRole('heading', { level: 2, name: fifth.text })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByRole('heading', { level: 2, name: fourth.text })).toBeInTheDocument()
    await user.keyboard('l')
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
    await user.keyboard('p')
    expect(await screen.findByRole('button', { name: 'Resume' })).toBeInTheDocument()
    await user.keyboard('l')
    expect(await screen.findByRole('button', { name: 'Start listening' })).toBeInTheDocument()
  })

  it('skips with the button, and commits the skip when the window closes', async () => {
    const { user } = openApp('/hands-free')
    await user.click(await screen.findByRole('button', { name: 'Skip' }))
    expect(await screen.findByRole('heading', { level: 2, name: fifth.text })).toBeInTheDocument()
    expect(screen.getByText(`Skipped “${fourth.text}”.`)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Skip' })) // a second skip commits the first
    await waitFor(() => expect(mock.prompts[3].skipped).toBe(true))
    await user.click(screen.getByRole('button', { name: 'Undo' }))
  })

  it('reads any prompt in the list first when asked', async () => {
    const { user } = openApp('/hands-free')
    await screen.findByRole('heading', { level: 2, name: fourth.text })
    await user.click(within(nextUp()).getByRole('button', { name: `Read now ${sixth.text}` }))
    expect(screen.getByRole('heading', { level: 2, name: sixth.text })).toBeInTheDocument()
  })

  it('keeps the prompt that replaced a skipped one when an earlier take comes back to be said again', async () => {
    // The take for the fourth is checked slowly and comes back misread, after the fifth has been skipped.
    server.use(
      http.post('*/api/prompts/:id/takes', async () => {
        await delay(400)
        return undefined
      }),
      keepMisread,
    )
    const { user } = openApp('/hands-free', { microphone: reader(1) })
    await user.click(await screen.findByRole('button', { name: 'Start listening' }))
    expect(await screen.findByRole('heading', { level: 2, name: fifth.text }, { timeout: 3000 })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    expect(await screen.findByRole('heading', { level: 2, name: sixth.text })).toBeInTheDocument()
    expect(await said().findByText('Back in the queue', {}, { timeout: 3000 })).toBeInTheDocument()
    await waitFor(() => expect(within(nextUp()).getAllByRole('row')[0]).toHaveTextContent(fourth.text))
    expect(screen.getByRole('heading', { level: 2, name: sixth.text })).toBeInTheDocument()
    // Undo still brings the skipped prompt back to the front.
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByRole('heading', { level: 2, name: fifth.text })).toBeInTheDocument()
  })

  it('does not change the prompt while a take is being said', async () => {
    const { user } = openApp('/hands-free', {
      microphone: fakeMicrophone({ script: speechScript(1, { speak: 30, gap: 1 }), speed: 1 }),
    })
    await user.click(await screen.findByRole('button', { name: 'Start listening' }))
    await waitFor(() => expect(screen.getByRole('meter', { name: 'Input level' })).toHaveAccessibleDescription(/^Hearing you/), {
      timeout: 3000,
    })
    expect(within(nextUp()).getByRole('button', { name: `Read now ${sixth.text}` })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Skip' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Stop listening' }))
  })

  it('says why the microphone did not open', async () => {
    const { user } = openApp('/hands-free', {
      microphone: fakeMicrophone({ refuse: 'No microphone was found. Plug one in, then try again.' }),
    })
    await user.click(await screen.findByRole('button', { name: 'Start listening' }))
    expect(await screen.findByText('No microphone was found. Plug one in, then try again.')).toBeInTheDocument()
  })

  it('asks for consent first, and says when the queue could not be read', async () => {
    server.use(studioNotConsented)
    const { unmount } = openApp('/hands-free')
    expect(await screen.findByRole('button', { name: 'I agree to be recorded' })).toBeInTheDocument()
    unmount()
    server.resetHandlers()
    server.use(queueError)
    openApp('/hands-free')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not answer (503)')
  })

  it('waits for the last take to be checked before its done moment, and says when a take was cut', async () => {
    mock.settings.max_take_seconds = 1
    // One prompt left until a take is kept; the take is kept slowly, so the wait shows.
    server.use(
      http.get('*/api/queue', () =>
        HttpResponse.json({ items: mock.takes.some(t => t.prompt_id === fourth.id) ? [] : [fourth], next: null, total: null }),
      ),
      http.post('*/api/prompts/:id/takes', async () => {
        await delay(300)
        return undefined
      }),
    )
    const { user } = openApp('/hands-free', { microphone: fakeMicrophone({ script: speechScript(1, { speak: 2, gap: 1 }), speed: 20 }) })
    await user.click(await screen.findByRole('button', { name: 'Start listening' }))
    expect(await screen.findByText('Waiting for the last takes to be checked…', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(said().getByText('Cut at the longest take: say it again if it ran on.')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Read every prompt' })).toBeInTheDocument()
  })

  it('has its done moment when the last prompt is skipped', async () => {
    server.use(http.get('*/api/queue', () => HttpResponse.json({ items: [fourth], next: null, total: null })))
    const { user } = openApp('/hands-free')
    await user.click(await screen.findByRole('button', { name: 'Skip' }))
    expect(await screen.findByRole('heading', { name: 'Read every prompt' })).toBeInTheDocument()
  })

  it('has its done moment once nothing is left to read', async () => {
    server.use(http.get('*/api/queue', () => HttpResponse.json({ items: [], next: null, total: null })))
    openApp('/hands-free')
    expect(await screen.findByRole('heading', { name: 'Read every prompt' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start listening' })).not.toBeInTheDocument()
  })
})
