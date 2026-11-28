import { expectOneFilledButton } from 'strata-react/testing'
import { describe, expect, it } from 'vitest'
import {
  writingBuildFailed,
  writingBuilding,
  writingCheckError,
  writingError,
  writingMany,
  writingMarkFails,
  writingNeverBuilt,
  writingNoSample,
  writingPageEmpty,
} from '../../src/mocks/handlers'
import { openApp, screen, waitFor, within } from '../utils/render'
import { mock, server } from '../utils/server'

describe('My writing', () => {
  it('answers with how much there is and what is sealed, and counts each medium', async () => {
    openApp('/writing')
    expect(
      await screen.findByText(
        /^174\.7k\spieces of writing from 2004 to 2026, 7\.9m\swords; 237\.6k\sshort replies set aside\. Everything since 27 Nov 2025 and 23\scorrespondents are sealed for testing\.$/,
      ),
    ).toBeInTheDocument()
    const table = screen.getByRole('grid', { name: 'Writing by medium' })
    const work = within(table).getByRole('row', { name: /Work email/ })
    expect(work).toHaveTextContent('32,700')
    expect(work).toHaveTextContent('50 of 50 checked, 46 right')
    expect(within(table).getByRole('row', { name: /Chats with one person/ })).toHaveTextContent('50 to check')
    expect(screen.getByRole('table', { name: 'Pieces by split' })).toHaveTextContent('Sealed')
    expect(screen.getByRole('grid', { name: 'Pieces flagged' })).toHaveTextContent('Still holds the mail it answers')
    expect(screen.getByText(/written since chat assistants came out/)).toBeInTheDocument()
    expect(screen.getByText(/^Last built /)).toBeInTheDocument()
    expectOneFilledButton()
  })

  it('builds again, and reads the summary again when the build ends', async () => {
    const { user } = openApp('/writing')
    await user.click(await screen.findByRole('button', { name: 'Build again' }))
    expect(await screen.findByRole('region', { name: 'Building the corpus' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Build again' }, { timeout: 4000 })).toBeInTheDocument()
    expect(mock.writing.job?.state).toBe('done')
  })

  it('offers the first build when nothing is read yet', async () => {
    server.use(writingNeverBuilt)
    openApp('/writing')
    expect(await screen.findByText(/^Nothing is read yet: build the corpus/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Build the corpus' })).toBeInTheDocument()
    expect(screen.queryByRole('tablist')).toBeNull()
  })

  it('shows a build while it runs, and lets it be stopped', async () => {
    server.use(writingBuilding)
    const { user } = openApp('/writing')
    expect(await screen.findByText('Cleaning emails')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Build again' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Stop' }))
  })

  it('says why a build failed, and tries it again', async () => {
    server.use(writingBuildFailed)
    const { user } = openApp('/writing')
    expect(await screen.findByText('Nothing is read yet: the last build failed.')).toBeInTheDocument()
    expect(screen.getByText(/unified\.my_writing could not be read/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try the build again' }))
    expectOneFilledButton()
  })

  it('says the server could not answer', async () => {
    server.use(writingError)
    openApp('/writing')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not answer (503)')
  })

  it('browses what counts, with what cleaning took out struck through, and filters it in the URL', async () => {
    const { user, router } = openApp('/writing?tab=browse')
    expect(await screen.findByText(/running late, the train sat outside Reading/)).toBeInTheDocument()
    const list = screen.getByRole('main')
    expect(within(list).queryByText('yep see you soon')).toBeNull()
    const struck = list.querySelectorAll('del')
    expect([...struck].map(d => d.title)).toEqual(['Taken out: quoted text', 'Taken out: a signature'])
    expect(within(list).getByText(/^2\smessages joined$/)).toBeInTheDocument()
    expect(within(list).getByText('Nearly the same as another')).toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: 'Show' }), 'trivial')
    expect(await screen.findByText('yep see you soon')).toBeInTheDocument()
    expect(router.state.location.search).toBe('?tab=browse&show=trivial')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Show' }), 'all')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Medium' }), 'email-work')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Year' }), '2024')
    expect(await screen.findByText(/Nothing you wrote matches these filters/)).toBeInTheDocument()
  })

  it('says when nothing matches', async () => {
    server.use(writingPageEmpty)
    openApp('/writing?tab=browse')
    expect(await screen.findByText('Nothing here')).toBeInTheDocument()
  })

  it('checks the cleaning sample from the keyboard, and each mark can be undone', async () => {
    const { user } = openApp('/writing?tab=check')
    // The first medium with rows left to check is personal email.
    expect(await screen.findByRole('heading', { name: 'Re: Friday' })).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Sample checked' })).toHaveAttribute('aria-valuetext', '12 of 50')
    await user.keyboard('2')
    expect(await screen.findByText('Marked “Quoted text left in”.')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Weekend' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByRole('heading', { name: 'Re: Friday' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cleaned right' }))
    await user.click(screen.getByRole('button', { name: 'Signature left in' }))
    expect(await screen.findByText('Personal email: all checked')).toBeInTheDocument()
    // Leaving the tab sends the mark still waiting.
    await user.click(screen.getByRole('tab', { name: 'Overview' }))
    await waitFor(() => expect(mock.writingRows.find(w => w.id === 7)?.checked_as).toBe('signature'))
    expect(mock.writingRows.find(w => w.id === 4)?.checked_as).toBe('clean')
  })

  it('names a piece with no subject by its medium and day', async () => {
    openApp('/writing?tab=check&medium=chat-direct')
    expect(await screen.findByRole('heading', { name: 'Chats with one person, 2 Jun 2026' })).toBeInTheDocument()
  })

  it('says a medium is all checked', async () => {
    openApp('/writing?tab=check&medium=email-work')
    expect(await screen.findByText('Work email: all checked')).toBeInTheDocument()
    expect(screen.getByText(/^46 of 50 were cleaned right/)).toBeInTheDocument()
  })

  it('says when there is no sample, and leaves out what there is none of', async () => {
    server.use(writingNoSample)
    const { user } = openApp('/writing')
    expect(await screen.findByRole('grid', { name: 'Writing by medium' })).toHaveTextContent('No sample')
    expect(screen.queryByRole('grid', { name: 'Pieces flagged' })).toBeNull()
    expect(screen.queryByText(/chat assistants/)).toBeNull()
    await user.click(screen.getByRole('tab', { name: 'Check cleaning' }))
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Medium' }), 'social')
    expect(await screen.findByText('Posts and comments: nothing to check')).toBeInTheDocument()
    expect(screen.getByText('This medium has no sample to check.')).toBeInTheDocument()
    expect(screen.queryByRole('meter')).toBeNull()
  })

  it('brings a piece back when its mark does not go through', async () => {
    server.use(writingMarkFails)
    const { user } = openApp('/writing?tab=check')
    await user.click(await screen.findByRole('button', { name: 'Not my words' }))
    expect(await screen.findByRole('heading', { name: 'Weekend' })).toBeInTheDocument()
    await user.keyboard('5') // the second mark sends the first, which fails, so the first is back
    expect(await screen.findByRole('heading', { name: 'Re: Friday' })).toBeInTheDocument()
    expect(mock.writingRows.find(w => w.id === 4)?.checked_as).toBeNull()
    server.resetHandlers()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
  })

  it('pages through a lot of writing', async () => {
    server.use(writingMany)
    const { user } = openApp('/writing?tab=browse')
    expect(await screen.findByText(/^Piece number 1,/)).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Show older writing' }))
    expect(await screen.findByText(/^Piece number 31,/)).toBeInTheDocument()
  })

  it('says the sample could not be read', async () => {
    server.use(writingCheckError)
    openApp('/writing?tab=check')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not answer (503)')
  })
})
