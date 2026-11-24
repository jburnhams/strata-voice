import type { Meta, StoryObj } from '@storybook/react-vite'
import { coverageError, coverageLoading, coverageNoEspeak, coverageNothing, writeDown } from '../src/mocks/handlers'
import { AppAt } from './app-at'

const meta = {
  title: 'Screens/Coverage',
  render: () => <AppAt route="/coverage" />,
  tags: ['visual-wide'],
} satisfies Meta
export default meta
type Story = StoryObj<typeof meta>

/** Part way through a pilot: the starter set's read prompts recorded, a dozen written prompts waiting. */
export const Ready: Story = {}
/** A fresh studio: nothing said, every unit of every known set missing. */
export const NothingRecorded: Story = { beforeEach: ({ msw }) => msw.use(coverageNothing) }
/** The server has no espeak-ng: sounds, pairs and stress are not counted. */
export const NoEspeak: Story = { beforeEach: ({ msw }) => msw.use(coverageNoEspeak) }
/** Press Write: strata-models is not running, and the button says so. */
export const WriterDown: Story = { beforeEach: ({ msw }) => msw.use(writeDown), tags: ['no-visual'] }
export const Loading: Story = { beforeEach: ({ msw }) => msw.use(coverageLoading) }
export const ServerError: Story = { beforeEach: ({ msw }) => msw.use(coverageError) }
export const Phone: Story = { tags: ['visual-phone'] }
