import type { Meta, StoryObj } from '@storybook/react-vite'
import { removeFails, takesEmpty, takesError, takesLoading, takesMany } from '../src/mocks/handlers'
import { AppAt } from './app-at'

const meta = {
  title: 'Screens/Takes',
  render: () => <AppAt route="/takes" />,
  tags: ['visual-wide'],
} satisfies Meta
export default meta
type Story = StoryObj<typeof meta>

export const Ready: Story = {}
/** 50 takes, 20 to a page: scroll the list to load the next. Not screenshotted: when the next page lands depends on timing. */
export const Many: Story = { beforeEach: ({ msw }) => msw.use(takesMany), tags: ['no-visual'] }
export const Loading: Story = { beforeEach: ({ msw }) => msw.use(takesLoading) }
export const Empty: Story = { beforeEach: ({ msw }) => msw.use(takesEmpty) }
export const ServerError: Story = { beforeEach: ({ msw }) => msw.use(takesError) }
/** Removing fails: press Remove, then remove another (or wait) to see the take come back. */
export const RemovingFails: Story = { beforeEach: ({ msw }) => msw.use(removeFails), tags: ['no-visual'] }
export const Phone: Story = { tags: ['visual-phone'] }
