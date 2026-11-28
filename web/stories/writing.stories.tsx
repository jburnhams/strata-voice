import type { Meta, StoryObj } from '@storybook/react-vite'
import {
  writingBuildFailed,
  writingBuilding,
  writingCheckError,
  writingError,
  writingLoading,
  writingNeverBuilt,
  writingNoSample,
  writingPageEmpty,
} from '../src/mocks/handlers'
import { AppAt } from './app-at'

const meta = {
  title: 'Screens/My writing',
  render: () => <AppAt route="/writing" />,
  tags: ['visual-wide'],
} satisfies Meta
export default meta
type Story = StoryObj<typeof meta>

/** Built: how much there is by medium, the frozen split, and what is flagged. */
export const Overview: Story = {}
/** The pieces themselves, with what cleaning took out of a mail struck through. */
export const Browse: Story = { render: () => <AppAt route="/writing?tab=browse" /> }
/** Browsing a filter nothing matches. */
export const BrowseNothing: Story = {
  render: () => <AppAt route="/writing?tab=browse" />,
  beforeEach: ({ msw }) => msw.use(writingPageEmpty),
}
/** The cleaning sample, one piece at a time, answered from the keyboard. */
export const Check: Story = { render: () => <AppAt route="/writing?tab=check" /> }
/** A medium whose sample is all checked. */
export const CheckDone: Story = { render: () => <AppAt route="/writing?tab=check&medium=email-work" /> }
/** The sample could not be read. */
export const CheckError: Story = { render: () => <AppAt route="/writing?tab=check" />, beforeEach: ({ msw }) => msw.use(writingCheckError) }
/** No sample, nothing flagged, nothing assisted. */
export const Bare: Story = { beforeEach: ({ msw }) => msw.use(writingNoSample) }
/** Never built: the first build is offered. */
export const NeverBuilt: Story = { beforeEach: ({ msw }) => msw.use(writingNeverBuilt) }
/** A build part way through. */
export const Building: Story = { beforeEach: ({ msw }) => msw.use(writingBuilding) }
/** The build failed: strata-takeout's view is not there. */
export const BuildFailed: Story = { beforeEach: ({ msw }) => msw.use(writingBuildFailed) }
export const Loading: Story = { beforeEach: ({ msw }) => msw.use(writingLoading) }
export const ServerError: Story = { beforeEach: ({ msw }) => msw.use(writingError) }
export const Phone: Story = { tags: ['visual-phone'] }
