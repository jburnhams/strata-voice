import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { initialTakes, makeTakes } from '../../src/mocks/fixtures'
import { removeFails, takesEmpty, takesError, takesMany } from '../../src/mocks/handlers'
import { openApp, screen, waitFor, within } from '../utils/render'
import { mock, server } from '../utils/server'

// InfiniteList is a grid of rows (React Aria); items carry data-index, the next-page row does not.
const list = () => screen.getByRole('grid', { name: 'Takes, newest first' })
const items = () => [...list().querySelectorAll<HTMLElement>('[data-index]')]

describe('Takes', () => {
  it('lists every take newest first, each with its length', async () => {
    openApp('/takes')
    expect(await screen.findByText('That is every take.')).toBeInTheDocument()
    expect(items()).toHaveLength(3)
    expect(items()[0]).toHaveTextContent(initialTakes[0].prompt_text)
    expect(items()[0]).toHaveTextContent('Read aloud')
    expect(items()[0]).toHaveTextContent('Good take')
  })

  it('says how each take was judged, and plays one not yet checked whole', async () => {
    mock.takes = makeTakes(11) // take 7 missed words, take 11 was not checked
    const { user } = openApp('/takes')
    expect(await screen.findByText('That is every take.')).toBeInTheDocument()
    const words = items().map(row => within(row).getByText(/^(Good take|Record again|Not checked)$/).textContent)
    expect(words.filter(w => w === 'Record again')).toHaveLength(1)
    expect(words[0]).toBe('Not checked')
    await user.click(within(items()[0]).getByRole('button', { name: `Listen to ${mock.takes[0].prompt_text}` }))
    expect(screen.getByRole('group', { name: `Take of “${mock.takes[0].prompt_text}”` })).toBeInTheDocument()
  })

  it('plays the take chosen in one player above the list', async () => {
    const { user } = openApp('/takes')
    await user.click(await screen.findByRole('button', { name: `Listen to ${initialTakes[1].prompt_text}` }))
    expect(screen.getByRole('heading', { name: 'Listening' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: `Take of “${initialTakes[1].prompt_text}”` })).toBeInTheDocument()
    // Removing the take being played stops the player.
    await user.click(screen.getByRole('button', { name: `Remove ${initialTakes[1].prompt_text}` }))
    expect(screen.queryByRole('heading', { name: 'Listening' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
  })

  it('removes a take with Undo in reach, and deletes it when the window closes', async () => {
    const { user } = openApp('/takes')
    const first = initialTakes[0]
    await user.click(await screen.findByRole('button', { name: `Remove ${first.prompt_text}` }))
    expect(screen.getByText(`Removed the take of “${first.prompt_text}”.`)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: `Remove ${first.prompt_text}` })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByRole('button', { name: `Remove ${first.prompt_text}` })).toBeInTheDocument()
    expect(mock.takes).toHaveLength(3)

    await user.click(screen.getByRole('button', { name: `Remove ${first.prompt_text}` }))
    await user.click(screen.getByRole('button', { name: `Remove ${initialTakes[1].prompt_text}` })) // commits the first
    await waitFor(() => expect(mock.takes.map(t => t.id)).not.toContain(first.id))
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(mock.takes.map(t => t.id)).toContain(initialTakes[1].id)
  })

  it('counts a take already gone as removed, and brings one back when removing fails', async () => {
    const { user } = openApp('/takes')
    const [first, second] = initialTakes
    const remove = await screen.findByRole('button', { name: `Remove ${first.prompt_text}` })
    mock.takes = mock.takes.filter(t => t.id !== first.id) // removed elsewhere meanwhile: a 404
    await user.click(remove)
    await user.click(screen.getByRole('button', { name: `Remove ${second.prompt_text}` })) // commits the first: a 404, done
    await waitFor(() => expect(screen.queryByText(/removing it did not go through/)).toBeNull())
    expect(screen.queryByRole('button', { name: `Remove ${first.prompt_text}` })).toBeNull()
    server.use(removeFails)
    await user.click(screen.getByRole('button', { name: `Remove ${initialTakes[2].prompt_text}` })) // commits the second: 503
    expect(await screen.findByRole('button', { name: `Remove ${second.prompt_text}` })).toBeInTheDocument()
    expect(mock.takes.map(t => t.id)).toContain(second.id)
    server.resetHandlers()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
  })

  it('brings a take back when the server cannot be reached at all', async () => {
    server.use(http.delete('*/api/takes/:id', () => HttpResponse.error()))
    const { user } = openApp('/takes')
    const [first, second] = initialTakes
    await user.click(await screen.findByRole('button', { name: `Remove ${first.prompt_text}` }))
    await user.click(screen.getByRole('button', { name: `Remove ${second.prompt_text}` })) // commits the first: no answer
    expect(await screen.findByRole('button', { name: `Remove ${first.prompt_text}` })).toBeInTheDocument()
    expect(mock.takes.map(t => t.id)).toContain(first.id)
    server.resetHandlers()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
  })

  it('reads a long list a page at a time', async () => {
    server.use(takesMany)
    const { user } = openApp('/takes')
    await user.click(await screen.findByRole('button', { name: 'Show older takes' }))
    await waitFor(() => expect(items()).toHaveLength(40))
  })

  it('points to the studio when there are no takes', async () => {
    server.use(takesEmpty)
    openApp('/takes')
    expect(await screen.findByText('No takes yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to the studio' })).toHaveAttribute('href', '/')
  })

  it('says the server could not answer', async () => {
    server.use(takesError)
    openApp('/takes')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not answer (503)')
    expect(within(screen.getByRole('alert')).getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
