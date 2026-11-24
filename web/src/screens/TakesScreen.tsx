// The one question: "What have I recorded, and is each take one I want to keep?" Takes grow without end, so
// they are read a page at a time (useInfiniteLoad over the server's Page, its cursor the last take held ->
// InfiniteList). Each row names the prompt, how the take was judged (the same status word as the studio's), how
// long it runs and when it was made, with Listen and
// Remove as RowActions named by the prompt. One player above the list plays the take chosen, so a long list
// does not mount a player per row. Removing a take is reversible for a few seconds (useUndoable -> UndoBar)
// and then deletes the file; the prompt comes back to the studio's queue when its last take goes.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  apiPage,
  ButtonLink,
  EmptyState,
  format,
  HttpError,
  InfiniteList,
  MediaPlayer,
  PageHeader,
  RowAction,
  Skeleton,
  SPEECH_RATES,
  Status,
  UndoBar,
  useInfiniteLoad,
  useUndoable,
} from 'strata-react'
import { api, crop, keys, kindName, type Take, takeAudio, verdictWord } from '../api'

/** Takes per page. Small enough that the first page is quick, large enough to fill a screen. */
export const PAGE_SIZE = 20

/** Mirrors a row: the same heights and column widths, so nothing moves when the rows arrive. */
function RowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 py-3">
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="h-3.5 w-12" />
          <Skeleton className="hidden h-3.5 w-40 sm:block" />
          <Skeleton className="h-3.5 w-32" />
        </div>
      ))}
    </div>
  )
}

export function TakesScreen() {
  const queryClient = useQueryClient()
  const undoable = useUndoable()
  const [playing, setPlaying] = useState<Take | null>(null)
  const takes = useInfiniteLoad({
    queryKey: keys.takes,
    queryFn: ({ cursor, signal }) =>
      api.get('/api/takes/page', { query: { after: cursor === undefined ? null : Number(cursor), limit: PAGE_SIZE }, signal }),
    itemKey: (t: Take) => String(t.id),
    ...apiPage<Take>(),
  })

  const remove = (t: Take) => {
    if (playing?.id === t.id) setPlaying(null)
    undoable.schedule({
      id: String(t.id),
      message: `Removed the take of “${t.prompt_text}”.`,
      failure: `The take of “${t.prompt_text}” is back: removing it did not go through.`,
      commit: async () => {
        try {
          // A take already gone (a retry after a partial failure) counts as removed.
          await api.delete('/api/takes/{take_id}', { path: { take_id: t.id } }).catch(e => {
            if (!(e instanceof HttpError && e.status === 404)) throw e
          })
        } finally {
          await queryClient.invalidateQueries({ queryKey: keys.takes })
          await queryClient.invalidateQueries({ queryKey: keys.studio })
          await queryClient.invalidateQueries({ queryKey: keys.coverage })
          await queryClient.invalidateQueries({ queryKey: keys.system })
        }
      },
    })
  }

  return (
    <>
      <PageHeader title="Takes" scope="Every take kept, newest first" />
      {playing && (
        <section aria-labelledby="listening" className="grid max-w-xl gap-2">
          <h2 id="listening" className="type-heading">
            Listening
          </h2>
          <MediaPlayer
            label={`Take of “${playing.prompt_text}”`}
            kind="audio"
            src={takeAudio(playing.id)}
            rates={SPEECH_RATES}
            window={crop(playing)}
            showFull={!!crop(playing)}
            autoPlay
          />
        </section>
      )}
      <InfiniteList
        state={takes}
        label="Takes, newest first"
        moreLabel="Show older takes"
        skeleton={<RowsSkeleton rows={8} />}
        moreSkeleton={<RowsSkeleton />}
        empty={
          <EmptyState
            title="No takes yet"
            action={
              <ButtonLink to="/" variant="default">
                Go to the studio
              </ButtonLink>
            }
          >
            Each take you record in the studio is kept here, where you can listen back and remove it.
          </EmptyState>
        }
        end="That is every take."
        estimateSize={45}
      >
        {t =>
          undoable.isRemoved(String(t.id)) ? null : (
            <div className="flex items-center gap-4 py-2 type-body-sm">
              <span className="min-w-0 flex-1 truncate">
                {t.prompt_text}
                <span className="ml-2 text-muted-foreground">{kindName(t.kind)}</span>
              </span>
              <span className="w-28 shrink-0">
                <Status tone={verdictWord(t).tone}>{verdictWord(t).word}</Status>
              </span>
              <span className="w-12 shrink-0 text-right tabular-nums">{format.runningTime(t.seconds)}</span>
              <span className="hidden w-40 shrink-0 text-muted-foreground tabular-nums sm:block">{format.dateTime(t.created)}</span>
              <span className="flex shrink-0 gap-1">
                <RowAction label="Listen to" subject={t.prompt_text} onClick={() => setPlaying(t)} />
                <RowAction label="Remove" subject={t.prompt_text} onClick={() => remove(t)} />
              </span>
            </div>
          )
        }
      </InfiniteList>
      <UndoBar undoable={undoable} />
    </>
  )
}
