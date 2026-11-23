import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { saveSettingsFails, settingsError, settingsNotConsented } from '../../src/mocks/handlers'
import { openApp, screen, waitFor } from '../utils/render'
import { mock, server } from '../utils/server'

describe('Settings', () => {
  it('starts the form from what the server holds and saves a change', async () => {
    const { user } = openApp('/settings')
    const folder = await screen.findByRole('textbox', { name: 'Recordings folder' })
    expect(folder).toHaveValue('/home/ada/.stratavoice/recordings')
    const seconds = screen.getByRole('textbox', { name: 'Longest take, in seconds' })
    expect(seconds).toHaveValue('60')
    await user.clear(folder)
    await user.type(folder, '/home/ada/voice')
    await user.clear(seconds)
    await user.type(seconds, '90')
    await user.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('Saved', { selector: '[role=status]' })).toBeInTheDocument()
    expect(mock.settings).toEqual({ recordings_dir: '/home/ada/voice', max_take_seconds: 90, consented_on: '2026-11-23' })
  })

  it('says under each field what is wrong, saves nothing, and clears the message as it is fixed', async () => {
    const { user } = openApp('/settings')
    const folder = await screen.findByRole('textbox', { name: 'Recordings folder' })
    const seconds = screen.getByRole('textbox', { name: 'Longest take, in seconds' })
    await user.clear(folder)
    await user.clear(seconds)
    await user.type(seconds, '2')
    await user.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(folder).toHaveAccessibleDescription(/Enter the folder takes are written to/)
    expect(seconds).toHaveAccessibleDescription(/Enter a whole number of seconds from 5 to 300/)
    expect(folder).toBeInvalid()
    expect(mock.settings.max_take_seconds).toBe(60)
    await user.type(folder, '/')
    expect(folder).not.toBeInvalid()
    await user.type(seconds, '0')
    expect(seconds).not.toBeInvalid()
  })

  it('says why the server refused a change', async () => {
    server.use(
      http.put('*/api/settings', () =>
        HttpResponse.json({ detail: 'recordings_dir: must be an absolute path', payload: null }, { status: 400 }),
      ),
    )
    const { user } = openApp('/settings')
    await user.click(await screen.findByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText(/recordings_dir: must be an absolute path\.? The settings were not changed\./)).toBeInTheDocument()
  })

  it('says what happened when saving fails', async () => {
    server.use(saveSettingsFails)
    const { user } = openApp('/settings')
    await user.click(await screen.findByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('The server could not answer (503). The settings were not changed.')).toBeInTheDocument()
  })

  it('says when consent was given, and withdraws it', async () => {
    const { user } = openApp('/settings')
    expect(await screen.findByText(/You agreed to be recorded on .*2026/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Withdraw consent' }))
    expect(await screen.findByText(/Not given\. The studio asks before the first take/)).toBeInTheDocument()
    expect(mock.settings.consented_on).toBe('')
    expect(screen.getByRole('link', { name: 'go to the studio' })).toHaveAttribute('href', '/')
  })

  it('says when withdrawing consent did not go through', async () => {
    const { user } = openApp('/settings')
    const withdraw = await screen.findByRole('button', { name: 'Withdraw consent' })
    server.use(saveSettingsFails)
    await user.click(withdraw)
    expect(await screen.findByText('The server could not answer (503). Consent still stands.')).toBeInTheDocument()
  })

  it('points to the studio when consent was never given', async () => {
    server.use(settingsNotConsented)
    openApp('/settings')
    expect(await screen.findByText(/Not given\./)).toBeInTheDocument()
  })

  it('keeps the tab in the URL, and the colour scheme choice changes the page', async () => {
    const { user, router } = openApp('/settings')
    await user.click(screen.getByRole('tab', { name: 'Appearance' }))
    expect(router.state.location.search).toBe('?tab=appearance')
    await user.click(screen.getByRole('radio', { name: 'Dark' }))
    await waitFor(() => expect(document.documentElement).toHaveClass('dark'))
  })

  it('opens on a tab from a link', () => {
    openApp('/settings?tab=appearance')
    expect(screen.getByRole('tab', { name: 'Appearance' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('radiogroup', { name: 'Colour scheme' })).toBeInTheDocument()
  })

  it('says the server could not answer', async () => {
    server.use(settingsError)
    openApp('/settings')
    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not answer (503)')
  })
})
