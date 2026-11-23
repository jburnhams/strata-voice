// The whole app at one URL, for screen stories: the app's own route tree (src/routes.tsx) in a memory
// router, so a story shows the screen in its frame exactly as a person reaches it, with the URL state
// (sort, tab) it was opened with. The microphone is strata-react's fake one: Storybook and the visual
// suite have no hardware to record from.
import { useState } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { type Microphone, MicrophoneContext } from 'strata-react'
import { fakeMicrophone } from 'strata-react/testing'
import { routes } from '../src/routes'

export function AppAt({ route, microphone }: { route: string; microphone?: Microphone }) {
  const [router] = useState(() => createMemoryRouter(routes, { initialEntries: [route] }))
  const [mic] = useState(() => microphone ?? fakeMicrophone())
  return (
    <MicrophoneContext value={mic}>
      <RouterProvider router={router} />
    </MicrophoneContext>
  )
}
