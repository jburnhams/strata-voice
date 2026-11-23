// The one question: "Where do my recordings go, and have I agreed to be recorded?" Two tabs whose choice lives
// in the URL (?tab=appearance), so a link can open either one. General is a form over the server's
// settings: the fields start from what the server holds (rendered inside DataView's ready state,
// so they are never blank while loading), problems are said under the field they belong to (the
// action's `validate`, and the server's own refusal as the error's reason), and saving is one
// AsyncButton through Saving… and Saved. Consent sits below it with its own outline button, as
// withdrawing it is a separate act from saving the form. Appearance is Strata's ColorSchemeChoice,
// which ThemeProvider (main.tsx) keeps in this browser.
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import {
  AsyncButton,
  ColorSchemeChoice,
  DataView,
  EmptyState,
  Field,
  format,
  Input,
  PageHeader,
  Skeleton,
  Tabs,
  TextLink,
  useAsyncAction,
  useLoad,
} from 'strata-react'
import { api, keys, type Settings } from '../api'

const tabs = [
  { value: 'general', label: 'General' },
  { value: 'appearance', label: 'Appearance' },
]

export function SettingsScreen() {
  return (
    <>
      <PageHeader title="Settings" scope="Saved on this computer, for every browser that opens the app" />
      <Tabs param="tab" items={tabs} label="Settings">
        {tab => (tab === 'appearance' ? <Appearance /> : <General />)}
      </Tabs>
    </>
  )
}

function General() {
  const load = useLoad({ queryKey: keys.settings, queryFn: () => api.get('/api/settings') })
  return (
    <DataView
      state={load}
      isEmpty={() => false}
      skeleton={<FormSkeleton />}
      empty={<EmptyState title="No settings">The server sent none.</EmptyState>}
    >
      {s => <SettingsForm current={s} />}
    </DataView>
  )
}

/** Mirrors the form: the two fields with their hints, the button, then the consent block. Heights are the
 *  controls' own (--control-h), so the skeleton follows the app's density. */
function FormSkeleton() {
  return (
    <div className="grid max-w-xl gap-6" aria-hidden>
      {[0, 1].map(i => (
        <div key={i} className="grid gap-1.5">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-(--control-h) w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      ))}
      <Skeleton className="h-(--control-h) w-32" />
      <Skeleton className="h-16 w-full" />
    </div>
  )
}

/** What is wrong with the longest-take field, in the server's words, or undefined. */
export function secondsProblem(value: string): string | undefined {
  const n = Number(value)
  return Number.isInteger(n) && n >= 5 && n <= 300 ? undefined : 'Enter a whole number of seconds from 5 to 300.'
}

export function SettingsForm({ current }: { current: Settings }) {
  const queryClient = useQueryClient()
  const [folder, setFolder] = useState(current.recordings_dir)
  const [seconds, setSeconds] = useState(String(current.max_take_seconds))

  const save = useAsyncAction(
    async () => {
      await api.put('/api/settings', { json: { recordings_dir: folder.trim(), max_take_seconds: Number(seconds) } })
      // Everything that reads the settings reads again.
      await queryClient.invalidateQueries({ queryKey: keys.settings })
      await queryClient.invalidateQueries({ queryKey: keys.studio })
      await queryClient.invalidateQueries({ queryKey: keys.system })
    },
    {
      validate: () => ({
        recordings_dir: folder.trim() ? undefined : 'Enter the folder takes are written to, such as /home/ada/voice.',
        max_take_seconds: secondsProblem(seconds),
      }),
    },
  )

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void save.run()
  }

  return (
    <div className="grid max-w-xl gap-10">
      <form onSubmit={onSubmit} noValidate className="grid gap-6">
        <Field
          label="Recordings folder"
          hint="Where takes are written. A folder that holds your voice is personal: keep it on a disk you back up and nobody else reads. Takes already made stay where they are."
          error={save.fieldErrors.recordings_dir}
        >
          <Input
            value={folder}
            onChange={e => {
              setFolder(e.target.value)
              save.clearFieldError('recordings_dir')
            }}
            autoComplete="off"
            className="font-mono"
          />
        </Field>
        <Field
          label="Longest take, in seconds"
          hint="A take that runs longer stops on its own, so a recorder left running does not fill the disk."
          error={save.fieldErrors.max_take_seconds}
        >
          <Input
            value={seconds}
            inputMode="numeric"
            onChange={e => {
              setSeconds(e.target.value)
              save.clearFieldError('max_take_seconds')
            }}
            autoComplete="off"
            className="max-w-32 tabular-nums"
          />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <AsyncButton
            type="submit"
            variant="default"
            phase={save.phase}
            error={save.error}
            labels={{ idle: 'Save settings', pending: 'Saving…', done: 'Saved' }}
          />
          {save.phase === 'error' && <p className="type-body-sm text-danger">{save.error} The settings were not changed.</p>}
        </div>
      </form>
      <ConsentSetting agreed={current.consented_on} />
    </div>
  )
}

/** Consent is a setting: when it was given, and the way to withdraw it (recording stops; takes stay until removed). */
function ConsentSetting({ agreed }: { agreed: string }) {
  const queryClient = useQueryClient()
  const withdraw = useAsyncAction(async () => {
    await api.put('/api/settings', { json: { consented_on: '' } })
    await queryClient.invalidateQueries({ queryKey: keys.settings })
    await queryClient.invalidateQueries({ queryKey: keys.studio })
  })
  return (
    <section aria-labelledby="consent" className="grid gap-3">
      <h2 id="consent" className="type-heading">
        Consent to record
      </h2>
      {agreed ? (
        <>
          <p className="type-body-sm">
            You agreed to be recorded on {format.date(`${agreed}T12:00:00Z`)}. Withdrawing stops the studio recording; the takes already
            kept stay until you remove them on the Takes screen.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <AsyncButton
              variant="outline"
              phase={withdraw.phase}
              error={withdraw.error}
              onClick={() => void withdraw.run()}
              labels={{ idle: 'Withdraw consent', pending: 'Withdrawing…', done: 'Withdrawn' }}
            />
            {withdraw.phase === 'error' && <p className="type-body-sm text-danger">{withdraw.error} Consent still stands.</p>}
          </div>
        </>
      ) : (
        <p className="type-body-sm">
          Not given. The studio asks before the first take: <TextLink to="/">go to the studio</TextLink>.
        </p>
      )}
    </section>
  )
}

function Appearance() {
  return (
    <div className="grid max-w-xl gap-3">
      <ColorSchemeChoice legend="Colour scheme" />
      <p className="type-body-sm text-muted-foreground">Kept in this browser only.</p>
    </div>
  )
}
