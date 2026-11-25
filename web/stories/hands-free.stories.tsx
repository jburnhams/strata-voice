import type { Meta, StoryObj } from '@storybook/react-vite'
import { HttpResponse, http } from 'msw'
import { fakeMicrophone, speechScript } from 'strata-react/testing'
import { keepMisread, queueError, queueLoading, studioNotConsented } from '../src/mocks/handlers'
import { AppAt } from './app-at'

const meta = {
  title: 'Screens/Hands-free',
  render: () => <AppAt route="/hands-free" />,
  tags: ['visual-wide'],
} satisfies Meta
export default meta
type Story = StoryObj<typeof meta>

/** The prompt to read and the queue after it, before listening starts. */
export const Ready: Story = {}
export const BeforeConsent: Story = { beforeEach: ({ msw }) => msw.use(studioNotConsented) }
export const QueueLoading: Story = { beforeEach: ({ msw }) => msw.use(queueLoading) }
export const QueueError: Story = { beforeEach: ({ msw }) => msw.use(queueError) }
export const EveryPromptRead: Story = {
  beforeEach: ({ msw }) => msw.use(http.get('*/api/queue', () => HttpResponse.json({ items: [], next: null, total: null }))),
}
/** Press Start listening: a fake reader says a prompt every few seconds, in real time, and the screen moves on. */
export const Reading: Story = {
  render: () => (
    <AppAt route="/hands-free" microphone={fakeMicrophone({ speed: 1, loop: true, script: speechScript(1, { speak: 2, gap: 2 }) })} />
  ),
  tags: ['no-visual'],
}
/** Every take misses words: each prompt goes back in the queue, after the one being read. */
export const Misread: Story = {
  beforeEach: ({ msw }) => msw.use(keepMisread),
  render: () => (
    <AppAt route="/hands-free" microphone={fakeMicrophone({ speed: 1, loop: true, script: speechScript(1, { speak: 2, gap: 2 }) })} />
  ),
  tags: ['no-visual'],
}
export const Phone: Story = { tags: ['visual-phone'] }
