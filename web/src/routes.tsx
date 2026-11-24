// The app's route tree, in its own module so the app (main.tsx), the jsdom tests (renderRoutes from
// strata-react/testing) and the stories build their routers from the same objects: a test that
// hand-copied the tree would keep passing after the app's routes changed.
//
// Routes are real paths (/takes, /settings?tab=appearance), not #hashes: the server answers every
// page path with the app (src/stratavoice/server/app.py), so a reload or a shared link opens that screen,
// and anything a person would link to (sort, tab, page) lives in the URL's search.
import type { RouteObject } from 'react-router'
import { CoverageScreen } from './screens/CoverageScreen'
import { Layout } from './screens/Layout'
import { NotFoundScreen } from './screens/NotFoundScreen'
import { SettingsScreen } from './screens/SettingsScreen'
import { StudioScreen } from './screens/StudioScreen'
import { SystemScreen } from './screens/SystemScreen'
import { TakesScreen } from './screens/TakesScreen'

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <StudioScreen /> },
      { path: 'takes', element: <TakesScreen /> },
      { path: 'coverage', element: <CoverageScreen /> },
      { path: 'system', element: <SystemScreen /> },
      { path: 'settings', element: <SettingsScreen /> },
      { path: '*', element: <NotFoundScreen /> },
    ],
  },
]
