// The visual suite, run by strata-react's own runner (`strata-visual`, from strata-react/visual):
// Playwright Chromium screenshots, light and dark, compared with committed baselines in
// tests/visual/baselines/ by pixelmatch. Two targets:
//
// - storybook: every story of the built Storybook (each screen in each server state);
// - app: the production build served as the Python server would (history fallback), each route at
//   a wide and a phone viewport, with every request answered in Node by the same MSW handlers the
//   jsdom tests use. Route states here are the ones a story cannot reach without a click: a skip
//   with its Undo bar, a removal, a field's error. None of them writes to the mock server (each
//   removal is still inside its undo window when the shot is taken), so shots cannot affect each other.
//
// The built app records from the browser's own microphone, which a screenshot run does not have, so
// no route shot presses Record: the recording and review states are covered by the jsdom tests
// (tests/integration/StudioScreen.test.tsx) against the fake microphone.
//
// `npm run test:visual` builds both and compares; `npm run test:visual:update` writes new
// baselines. Look at a diff in tests/visual/output/ before accepting it.
import { defineVisualConfig } from 'strata-react/visual'
import { initialPrompts, initialTakes } from './src/mocks/fixtures'
import { handlers } from './src/mocks/handlers'

export default defineVisualConfig({
  storybook: 'storybook-static',
  app: {
    dir: 'dist-visual',
    handlers,
    viewports: ['wide', 'phone'],
    routes: [
      {
        name: 'studio',
        path: '/',
        states: {
          ready: [],
          skipped: {
            setup: async page => {
              await page.getByRole('button', { name: 'Skip' }).click()
              await page.getByRole('heading', { level: 2, name: initialPrompts[4].text }).waitFor()
              await page.getByRole('button', { name: 'Undo' }).waitFor()
            },
          },
        },
      },
      { name: 'hands-free', path: '/hands-free' },
      {
        name: 'takes',
        path: '/takes',
        states: {
          ready: [],
          removed: {
            setup: async page => {
              await page.getByRole('button', { name: `Remove ${initialTakes[0].prompt_text}` }).click()
              await page.getByRole('button', { name: 'Undo' }).waitFor()
            },
          },
        },
      },
      { name: 'coverage', path: '/coverage' },
      { name: 'system', path: '/system' },
      {
        name: 'settings',
        path: '/settings',
        states: {
          general: [],
          appearance: { path: '/settings?tab=appearance' },
          invalid: {
            setup: async page => {
              await page.getByRole('textbox', { name: 'Longest take, in seconds' }).fill('2')
              await page.getByRole('button', { name: 'Save settings' }).click()
              await page.getByText('Enter a whole number of seconds from 5 to 300.').waitFor()
            },
          },
        },
      },
    ],
  },
})
