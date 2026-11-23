// Render the app the way it runs: its own route tree (src/routes.tsx) in a memory data router, inside
// Strata's providers (renderRoutes from strata-react/testing: a fresh query client with retries
// off, ThemeProvider with storage off), with a user-event `user` beside the usual queries. The
// microphone is strata-react's `fakeMicrophone` (hardware being the one true external here) unless
// a test passes another.
import userEvent from '@testing-library/user-event'
import { fakeMicrophone, type RenderRoutesOptions, renderRoutes } from 'strata-react/testing'
import { routes } from '../../src/routes'

type OpenOptions = Omit<RenderRoutesOptions, 'route'> & { user?: Parameters<typeof userEvent.setup>[0] }

/** The app at `route` (`/settings?tab=appearance`). Returns `router` too, to assert where the URL went. */
export function openApp(route = '/', options: OpenOptions = {}) {
  const { user: userOptions, microphone = fakeMicrophone(), ...rest } = options
  return { user: userEvent.setup(userOptions), ...renderRoutes(routes, { route, microphone, ...rest }) }
}

export { act, screen, waitFor, within } from '@testing-library/react'
