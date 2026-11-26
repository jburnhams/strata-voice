import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { failedUpload, kitchenSentences, kitchenUpload, talkUpload } from '../../src/mocks/fixtures'
import { uploadRefused, uploadsEmpty, uploadsError, uploadsEveryState } from '../../src/mocks/handlers'
import { openApp, screen, waitFor, within } from '../utils/render'
import { mock, server } from '../utils/server'

const list = () => screen.getByRole('grid', { name: 'Recordings brought in, newest first' })
const items = () => [...list().querySelectorAll<HTMLElement>('[data-index]')]
const file = (name: string, type = 'audio/mp4') => new File([new Uint8Array(2048)], name, { type })

describe('Upload', () => {
  it('says what each recording gave the voice model', async () => {
    openApp('/upload')
    expect(await screen.findByText('That is every recording brought in.')).toBeInTheDocument()
    const [row] = items()
    expect(row).toHaveTextContent(kitchenUpload.name)
    expect(row).toHaveTextContent('Done')
    expect(row).toHaveTextContent('2 of 3 sentences kept, 0:05 of speech; 1 someone else’s.')
    expect(screen.queryByRole('heading', { name: 'Working on' })).toBeNull()
  })

  it('brings a recording in, shows it working, and refuses what the server cannot use by name', async () => {
    // applyAccept off: a file dropped on the zone is not filtered by the input's accept, so the screen's check is what refuses it.
    const { user } = openApp('/upload', { user: { applyAccept: false } })
    await screen.findByText('That is every recording brought in.')
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')
    expect(input).not.toBeNull()
    await user.upload(input as HTMLInputElement, file('walk.m4a'))
    await waitFor(() => expect(mock.uploads.map(u => u.name)).toContain('walk.m4a'))
    expect(await screen.findByRole('heading', { name: 'Working on' })).toBeInTheDocument()
    expect(screen.getByText('Waiting to start.', { selector: ':not([data-index] *)' })).toBeInTheDocument()

    server.use(uploadRefused)
    await user.upload(input as HTMLInputElement, file('notes.m4a'))
    expect(await screen.findByText('notes.m4a is not a recording ffmpeg can read.')).toBeInTheDocument()
    server.use(http.post('*/api/uploads', () => new HttpResponse(null, { status: 503, statusText: 'Service Unavailable' })))
    await user.upload(input as HTMLInputElement, file('later.m4a'))
    expect(await screen.findByRole('button', { name: /Try again.*later\.m4a|later\.m4a.*Try again/ })).toBeInTheDocument()
    await user.upload(input as HTMLInputElement, file('photo.png', 'image/png'))
    expect(await screen.findByText(/photo\.png is not a type this accepts/)).toBeInTheDocument()
    expect(mock.uploads.map(u => u.name)).not.toContain('photo.png')
  })

  it('shows a job running, failed and done, with Stop and Try again', async () => {
    server.use(uploadsEveryState)
    mock.uploads = [kitchenUpload, talkUpload, failedUpload]
    const { user } = openApp('/upload')
    const working = await screen.findByRole('heading', { name: 'Working on' })
    const section = working.closest('section') as HTMLElement
    expect(within(section).getByText('Judging sentence 42 of 120')).toBeInTheDocument()
    expect(within(section).getByRole('progressbar')).toBeInTheDocument()
    await user.click(within(section).getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(mock.uploads.find(u => u.id === talkUpload.id)?.job?.state).toBe('cancelled'))

    const failed = items().find(r => r.textContent?.includes(failedUpload.name)) as HTMLElement
    expect(failed).toHaveTextContent('Failed')
    expect(failed).toHaveTextContent('Invalid data found')
    await user.click(within(failed).getByRole('button', { name: `Try again ${failedUpload.name}` }))
    await waitFor(() => expect(mock.uploads.find(u => u.id === failedUpload.id)?.job?.state).toBe('queued'))
  })

  it('opens the sentences of a recording, and keeps someone else’s anyway', async () => {
    const { user, router } = openApp('/upload')
    await user.click(await screen.findByRole('button', { name: `Sentences of ${kitchenUpload.name}` }))
    expect(router.state.location.search).toBe(`?upload=${kitchenUpload.id}`)
    expect(await screen.findByText('The sentences cut from one recording you brought in, in the order said')).toBeInTheDocument()
    const rows = await screen.findAllByText(/Good take|Someone else/)
    expect(rows.map(r => r.textContent)).toEqual(['Good take', 'Someone else', 'Good take'])
    const other = kitchenSentences[1]
    await user.click(screen.getByRole('button', { name: `Keep anyway ${other.prompt_text}` }))
    expect(await screen.findByText('Kept anyway')).toBeInTheDocument()
    expect(mock.uploads[0].kept).toBe(3)
    await user.click(screen.getByRole('link', { name: 'Every take' }))
    expect(router.state.location.search).toBe('')
  })

  it('reads a long list a page at a time', async () => {
    mock.uploads = Array.from({ length: 25 }, (_, i) => ({ ...kitchenUpload, id: 25 - i, name: `memo-${25 - i}.m4a` }))
    const { user } = openApp('/upload')
    await user.click(await screen.findByRole('button', { name: 'Show older recordings' }))
    await waitFor(() => expect(items()).toHaveLength(25))
  })

  it('removes a recording only after a confirm', async () => {
    const { user } = openApp('/upload')
    await user.click(await screen.findByRole('button', { name: `Remove ${kitchenUpload.name}` }))
    const dialog = screen.getByRole('alertdialog', { name: `Remove ${kitchenUpload.name}?` })
    expect(dialog).toHaveTextContent('3 sentences cut from it')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(mock.uploads).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: `Remove ${kitchenUpload.name}` }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Remove recording' }))
    expect(await screen.findByText('Nothing brought in yet')).toBeInTheDocument()
    expect(mock.uploads).toHaveLength(0)
  })

  it('teaches what to bring when there is nothing yet, and says when the list cannot be read', async () => {
    server.use(uploadsEmpty)
    openApp('/upload')
    expect(await screen.findByText('Nothing brought in yet')).toBeInTheDocument()
    server.use(uploadsError)
    openApp('/upload')
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
