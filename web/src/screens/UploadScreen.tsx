// The one question: "What did the recordings of me that I brought in give the voice model?" A found recording (a
// voice note, a talk, a video) is any format, long, at whatever level, and may hold other people; the server
// (src/stratavoice/ingest.py) levels it, transcribes it, cuts it into sentences, checks whose voice each is and
// judges each like a studio take, in the background. So the screen is two blocks in the order a person asks: bring
// one in (pick or drop; each file's outcome by name, with the server's sentence when it is refused), then what each
// upload gave, newest first. An upload still being worked on shows its job (JobStatus over useJob, polling the
// shared /api/jobs route) above the list, and the list and the takes are read again when it ends. Its sentences are
// takes, so they are listened to and kept anyway on the Takes screen (`/takes?upload=<id>`), not built again here.
// Removing an upload deletes its original and every sentence cut from it, which cannot be undone: a confirm.
import { useQueryClient } from '@tanstack/react-query'
import { Upload as UploadIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import {
  AlertDialog,
  apiPage,
  describeActionError,
  EmptyState,
  FileButton,
  FileDropZone,
  FileOutcomes,
  format,
  HttpError,
  InfiniteList,
  JobStatus,
  PageHeader,
  RowAction,
  Skeleton,
  Status,
  useFileIntake,
  useInfiniteLoad,
  useJob,
} from 'strata-react'
import { activeJob, api, keys, postUpload, type Task, type Upload, uploadSummary, uploadWord } from '../api'

/** Uploads per page. */
export const PAGE_SIZE = 20

/** What the picker offers: any sound or video, and the usual extensions for files a browser gives no type. */
export const ACCEPT = [
  'audio/*',
  'video/*',
  '.m4a',
  '.mp3',
  '.wav',
  '.flac',
  '.ogg',
  '.opus',
  '.aac',
  '.wma',
  '.amr',
  '.mkv',
  '.webm',
] as const

/** The largest file the server takes (ingest.MAX_UPLOAD_BYTES). */
export const MAX_BYTES = 4_000_000_000

function RowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 py-3">
          <Skeleton className="h-3.5 w-48" />
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="hidden h-3.5 w-40 sm:block" />
        </div>
      ))}
    </div>
  )
}

/** One upload's job while it runs: its stage and how far through the sentences. */
function Working({ upload, initial }: { upload: Upload; initial: Task }) {
  const job = useJob({
    queryKey: keys.job(initial.id),
    queryFn: ({ signal }) => api.get('/api/jobs/{job_id}', { path: { job_id: Number(initial.id) }, signal }),
    initialData: initial,
    isRunning: (t: Task) => t.state === 'queued' || t.state === 'running',
    invalidates: [keys.uploads, keys.takes, keys.coverage, keys.system],
  })
  // Started from the row's own status (initialData), so the read is always ready; the fallback is for the type.
  /* v8 ignore next -- @preserve */
  const task = job.status === 'ready' ? job.data : initial
  const p = task.progress
  const now = { ...upload, job: task }
  return (
    <JobStatus
      label={`Bringing in ${upload.name}`}
      running={job.running}
      words={{ running: uploadWord(now).word, finished: 'Brought in', failed: 'Could not bring it in', cancelled: 'Stopped' }}
      summary={uploadSummary(now)}
      progress={p?.total ? { done: p.done, total: p.total } : undefined}
      failed={task.state === 'failed'}
      cancelled={task.state === 'cancelled'}
      onCancel={() => void api.post('/api/jobs/{job_id}/cancel', { path: { job_id: Number(task.id) } }).then(() => job.poll())}
      cancelLabel="Stop"
    />
  )
}

export function UploadScreen() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [removing, setRemoving] = useState<Upload | null>(null)
  const intake = useFileIntake({
    accept: ACCEPT,
    acceptLabel: 'a recording: any audio or video file',
    maxBytes: MAX_BYTES,
    process: async (file, { signal }) => {
      // useFileIntake shows the thrown Error's message, which for an HttpError is its status line; the server's own
      // sentence ("notes.m4a is not a recording ffmpeg can read.") is its reason, and anything else is said as an action's
      // error is (to raise on strata-react).
      await postUpload(file, signal).catch((e: unknown) => {
        throw new Error(e instanceof HttpError && e.reason ? e.reason : describeActionError(e))
      })
      await queryClient.invalidateQueries({ queryKey: keys.uploads })
    },
  })
  const uploads = useInfiniteLoad({
    queryKey: keys.uploads,
    queryFn: ({ cursor, signal }) =>
      api.get('/api/uploads/page', { query: { after: cursor === undefined ? null : Number(cursor), limit: PAGE_SIZE }, signal }),
    itemKey: (u: Upload) => String(u.id),
    ...apiPage<Upload>(),
  })
  const working =
    uploads.status === 'ready'
      ? uploads.data.flatMap(upload => {
          const initial = activeJob(upload)
          return initial ? [{ upload, initial }] : []
        })
      : []

  const retry = async (job: Task) => {
    await api.post('/api/jobs/{job_id}/retry', { path: { job_id: Number(job.id) } })
    await queryClient.invalidateQueries({ queryKey: keys.uploads })
  }

  return (
    <>
      <PageHeader
        title="Upload"
        scope="Recordings of you, brought in: each is levelled, transcribed, cut into sentences and checked for your voice"
      />
      <section aria-labelledby="bring-in" className="grid gap-3">
        <h2 id="bring-in" className="type-heading">
          Bring in a recording
        </h2>
        <FileDropZone onFiles={intake.add} title="Drop recordings of you here" acceptLabel="a recording: any audio or video file">
          <FileButton accept={ACCEPT} multiple onFiles={intake.add} icon={UploadIcon} variant="default">
            Choose recordings
          </FileButton>
        </FileDropZone>
        <FileOutcomes intake={intake} />
      </section>
      {working.length > 0 && (
        <section aria-labelledby="working" className="grid gap-3">
          <h2 id="working" className="type-heading">
            Working on
          </h2>
          {working.map(w => (
            <Working key={w.upload.id} {...w} />
          ))}
        </section>
      )}
      <section aria-labelledby="brought-in" className="grid gap-3">
        <h2 id="brought-in" className="type-heading">
          Brought in
        </h2>
        <InfiniteList
          state={uploads}
          label="Recordings brought in, newest first"
          moreLabel="Show older recordings"
          skeleton={<RowsSkeleton rows={4} />}
          moreSkeleton={<RowsSkeleton />}
          empty={
            <EmptyState title="Nothing brought in yet">
              A recording of you talking (a voice note, a talk, a video) adds to the voice model: drop it above. Only the sentences in your
              voice are kept.
            </EmptyState>
          }
          end="That is every recording brought in."
          estimateSize={64}
        >
          {u => {
            const state = uploadWord(u)
            const failed = u.job?.state === 'failed' ? u.job : null
            return (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 type-body-sm">
                <span className="w-48 min-w-0 truncate font-medium">{u.name}</span>
                <span className="w-36 shrink-0">
                  <Status tone={state.tone}>{state.word}</Status>
                </span>
                <span className="min-w-0 flex-1 text-muted-foreground">{uploadSummary(u)}</span>
                <span className="w-12 shrink-0 text-right tabular-nums">{format.runningTime(u.seconds)}</span>
                <span className="hidden w-40 shrink-0 text-muted-foreground tabular-nums sm:block">{format.dateTime(u.created)}</span>
                <span className="flex shrink-0 gap-1">
                  {u.sentences > 0 && (
                    <RowAction label="Sentences of" subject={u.name} onClick={() => void navigate(`/takes?upload=${u.id}`)} />
                  )}
                  {failed && <RowAction label="Try again" subject={u.name} onClick={() => void retry(failed)} />}
                  <RowAction label="Remove" subject={u.name} onClick={() => setRemoving(u)} />
                </span>
              </div>
            )
          }}
        </InfiniteList>
      </section>
      {removing && (
        <AlertDialog
          open
          onOpenChange={() => setRemoving(null)}
          title={`Remove ${removing.name}?`}
          description={`The recording and the ${format.count(removing.sentences, 'sentence')} cut from it are deleted from the recordings folder. This cannot be undone.`}
          confirm="Remove recording"
          onConfirm={async () => {
            await api.delete('/api/uploads/{upload_id}', { path: { upload_id: removing.id } })
            setRemoving(null)
            for (const key of [keys.uploads, keys.takes, keys.coverage, keys.system]) await queryClient.invalidateQueries({ queryKey: key })
          }}
        />
      )}
    </>
  )
}
