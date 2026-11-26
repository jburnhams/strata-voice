import type { Meta, StoryObj } from '@storybook/react-vite'
import { uploadsEmpty, uploadsError, uploadsEveryState, uploadsLoading } from '../src/mocks/handlers'
import { AppAt } from './app-at'

const meta = {
  title: 'Screens/Upload',
  render: () => <AppAt route="/upload" />,
  tags: ['visual-wide'],
} satisfies Meta
export default meta
type Story = StoryObj<typeof meta>

/** One recording brought in: three sentences, two kept and one someone else's. */
export const Ready: Story = {}
/** One recording of each state: brought in, still being judged (under "Working on", with Stop), and failed. */
export const EveryState: Story = { beforeEach: ({ msw }) => msw.use(uploadsEveryState) }
export const Loading: Story = { beforeEach: ({ msw }) => msw.use(uploadsLoading) }
export const Empty: Story = { beforeEach: ({ msw }) => msw.use(uploadsEmpty) }
export const ServerError: Story = { beforeEach: ({ msw }) => msw.use(uploadsError) }
export const Phone: Story = { beforeEach: ({ msw }) => msw.use(uploadsEveryState), tags: ['visual-phone'] }
