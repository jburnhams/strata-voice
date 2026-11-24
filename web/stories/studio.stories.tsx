import type { Meta, StoryObj } from '@storybook/react-vite'
import { fakeMicrophone } from 'strata-react/testing'
import { keepFails, keepMisread, keepUnchecked, studioDone, studioError, studioLoading, studioNotConsented } from '../src/mocks/handlers'
import { AppAt } from './app-at'

const meta = {
  title: 'Screens/Studio',
  render: () => <AppAt route="/" />,
  tags: ['visual-wide'],
} satisfies Meta
export default meta
type Story = StoryObj<typeof meta>

/** The next prompt, ready to record. Press Record (or R): the fake microphone sends a steady tone. */
export const Ready: Story = {}
export const BeforeConsent: Story = { beforeEach: ({ msw }) => msw.use(studioNotConsented) }
export const EveryPromptRecorded: Story = { beforeEach: ({ msw }) => msw.use(studioDone) }
export const Loading: Story = { beforeEach: ({ msw }) => msw.use(studioLoading) }
export const ServerError: Story = { beforeEach: ({ msw }) => msw.use(studioError) }
/** A microphone that is too quiet: record, stop, and the take is judged. */
export const QuietMicrophone: Story = {
  render: () => <AppAt route="/" microphone={fakeMicrophone({ amplitude: 0.01 })} />,
  tags: ['no-visual'],
}
/** The browser refused the microphone: press Record to see what the studio says. */
export const MicrophoneRefused: Story = {
  render: () => (
    <AppAt
      route="/"
      microphone={fakeMicrophone({
        refuse: 'The browser was not allowed to use the microphone. Allow it from the address bar, then try again.',
      })}
    />
  ),
  tags: ['no-visual'],
}
/** The server does not keep the take: record and stop to see Try again. */
export const KeepingFails: Story = { beforeEach: ({ msw }) => msw.use(keepFails), tags: ['no-visual'] }
/** The take missed words: record and stop to see the studio ask again, with Keep it anyway beside Record again. */
export const Misread: Story = { beforeEach: ({ msw }) => msw.use(keepMisread), tags: ['no-visual'] }
/** strata-models is not running: record and stop to see the take kept with its words not checked. */
export const NotChecked: Story = { beforeEach: ({ msw }) => msw.use(keepUnchecked), tags: ['no-visual'] }
export const Phone: Story = { tags: ['visual-phone'] }
