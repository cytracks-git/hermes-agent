/**
 * Task drawer — the desktop port of the dashboard's task detail, flat-styled:
 * status menu + meta table, DIAGNOSTICS (the "why is this stuck" panel, with
 * reassign recovery), description (editable), result/summary, dependencies,
 * comments (+composer), activity, run history, and the worker log tail.
 */

import {
  Badge,
  Button,
  cn,
  Codicon,
  compactNumber,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  ErrorState,
  host,
  isSubmitEnter,
  Loader,
  LogView,
  Textarea,
  Tip,
  useMutation,
  useQuery,
  useQueryClient,
  useValue
} from '@hermes/plugin-sdk'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { type CardActivity, cardActivity, formatElapsed } from './activity'
import {
  $boardSlug,
  addComment,
  deleteTask,
  estimateTask,
  fetchLog,
  fetchProfiles,
  fetchTask,
  logKey,
  patchTask,
  PROFILES_KEY,
  reassignTask,
  reclaimTask,
  taskKey,
  uploadAttachment
} from './api'
import { ModelOverrideField, overridePatch } from './model-override'
import {
  type Diagnostic,
  type DiagnosticAction,
  type KanbanAttachment,
  type KanbanEvent,
  type KanbanTaskDetail,
  SEVERITY_TONE,
  type TaskEstimate
} from './types'
import {
  ago,
  Avatar,
  Callout,
  columnLabel,
  duration,
  errText,
  isLockedTarget,
  type KanbanText,
  lockedReason,
  ScrollFade,
  Section,
  shortId,
  StatusMenu,
  useDefaultAssignee,
  useKanban
} from './ui'

/**
 * Turn a task_events row into an operator-readable line. The backend logs
 * machine payloads ("status" + {"status":"ready"}); rendering the raw kind
 * made the feed useless ("status · 2 sec. ago" after a drag). Known kinds get
 * prose with the payload folded in; unknown kinds fall back to kind + compact
 * key=value detail so new backend events still say something.
 */
function eventText(event: KanbanEvent, k: KanbanText): { detail?: string; label: string } {
  let p: Record<string, unknown> = {}

  if (typeof event.payload === 'string' && event.payload) {
    try {
      p = JSON.parse(event.payload) as Record<string, unknown>
    } catch {
      return { label: event.kind.replace(/_/g, ' '), detail: event.payload }
    }
  } else if (event.payload && typeof event.payload === 'object') {
    p = event.payload as Record<string, unknown>
  }

  const str = (key: string): null | string => {
    const value = p[key]

    return typeof value === 'string' && value ? value : null
  }

  const col = (key: string) => {
    const value = str(key)

    return value ? columnLabel(k, value) : null
  }

  switch (event.kind) {
    case 'created':
      return { label: k.evtCreated(col('status') ?? '', str('assignee') ?? '') }
    case 'status': {
      const reason = str('reason')

      return {
        label: k.evtMovedTo(col('status') ?? '?'),
        detail: reason === 'parent_reopened' ? k.evtParentReopened(str('parent') ?? '') : (reason ?? undefined)
      }
    }

    case 'assigned': {
      const assignee = str('assignee')

      return { label: assignee ? k.evtAssignedTo(assignee) : k.evtUnassigned }
    }

    case 'commented':
      return { label: k.evtCommentBy(str('author') ?? k.someone) }

    case 'claimed':
      return { label: str('source_status') === 'review' ? k.evtClaimedReview : k.evtClaimedWorker }

    case 'spawned':
      return { label: k.evtWorkerStarted, detail: p.pid != null ? `pid ${p.pid}` : undefined }

    case 'completed':
      return { label: k.evtCompleted }

    case 'blocked':
      return { label: k.evtBlocked, detail: str('reason') ?? undefined }

    case 'unblocked':
      return { label: k.evtUnblocked(col('status') ?? '') }

    case 'reclaimed':
      return { label: k.evtReclaimed, detail: str('reason') ?? undefined }

    case 'specified':
      return { label: k.evtSpecified }

    case 'promoted':
      return { label: k.evtPromoted }

    case 'scheduled':
      return { label: k.evtScheduled, detail: str('reason') ?? undefined }

    case 'archived':
      return { label: k.evtArchived }

    case 'reprioritized':
      return { label: k.evtReprioritized(String(p.priority ?? '?')) }
    default: {
      const detail = Object.entries(p)
        .filter(([, value]) => value != null && typeof value !== 'object')
        .map(([key, value]) => `${key}=${String(value)}`)
        .join(' ')

      return { label: event.kind.replace(/_/g, ' '), detail: detail || undefined }
    }
  }
}

/**
 * "Where is this card, really?" — age vs current attempt, the last signal WITH
 * its origin, what it waits on, and the operator's next action.
 *
 * Regras que a tela nao pode quebrar (o calculo mora em ./activity):
 *  - heartbeat prova processo vivo, NAO progresso: os dois sao ditos separados;
 *  - sem telemetria a tela diz DESCONHECIDO, nunca "parado" nem "0%";
 *  - motivo de recusa do preflight aparece literal, sem reinterpretacao.
 * Detalhe fica sob demanda (Tip) para a caixa nao virar paredao de texto.
 */
function ActivityPanel({ activity, k }: { activity: CardActivity; k: KanbanText }) {
  const age = formatElapsed(activity.ageSeconds)
  const attempt = formatElapsed(activity.attemptSeconds)
  const beat = formatElapsed(activity.heartbeatSeconds)

  const waitText = (waiting: NonNullable<CardActivity['waiting']>): string => {
    switch (waiting.kind) {
      case 'dependency':
        return waiting.ref ? k.waitDependency(shortId(waiting.ref)) : k.waitDependencyBare

      case 'input':
        return k.waitInput

      case 'rate_limit':
        return k.waitRateLimit

      case 'refused':
        return k.waitRefused

      case 'review':
        return waiting.ref ? k.waitReview(waiting.ref) : k.waitReviewBare

      case 'unassigned':
        return k.waitUnassigned
    }
  }

  const ACTION_TEXT: Record<NonNullable<CardActivity['nextAction']>, string> = {
    answer: k.actAnswer,
    assign: k.actAssign,
    fix_route: k.actFixRoute,
    reclaim: k.actReclaim,
    review: k.actReview,
    wait_parent: k.actWaitParent,
    wait_quota: k.actWaitQuota
  }

  const SOURCE_TEXT = {
    comment: k.signalFromComment,
    event: k.signalFromEvent,
    run: k.signalFromRun
  } as const

  // Vivo sem reportar nada e uma frase DIFERENTE de "nao sei se esta vivo".
  const aliveButSilent = activity.liveness === 'beating' && !activity.progressKnown

  return (
    <Section label={k.progress}>
      <div className="flex flex-col gap-2 rounded-md bg-(--ui-bg-quaternary)/40 p-2.5 text-[0.71rem]">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {age && (
            <span className="text-(--ui-text-tertiary)">
              <span className="text-(--ui-text-quaternary)">{k.cardAge}</span> {age}
            </span>
          )}
          {attempt && (
            <span className="text-(--ui-text-tertiary)">
              <span className="text-(--ui-text-quaternary)">{k.attempt}</span> {attempt}
              {activity.attemptNumber && activity.attemptNumber > 1 ? (
                <span className="ml-1 text-(--ui-text-quaternary)">
                  ({k.attemptNth(activity.attemptNumber)})
                </span>
              ) : null}
            </span>
          )}
          {activity.childProgress && (
            <span className="inline-flex items-center gap-1 text-(--ui-text-tertiary)">
              <Codicon name="checklist" size="0.7rem" />
              {activity.childProgress.done}/{activity.childProgress.total}
            </span>
          )}
          {activity.liveness && (
            <Tip label={activity.heartbeatSeconds == null ? k.neverBeat : k.lastBeat(beat ?? '')}>
              <span
                className={cn(
                  'inline-flex cursor-help items-center gap-1',
                  activity.liveness === 'beating' ? 'text-(--ui-text-quaternary)' : 'text-amber-500'
                )}
              >
                <Codicon name="pulse" size="0.7rem" />
                {activity.liveness === 'beating' ? (beat ?? '') : k.noHeartbeat}
              </span>
            </Tip>
          )}
        </div>

        {activity.lastSignal ? (
          <div className="flex flex-col gap-0.5">
            <div className="flex items-baseline gap-2">
              <span className="text-(--ui-text-quaternary)">{k.lastSignal}</span>
              <span className="min-w-0 truncate font-medium text-(--ui-text-secondary)">
                {activity.lastSignal.kind.replace(/_/g, ' ')}
              </span>
              {/* Origem nomeada: o leitor consegue ir conferir onde isso foi lido. */}
              <button className="shrink-0 underline text-(--ui-text-secondary)" onClick={() => {
                const signal = activity.lastSignal!
                const target = document.getElementById(`kanban-${signal.source}-${signal.id}`)
                target?.scrollIntoView({ block: 'nearest' })
                target?.focus({ preventScroll: true })
              }} type="button">
                {SOURCE_TEXT[activity.lastSignal.source]}
              </button>
              <span className="ml-auto shrink-0 text-(--ui-text-quaternary)">{ago(activity.lastSignal.at)}</span>
            </div>
            {activity.lastSignal.detail && (
              <p className="line-clamp-2 whitespace-pre-wrap text-(--ui-text-tertiary)">
                {activity.lastSignal.detail}
              </p>
            )}
          </div>
        ) : (
          <Tip label={aliveButSilent ? k.heartbeatOnlyHelp : k.progressUnknownHelp}>
            <span className="inline-flex w-fit cursor-help items-center gap-1 text-(--ui-text-quaternary)">
              <Codicon name="question" size="0.7rem" />
              {aliveButSilent ? k.heartbeatOnly : k.progressUnknown}
            </span>
          </Tip>
        )}

        {activity.liveness && !activity.waiting && (
          <p className="text-(--ui-text-tertiary)">{k.operationUnknown}</p>
        )}
        {activity.waiting && (
          <div className="flex flex-col gap-0.5 border-t border-(--ui-border-secondary) pt-2">
            <div className="flex items-baseline gap-2">
              <span className="text-(--ui-text-quaternary)">{k.waitingLabel}</span>
              <span className="min-w-0 font-medium text-(--ui-text-secondary)">{waitText(activity.waiting)}</span>
            </div>
            {'detail' in activity.waiting && activity.waiting.detail && (
              // Texto do preflight/bloqueio copiado verbatim — reescrever aqui
              // criaria uma segunda verdade divergindo da primeira em silencio.
              <p className="whitespace-pre-wrap text-(--ui-text-tertiary)">{activity.waiting.detail}</p>
            )}
          </div>
        )}

        {activity.nextAction && (
          <div className="flex items-baseline gap-2">
            <span className="shrink-0 text-(--ui-text-quaternary)">{k.nextActionLabel}</span>
            <span className="min-w-0 text-(--ui-text-secondary)">{ACTION_TEXT[activity.nextAction]}</span>
          </div>
        )}
      </div>
    </Section>
  )
}

function MetaRow({ children, label }: { children: ReactNode; label: string }) {
  return (
    <>
      <span className="text-(--ui-text-quaternary)">{label}</span>
      <span className="min-w-0 truncate text-(--ui-text-secondary)">{children}</span>
    </>
  )
}

/** The dashboard's diagnostics panel: severity-toned, plain-English, with the
 *  backend's structured recovery actions as buttons. `reassign` is skipped —
 *  the Assignee control in the meta table IS that action, inline. */
function Diagnostics({ items, onReclaim }: { items: Diagnostic[]; onReclaim: () => void }) {
  const k = useKanban()

  const act = (action: DiagnosticAction) => {
    if (action.kind === 'reclaim') {
      onReclaim()
    } else if (action.kind === 'cli_hint') {
      void navigator.clipboard.writeText(String(action.payload?.command ?? action.label))
      host.notify({ kind: 'info', message: k.commandCopied })
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {items.map(diag => {
        const tone = SEVERITY_TONE[diag.severity]
        const actions = diag.actions.filter(action => action.kind === 'reclaim' || action.kind === 'cli_hint')

        return (
          <Callout
            key={`${diag.kind}-${diag.last_seen_at}`}
            title={`${diag.title}${diag.count > 1 ? ` ×${diag.count}` : ''}`}
            tone={tone}
          >
            <p className="whitespace-pre-wrap text-[0.71rem] leading-relaxed text-(--ui-text-secondary)">
              {diag.detail}
            </p>
            {actions.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {actions.map(action => (
                  <Button
                    key={`${action.kind}-${action.label}`}
                    onClick={() => act(action)}
                    size="xs"
                    variant={action.suggested ? 'secondary' : 'outline'}
                  >
                    {action.kind === 'cli_hint' && <Codicon name="copy" size="0.7rem" />}
                    {action.label}
                  </Button>
                ))}
              </div>
            )}
          </Callout>
        )
      })}
    </div>
  )
}

/** Jira-style inline assignee editor: the meta row IS the control — click the
 *  assignee to reassign (reclaims a running worker first, resets the failure
 *  streak — the explicit human recovery action). */
function AssigneeMenu({
  current,
  onReassign
}: {
  current: null | string | undefined
  onReassign: (p: string) => void
}) {
  const k = useKanban()
  const { data: roster } = useQuery({ queryKey: PROFILES_KEY, queryFn: fetchProfiles, staleTime: 60_000 })

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="-mx-1 inline-flex max-w-full items-center gap-1.5 rounded px-1 py-0.5 text-left transition-colors hover:bg-(--chrome-action-hover)"
          type="button"
        >
          {current ? (
            <>
              <Avatar name={current} size="0.875rem" />
              <span className="truncate">{current}</span>
            </>
          ) : (
            <span className="text-(--ui-text-quaternary)">{k.unassigned}</span>
          )}
          <Codicon className="shrink-0 text-(--ui-text-quaternary)" name="chevron-down" size="0.65rem" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {(roster?.profiles ?? []).map(profile => (
          <DropdownMenuItem key={profile.name} onSelect={() => onReassign(profile.name)}>
            <Avatar name={profile.name} size="0.875rem" />
            {profile.name}
            {profile.name === current && <Codicon className="ml-auto" name="check" size="0.8rem" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// Mirrors the review pane's commit-message field: one row tall to start
// (button-height), CSS field-sizing grows it with content, button hugs the
// bottom edge as it grows.
//
// On a RUNNING task the worker polls its comment thread and folds new notes
// into the live turn (OUT-OF-BAND steer), so a plain note reaches the agent
// mid-run within a few seconds — no block/unblock dance. `onRequeue` is the
// heavier option: post the note AND reclaim so the task restarts from scratch
// with the note in context (use when the current run has gone off the rails).
function CommentComposer({
  onRequeue,
  onSubmit,
  pending,
  running
}: {
  onRequeue?: (body: string) => void
  onSubmit: (body: string) => void
  pending: boolean
  running?: boolean
}) {
  const k = useKanban()
  const [body, setBody] = useState('')

  const submit = () => {
    const trimmed = body.trim()

    if (trimmed && !pending) {
      onSubmit(trimmed)
      setBody('')
    }
  }

  const requeue = () => {
    const trimmed = body.trim()

    if (trimmed && !pending && onRequeue) {
      onRequeue(trimmed)
      setBody('')
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="relative">
        <Textarea
          className={cn('field-sizing-content max-h-40 min-h-0 resize-none', running ? 'pr-[3.5rem]' : 'pr-[5rem]')}
          onChange={event => setBody(event.target.value)}
          onKeyDown={event => {
            if (isSubmitEnter(event) && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder={running ? k.messageWorker : k.addComment}
          rows={1}
          size="sm"
          value={body}
        />
        <Button
          className="absolute top-1 right-1"
          disabled={!body.trim() || pending}
          onClick={submit}
          size="xs"
          variant="secondary"
        >
          {running ? k.send : k.comment}
        </Button>
      </div>
      {running && onRequeue && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-[0.625rem] leading-tight text-(--ui-text-quaternary)">{k.deliveredLive}</span>
          <Button className="shrink-0" disabled={!body.trim() || pending} onClick={requeue} size="xs" variant="outline">
            <Codicon name="debug-restart" size="0.7rem" />
            {k.requeueWithNote}
          </Button>
        </div>
      )}
    </div>
  )
}

function DescriptionSection({ body, onSave }: { body: null | string | undefined; onSave: (body: string) => void }) {
  const k = useKanban()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  return (
    <Section
      action={
        <Button
          aria-label={editing ? k.cancelEdit : k.editDescription}
          onClick={() => {
            setDraft(body ?? '')
            setEditing(!editing)
          }}
          size="icon-xs"
          variant="ghost"
        >
          <Codicon name={editing ? 'close' : 'edit'} size="0.75rem" />
        </Button>
      }
      label={k.description}
    >
      {editing ? (
        <div className="flex flex-col gap-1.5">
          <Textarea
            className="min-h-24 text-[0.75rem]"
            onChange={event => setDraft(event.target.value)}
            value={draft}
          />
          <Button
            className="self-end"
            onClick={() => {
              onSave(draft)
              setEditing(false)
            }}
            size="xs"
            variant="secondary"
          >
            {k.save}
          </Button>
        </div>
      ) : body ? (
        <p className="whitespace-pre-wrap text-[0.8125rem] text-(--ui-text-secondary)">{body}</p>
      ) : (
        <p className="text-[0.8125rem] text-(--ui-text-quaternary)">{k.noDescription}</p>
      )}
    </Section>
  )
}

// `latest_summary` is just the newest non-null run summary. A reclaim writes an
// administrative note into that slot; hide those (Runs still shows them).
const isAdminSummary = (summary: string) => /^status changed to \w+ \(dashboard\/direct\)$/.test(summary)

function AttachmentsSection({
  attachments,
  onUpload,
  pending
}: {
  attachments: KanbanAttachment[]
  onUpload: (file: File) => void
  pending: boolean
}) {
  const k = useKanban()
  const fileRef = useRef<HTMLInputElement>(null)

  return (
    <Section
      action={
        <>
          <input
            hidden
            onChange={event => {
              const file = event.target.files?.[0]

              if (file) {
                onUpload(file)
              }

              event.target.value = ''
            }}
            ref={fileRef}
            type="file"
          />
          <Button
            aria-label={k.uploadAttachment}
            disabled={pending}
            onClick={() => fileRef.current?.click()}
            size="icon-xs"
            variant="ghost"
          >
            <Codicon name={pending ? 'sync' : 'cloud-upload'} size="0.8rem" spinning={pending} />
          </Button>
        </>
      }
      label={k.attachments(attachments.length)}
    >
      {attachments.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {attachments.map(attachment => (
            <li className="flex items-center gap-1.5 text-[0.75rem] text-(--ui-text-tertiary)" key={attachment.id}>
              <Codicon name="file" size="0.75rem" />
              {attachment.filename}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[0.75rem] text-(--ui-text-quaternary)">{k.noAttachments}</p>
      )}
    </Section>
  )
}

// Rough effort estimate via the auxiliary (auto-routed) model. Tokens +
// complexity, never dollars — providers don't report cost reliably. Gated
// behind an explicit click + disclaimer since it makes a model call. The
// control keeps a stable footprint (spinner swaps in place) so there's no
// layout jump when it runs.
function EstimateSection({ id }: { id: string }) {
  const k = useKanban()
  const [result, setResult] = useState<null | TaskEstimate>(null)

  const est = useMutation({
    mutationFn: () => estimateTask(id),
    onError: err => host.notify({ kind: 'error', message: errText(err) }),
    onSuccess: r => {
      if (r.ok) {
        setResult(r)
      } else {
        host.notify({ kind: 'warning', message: r.reason || k.couldNotEstimate })
      }
    }
  })

  // A new task resets the cached estimate (the drawer reuses one instance).
  useEffect(() => setResult(null), [id])

  return (
    <Section label={k.estimate}>
      {result?.ok ? (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 text-[0.8125rem]">
            <span className="font-medium tabular-nums text-(--ui-text-secondary)">
              ~{compactNumber(result.est_tokens)} {k.tokUnit}
            </span>
            {result.complexity && (
              <span className="text-(--ui-text-tertiary)">
                · {k.complexity[result.complexity] ?? result.complexity}
              </span>
            )}
            <Tip label={k.reEstimate}>
              <Button
                aria-label={k.reEstimate}
                className="ml-auto"
                disabled={est.isPending}
                onClick={() => est.mutate()}
                size="icon-xs"
                variant="ghost"
              >
                <Codicon name="refresh" size="0.75rem" spinning={est.isPending} />
              </Button>
            </Tip>
          </div>
          {result.rationale && (
            <p className="text-[0.6875rem] leading-relaxed text-(--ui-text-quaternary)">{result.rationale}</p>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Button disabled={est.isPending} onClick={() => est.mutate()} size="xs" variant="outline">
            <Codicon name={est.isPending ? 'loading' : 'dashboard'} size="0.75rem" spinning={est.isPending} />
            {est.isPending ? k.estimating : k.estimateEffort}
          </Button>
          <Tip label={k.estimateTipLong}>
            <span className="text-[0.625rem] text-(--ui-text-quaternary)">{k.makesModelCall}</span>
          </Tip>
        </div>
      )}
    </Section>
  )
}

export function TaskDrawer({
  columns,
  id,
  onClose,
  onOpen
}: {
  columns: string[]
  id: null | string
  onClose: () => void
  onOpen: (id: string) => void
}) {
  const k = useKanban()
  const qc = useQueryClient()
  const slug = useValue($boardSlug)

  // Socket-invalidated (bindApi); the interval is only the socketless heartbeat.
  const { data: detail, error } = useQuery({
    enabled: !!id,
    queryFn: () => fetchTask(id!),
    queryKey: taskKey(slug, id ?? ''),
    refetchInterval: 30_000
  })

  const task = detail?.task
  const running = task?.status === 'running'
  const defaultAssignee = useDefaultAssignee()

  // Um tick proprio: as idades sao derivadas de `Date.now()`, entao sem ele o
  // painel so avancaria quando uma query invalidasse. 5s e a mesma cadencia do
  // relogio da tentativa no card (ui.tsx), e o menor termo exibido e o segundo.
  const [, forceClock] = useState(0)

  useEffect(() => {
    const timer = window.setInterval(() => forceClock(n => n + 1), 5_000)

    return () => window.clearInterval(timer)
  }, [])

  // Falha de leitura do painel NAO pode derrubar o drawer: sem isto, um payload
  // de evento inesperado apagaria descricao, comentarios e acoes de recuperacao
  // — exatamente a tela que o operador usa para consertar o card quebrado.
  //
  // Mas engolir a falha em silencio seria a outra mentira: um painel que
  // simplesmente SOME e indistinguivel de um card sem nada a mostrar. Erro e
  // ausencia sao afirmacoes diferentes, entao a tela diz qual das duas e.
  let activity: CardActivity | null = null
  let activityFailed = false

  try {
    activity = task
      ? cardActivity({
          comments: detail?.comments ?? [],
          defaultAssignee,
          events: detail?.events ?? [],
          // Segundos, nao ms: todos os carimbos do board (`created_at`,
          // `started_at`, `last_heartbeat_at`) sao epoch em SEGUNDOS. Misturar
          // as duas escalas aqui produziria idades absurdas em vez de erro.
          now: Math.floor(Date.now() / 1000),
          runs: detail?.runs ?? [],
          task
        })
      : null
  } catch {
    activity = null
    activityFailed = true
  }

  const { data: log } = useQuery({
    enabled: !!id,
    queryFn: () => fetchLog(id!),
    queryKey: logKey(slug, id ?? ''),
    refetchInterval: running ? 3_000 : 15_000
  })

  // Esc closes the drawer even though it isn't modal (no backdrop to click off).
  useEffect(() => {
    if (!id) {
      return
    }

    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)
  }, [id, onClose])

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: taskKey(slug, id!) })
    void qc.invalidateQueries({ queryKey: ['kanban', 'board', slug] })
  }

  // Optimistic status change against the task cache; rolls back + toasts on a
  // rejected transition (the backend enforces the workflow).
  const moveMut = useMutation({
    mutationFn: (status: string) => patchTask(id!, { status }),
    onMutate: async status => {
      await qc.cancelQueries({ queryKey: taskKey(slug, id!) })
      const previous = qc.getQueryData<KanbanTaskDetail>(taskKey(slug, id!))

      if (previous) {
        qc.setQueryData(taskKey(slug, id!), { ...previous, task: { ...previous.task, status } })
      }

      return { previous }
    },
    onError: (err, _status, context) => {
      if (context?.previous) {
        qc.setQueryData(taskKey(slug, id!), context.previous)
      }

      host.notify({ kind: 'error', message: errText(err) })
    },
    onSettled: invalidate
  })

  const mutate = (fn: () => Promise<unknown>, onDone?: () => void) => () =>
    fn().then(
      () => {
        invalidate()
        onDone?.()
      },
      (err: unknown) => host.notify({ kind: 'error', message: errText(err) })
    )

  const commentMut = useMutation({
    mutationFn: (body: string) => addComment(id!, body),
    onError: err => host.notify({ kind: 'error', message: errText(err) }),
    onSuccess: invalidate
  })

  // "Note & requeue" for a running task: post the note, then reclaim so the
  // dispatcher re-runs it with the note in the worker's context — the one-click
  // replacement for the block → comment → unblock dance.
  const requeueMut = useMutation({
    mutationFn: async (body: string) => {
      await addComment(id!, body)
      await reclaimTask(id!)
    },
    onError: err => host.notify({ kind: 'error', message: errText(err) }),
    onSuccess: () => {
      host.notify({ kind: 'info', message: k.notePosted })
      invalidate()
    }
  })

  const uploadMut = useMutation({
    mutationFn: async (file: File) =>
      uploadAttachment(id!, {
        bytes: await file.arrayBuffer(),
        contentType: file.type || undefined,
        filename: file.name
      }),
    onError: err => host.notify({ kind: 'error', message: errText(err) }),
    onSuccess: invalidate
  })

  if (!id) {
    return null
  }

  const errorMessage = error ? errText(error) : null

  const move = (status: string) => {
    if (!task || status === task.status) {
      return
    }

    if (isLockedTarget(status)) {
      host.notify({ kind: 'info', message: lockedReason(k, status) })

      return
    }

    moveMut.mutate(status)
  }

  return (
    <div className="absolute inset-y-0 right-0 z-20 flex w-[26rem] flex-col border-l border-(--ui-stroke-tertiary) bg-(--ui-bg-elevated) duration-150 ease-out animate-in fade-in slide-in-from-right-4">
      <header className="flex flex-col gap-2 px-4 pt-3.5 pb-3">
        <div className="flex items-center gap-2">
          {task ? (
            <StatusMenu columns={columns} onMove={move} status={task.status} />
          ) : (
            <span className="font-mono text-sm text-(--ui-text-tertiary)">{shortId(id)}</span>
          )}
          {task && (
            <span className="font-mono text-[0.625rem] text-(--ui-text-quaternary)" data-selectable-text="true">
              {shortId(task.id)}
            </span>
          )}
          <div className="ml-auto flex items-center gap-0.5">
            {task && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    aria-label={k.taskActions}
                    className="grid size-6 place-items-center rounded text-(--ui-text-tertiary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground"
                    type="button"
                  >
                    <Codicon name="ellipsis" size="0.9rem" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => {
                      void navigator.clipboard.writeText(task.id)
                      host.notify({ kind: 'info', message: k.copiedId(task.id) })
                    }}
                  >
                    <Codicon name="copy" size="0.85rem" />
                    {k.copyTaskId}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => {
                      void navigator.clipboard.writeText(task.title || task.id)
                      host.notify({ kind: 'info', message: k.copiedTitle })
                    }}
                  >
                    <Codicon name="copy" size="0.85rem" />
                    {k.copyTitle}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={mutate(() => patchTask(task.id, { status: 'archived' }), onClose)}>
                    <Codicon name="archive" size="0.85rem" />
                    {k.archive}
                  </DropdownMenuItem>
                  <DropdownMenuItem className="text-destructive" onSelect={mutate(() => deleteTask(task.id), onClose)}>
                    <Codicon name="trash" size="0.85rem" />
                    {k.delete}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            <button
              aria-label={k.close}
              className="grid size-6 place-items-center rounded text-(--ui-text-tertiary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground"
              onClick={onClose}
              type="button"
            >
              <Codicon name="close" size="0.9rem" />
            </button>
          </div>
        </div>
        {task && (
          <h2 className="text-sm leading-snug font-semibold text-foreground" data-selectable-text="true">
            {task.title || task.id}
          </h2>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4" data-selectable-text="true">
        {errorMessage ? (
          <ErrorState title={errorMessage} />
        ) : !detail || !task ? (
          <div className="grid h-32 place-items-center">
            <Loader type="lemniscate-bloom" />
          </div>
        ) : (
          <div className="flex flex-col gap-4 text-sm">
            <div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-[0.71rem]">
              <MetaRow label={k.assignee}>
                <AssigneeMenu
                  current={task.assignee}
                  onReassign={profile => void mutate(() => reassignTask(task.id, profile))()}
                />
              </MetaRow>
              {typeof task.priority === 'number' && <MetaRow label={k.metaPriority}>{task.priority}</MetaRow>}
              {task.tenant && <MetaRow label={k.metaTenant}>{task.tenant}</MetaRow>}
              {task.workspace_path && (
                <MetaRow label={k.workspace}>
                  {task.workspace_kind ? `${task.workspace_kind}: ` : ''}
                  {task.workspace_path}
                </MetaRow>
              )}
              <MetaRow label={k.model}>
                <ModelOverrideField
                  onChange={next => void mutate(() => patchTask(task.id, overridePatch(next)))()}
                  value={{
                    effort: task.reasoning_effort ?? '',
                    model: task.model_override ?? '',
                    provider: task.provider_override ?? ''
                  }}
                />
              </MetaRow>
              {task.created_by && <MetaRow label={k.metaCreatedBy}>{task.created_by}</MetaRow>}
              {ago(task.created_at) && <MetaRow label={k.metaCreated}>{ago(task.created_at)}</MetaRow>}
              {running && task.worker_pid ? <MetaRow label={k.metaWorkerPid}>{task.worker_pid}</MetaRow> : null}
            </div>

            {activity && <ActivityPanel activity={activity} k={k} />}
            {activityFailed && (
              <Section label={k.progress}>
                <div className="flex items-center gap-1.5 rounded-md bg-(--ui-bg-quaternary)/40 p-2.5 text-[0.71rem] text-amber-500">
                  <Codicon name="warning" size="0.7rem" />
                  {k.activityUnavailable}
                </div>
              </Section>
            )}

            {task.status === 'ready' && !task.assignee && !defaultAssignee && (
              <Callout title={k.readyUnassignedTitle} tone={SEVERITY_TONE.warning}>
                <p className="text-[0.71rem] leading-relaxed text-(--ui-text-secondary)">{k.readyUnassignedBody}</p>
              </Callout>
            )}

            {task.diagnostics && task.diagnostics.length > 0 && (
              <Section label={k.diagnosticsN(task.diagnostics.length)}>
                <Diagnostics items={task.diagnostics} onReclaim={() => void mutate(() => reclaimTask(task.id))()} />
              </Section>
            )}

            <DescriptionSection body={task.body} onSave={body => void mutate(() => patchTask(task.id, { body }))()} />

            <EstimateSection id={task.id} />

            {task.result && (
              <Section label={k.result}>
                <p className="whitespace-pre-wrap text-[0.8125rem] text-(--ui-text-secondary)">{task.result}</p>
              </Section>
            )}

            {task.latest_summary && !isAdminSummary(task.latest_summary) && (
              <Section label={k.latestSummary}>
                <p className="whitespace-pre-wrap text-[0.8125rem] text-(--ui-text-secondary)">{task.latest_summary}</p>
              </Section>
            )}

            {(detail.links.parents.length > 0 || detail.links.children.length > 0) && (
              <Section label={k.dependencies}>
                {(['parents', 'children'] as const).map(side =>
                  detail.links[side].length > 0 ? (
                    <div className="flex flex-wrap items-center gap-1.5" key={side}>
                      <span className="text-[0.6875rem] text-(--ui-text-quaternary)">
                        {side === 'parents' ? k.blockedBy : k.blocks}
                      </span>
                      {detail.links[side].map(linked => (
                        <button
                          className="rounded bg-(--ui-bg-quaternary) px-1.5 py-0.5 font-mono text-[0.625rem] text-(--ui-text-secondary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground"
                          key={linked}
                          onClick={() => onOpen(linked)}
                          type="button"
                        >
                          {shortId(linked)}
                        </button>
                      ))}
                    </div>
                  ) : null
                )}
              </Section>
            )}

            <Section
              action={
                <Tip label={running ? k.commentsHelpRunning : k.commentsHelp}>
                  <span className="grid size-5 place-items-center rounded text-(--ui-text-quaternary) hover:text-(--ui-text-secondary)">
                    <Codicon name="question" size="0.8rem" />
                  </span>
                </Tip>
              }
              label={k.comments(detail.comments.length)}
            >
              {detail.comments.length > 0 && (
                <ul className="flex flex-col gap-2">
                  {detail.comments.map(comment => (
                    <li className="text-[0.75rem]" id={`kanban-comment-${comment.id}`} key={comment.id} tabIndex={-1}>
                      <span className="font-medium text-(--ui-text-secondary)">{comment.author}</span>
                      <span className="ml-2 text-[0.625rem] text-(--ui-text-quaternary)">
                        {ago(comment.created_at)}
                      </span>
                      <p className="whitespace-pre-wrap text-(--ui-text-tertiary)">{comment.body}</p>
                    </li>
                  ))}
                </ul>
              )}
              <CommentComposer
                onRequeue={body => requeueMut.mutate(body)}
                onSubmit={body => commentMut.mutate(body)}
                pending={commentMut.isPending || requeueMut.isPending}
                running={running}
              />
            </Section>

            {detail.events.length > 0 && (
              <Section label={k.activity(detail.events.length)}>
                <ScrollFade deps={detail.events.length} max="7rem">
                  <ul className="flex flex-col gap-1">
                    {detail.events.map(event => {
                      const { detail: extra, label } = eventText(event, k)

                      return (
                        <li className="flex items-baseline gap-2 text-[0.6875rem]" id={`kanban-event-${event.id}`} key={event.id} tabIndex={-1}>
                          <span className="shrink-0 text-(--ui-text-secondary)">{label}</span>
                          {extra && (
                            <span
                              className="min-w-0 truncate text-[0.625rem] text-(--ui-text-quaternary)"
                              title={extra}
                            >
                              {extra}
                            </span>
                          )}
                          <span className="ml-auto shrink-0 text-(--ui-text-quaternary)">{ago(event.created_at)}</span>
                        </li>
                      )
                    })}
                  </ul>
                </ScrollFade>
              </Section>
            )}

            {detail.runs.length > 0 && (
              <Section label={k.runs(detail.runs.length)}>
                <ScrollFade max="11rem">
                  <ul className="flex flex-col gap-1.5">
                    {detail.runs.map(run => {
                      const failed = ['crashed', 'failed', 'timed_out', 'gave_up'].includes(run.outcome ?? run.status)

                      return (
                        <li className="flex flex-col gap-0.5 text-[0.71rem]" id={`kanban-run-${run.id}`} key={run.id} tabIndex={-1}>
                          <div className="flex items-center gap-2">
                            <Badge size="xs" variant={failed ? 'destructive' : 'muted'}>
                              {run.outcome ?? run.status}
                            </Badge>
                            {run.profile && <span className="text-(--ui-text-tertiary)">{run.profile}</span>}
                            {duration(run.started_at, run.ended_at) && (
                              <span className="text-(--ui-text-quaternary)">
                                {duration(run.started_at, run.ended_at)}
                              </span>
                            )}
                            <span className="ml-auto shrink-0 text-(--ui-text-quaternary)">
                              {ago(run.ended_at ?? run.started_at)}
                            </span>
                          </div>
                          {(run.error || run.summary) && (
                            <p
                              className={cn(
                                'line-clamp-2 whitespace-pre-wrap',
                                run.error ? 'text-destructive' : 'text-(--ui-text-quaternary)'
                              )}
                            >
                              {run.error ?? run.summary}
                            </p>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </ScrollFade>
              </Section>
            )}

            {log?.exists && log.content && (
              <Section label={log.truncated ? k.workerLogTail : k.workerLog}>
                <ScrollFade deps={log.content.length} max="12rem">
                  <LogView className="border-0 px-0">{log.content}</LogView>
                </ScrollFade>
              </Section>
            )}

            {Array.isArray(detail.attachments) && (
              <AttachmentsSection
                attachments={detail.attachments}
                onUpload={file => uploadMut.mutate(file)}
                pending={uploadMut.isPending}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
