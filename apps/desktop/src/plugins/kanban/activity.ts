/**
 * Derives what a card is ACTUALLY doing — age, current attempt, last verifiable
 * signal, what it waits on, and the operator's next action.
 *
 * Por que um modulo puro e separado da tela: tudo aqui e testavel com relogio
 * fixo, sem render e sem rede. A tela so escolhe palavras e cor.
 *
 * TRES REGRAS QUE ESTE ARQUIVO NAO PODE QUEBRAR (custaram medicao):
 *
 *  1. HEARTBEAT NAO E PROGRESSO. Medido no board atlas: 9614 eventos
 *     `heartbeat` e payload VAZIO nos mais recentes. Heartbeat prova que o
 *     processo respira, nada sobre o trabalho. Contar isso como progresso seria
 *     inventar telemetria que ninguem gravou.
 *  2. AUSENCIA DE DADO E "DESCONHECIDO", NUNCA ZERO. Campo ausente vira `null`
 *     e a tela diz que nao sabe; nao existe "0%" fabricado, nem "sem progresso"
 *     quando na verdade nao ha telemetria nenhuma.
 *  3. MOTIVO DE RECUSA E COPIADO, NAO REESCRITO. `preflight_refused` traz o
 *     texto pronto do preflight (card t_00b18862). Re-derivar aqui criaria uma
 *     segunda verdade que diverge em silencio da primeira.
 */

import { elapsedParts, SECOND } from '@hermes/plugin-sdk'

import type { KanbanComment, KanbanEvent, KanbanRun, KanbanTaskFull } from './types'

/** Sem heartbeat por este tempo, um worker vivo vira suspeito (mesmo limiar da
 *  arc do board, para a tela nao se contradizer). */
export const STALE_AFTER_SECONDS = 120

/** Silencio longo o bastante para valer a pena OFERECER reclaim — bem acima do
 *  limiar de "suspeito", porque propor recuperacao cedo demais convida o
 *  operador a matar worker que ainda estava trabalhando. */
export const RECLAIM_AFTER_SECONDS = 15 * 60

const SUFFIX = { day: 'd', hour: 'h', minute: 'm', second: 's' } as const

/**
 * Compact two-unit duration from a count of SECONDS — `"1h 59m"`, `"2d 4h"`.
 *
 * `null`/`undefined` devolve `null` de proposito: campo ausente nao e duracao
 * zero, e quem chama precisa poder escrever "desconhecido" em vez de "0s".
 */
export function formatElapsed(seconds?: null | number): null | string {
  if (seconds == null) {
    return null
  }

  return elapsedParts(Math.max(0, seconds) * SECOND)
    .map(part => `${part.value}${SUFFIX[part.unit]}`)
    .join(' ')
}

/** Duracao entre dois carimbos em segundos; `null` quando falta um deles ou o
 *  intervalo e invertido (relogio torto nao vira numero bonito). */
export const spanSeconds = (from?: null | number, to?: null | number): null | number =>
  from && to && to >= from ? to - from : null

/** Onde o ultimo sinal foi lido. Sempre nomeado: sinal sem origem verificavel
 *  nao entra na tela. */
export type SignalSource = 'comment' | 'event' | 'run'

export interface ActivitySignal {
  at: number
  id: number | string
  detail?: string
  kind: string
  source: SignalSource
}

/** O que segura o card. `ref` nomeia o outro lado (pai, revisor). */
export type WaitingOn =
  | { detail?: string; kind: 'input' }
  | { detail?: string; kind: 'rate_limit' }
  | { detail?: string; kind: 'refused' }
  | { kind: 'dependency'; ref?: string }
  | { kind: 'review'; ref?: string }
  | { kind: 'unassigned' }

/** Acao do operador. Chave estavel — a frase mora no i18n, em INGLES (12-G). */
export type NextAction = 'answer' | 'assign' | 'fix_route' | 'reclaim' | 'review' | 'wait_parent' | 'wait_quota'

/** Liveness so existe para card rodando; `unknown` quando nunca bateu. */
export type Liveness = 'beating' | 'stale' | 'unknown'

export interface CardActivity {
  ageSeconds: null | number
  attemptNumber: null | number
  attemptSeconds: null | number
  childProgress: null | { done: number; total: number }
  heartbeatSeconds: null | number
  lastSignal: ActivitySignal | null
  liveness: Liveness | null
  nextAction: NextAction | null
  /** `false` = nao ha sinal NENHUM para mostrar (desconhecido), nao "parado". */
  progressKnown: boolean
  waiting: WaitingOn | null
}

export interface ActivityInput {
  comments?: KanbanComment[]
  defaultAssignee?: string
  events?: KanbanEvent[]
  now: number
  runs?: KanbanRun[]
  task: KanbanTaskFull
}

/** Payload normalizado. String ilegivel vira `{}`: o evento ACONTECEU (ele
 *  conta como sinal), so ficou sem detalhe — falha de leitura nao pode apagar
 *  o fato nem derrubar o painel. */
function payloadOf(event: KanbanEvent): Record<string, unknown> {
  const raw = event.payload

  if (typeof raw === 'string') {
    try {
      const parsed: unknown = JSON.parse(raw)

      return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
    } catch {
      return {}
    }
  }

  return raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
}

const text = (payload: Record<string, unknown>, key: string): string | undefined => {
  const value = payload[key]

  return typeof value === 'string' && value.trim() ? value : undefined
}

// Batimento e ruido de liveness, nao trabalho: fica fora de "ultimo sinal" por
// construcao (regra 1 do cabecalho). `respawn_guarded` idem — e o dispatcher
// falando consigo mesmo, milhares de vezes, sem o card ter andado.
const NON_PROGRESS_EVENTS = new Set(['heartbeat', 'respawn_guarded'])

/** Ultimo evento que representa trabalho, ja com detalhe legivel quando houver. */
function latestEventSignal(events: KanbanEvent[]): ActivitySignal | null {
  let best: ActivitySignal | null = null

  for (const event of events) {
    if (NON_PROGRESS_EVENTS.has(event.kind) || !event.created_at) {
      continue
    }

    if (best && event.created_at <= best.at) {
      continue
    }

    const payload = payloadOf(event)

    best = {
      at: event.created_at,
      id: event.id,
      detail: text(payload, 'summary') ?? text(payload, 'reason'),
      kind: event.kind,
      source: 'event'
    }
  }

  return best
}

/** Ultimo run TERMINADO que deixou recado — o handoff explicito do worker. */
function latestRunSignal(runs: KanbanRun[]): ActivitySignal | null {
  let best: ActivitySignal | null = null

  for (const run of runs) {
    const at = run.ended_at

    if (!at || (best && at <= best.at)) {
      continue
    }

    const detail = run.error ?? run.summary

    best = {
      at,
      id: run.id,
      detail: detail ?? undefined,
      kind: run.outcome ?? run.status,
      source: 'run'
    }
  }

  return best
}

function latestCommentSignal(comments: KanbanComment[]): ActivitySignal | null {
  let best: ActivitySignal | null = null

  for (const comment of comments) {
    if (!comment.created_at || (best && comment.created_at <= best.at)) {
      continue
    }

    best = { at: comment.created_at, id: comment.id, detail: comment.body || undefined, kind: 'commented', source: 'comment' }
  }

  return best
}

const newest = (signals: (ActivitySignal | null)[]): ActivitySignal | null =>
  signals.reduce<ActivitySignal | null>((best, s) => (s && (!best || s.at > best.at) ? s : best), null)

/** Evento mais recente de um tipo, e so se for posterior ao inicio da tentativa
 *  atual: estado velho nao pode legendar card que ja voltou a rodar. */
function currentEvent(events: KanbanEvent[], kind: string, since: number): KanbanEvent | null {
  let best: KanbanEvent | null = null

  for (const event of events) {
    if (event.kind === kind && event.created_at >= since && (!best || event.created_at > best.created_at)) {
      best = event
    }
  }

  return best
}

/** O que segura o card AGORA. Ordem = prioridade do que o operador resolve
 *  primeiro; so estados medidos entram, nunca suposicao. */
function waitingOn(input: ActivityInput): WaitingOn | null {
  const { defaultAssignee = '', events = [], task } = input

  if (['running', 'done', 'archived'].includes(task.status)) {
    return null
  }

  // Transicoes explicitas invalidam esperas anteriores; comentario e heartbeat
  // nao resolvem bloqueio. Nao reaproveitar uma recusa historica como estado atual.
  const transitions = new Set(['claimed', 'spawned', 'unblocked', 'promoted', 'review_requested', 'changes_requested'])
  const since = Math.max(task.started_at ?? 0, ...events.filter(event => transitions.has(event.kind)).map(event => event.created_at))

  const refused = currentEvent(events, 'preflight_refused', since)

  if (refused && task.status !== 'running') {
    // Texto do preflight, copiado (regra 3). A tela nao reinterpreta.
    return { detail: text(payloadOf(refused), 'reason'), kind: 'refused' }
  }

  if (task.status === 'blocked') {
    const blocked = currentEvent(events, 'blocked', since)

    return { detail: blocked ? text(payloadOf(blocked), 'reason') : undefined, kind: 'input' }
  }

  const dependency = currentEvent(events, 'dependency_wait', since)

  if (dependency && task.status === 'todo') {
    return { kind: 'dependency', ref: text(payloadOf(dependency), 'parent') }
  }

  const limited = currentEvent(events, 'rate_limited', since)

  if (limited && task.status === 'ready') {
    return { detail: text(payloadOf(limited), 'reason'), kind: 'rate_limit' }
  }

  if (task.status === 'review') {
    return { kind: 'review', ref: task.assignee ?? undefined }
  }

  // Ready sem ninguem E sem fallback: o dispatcher nao vai pegar, ponto. Com
  // fallback configurado nao ha espera — ele pega no proximo tick.
  if (task.status === 'ready' && !task.assignee && !defaultAssignee.trim()) {
    return { kind: 'unassigned' }
  }

  return null
}

const ACTION_FOR: Record<WaitingOn['kind'], NextAction> = {
  dependency: 'wait_parent',
  input: 'answer',
  rate_limit: 'wait_quota',
  refused: 'fix_route',
  review: 'review',
  unassigned: 'assign'
}

/**
 * Read a card's activity. Puro: nada de `Date.now()` aqui dentro — `now` entra
 * pelo parametro para o teste poder fixar o relogio.
 */
export function cardActivity(input: ActivityInput): CardActivity {
  const { comments = [], events = [], now, runs = [], task } = input

  const running = task.status === 'running'
  const heartbeatSeconds = spanSeconds(task.last_heartbeat_at, now)

  let liveness: Liveness | null = null

  if (running) {
    liveness = heartbeatSeconds == null ? 'unknown' : heartbeatSeconds > STALE_AFTER_SECONDS ? 'stale' : 'beating'
  }

  const lastSignal = newest([latestEventSignal(events), latestRunSignal(runs), latestCommentSignal(comments)])
  const waiting = waitingOn(input)

  // Reclaim so depois de silencio longo: oferecer cedo convida a matar worker
  // que ainda trabalhava. Espera explicita tem prioridade sobre recuperacao.
  const nextAction: NextAction | null = waiting
    ? ACTION_FOR[waiting.kind]
    : running && heartbeatSeconds != null && heartbeatSeconds >= RECLAIM_AFTER_SECONDS
      ? 'reclaim'
      : null

  // `{done: 0, total: 0}` NAO e 0% — e "sem filhos". Nao vira barra nenhuma.
  const progress = task.progress
  const childProgress = progress && progress.total > 0 ? { done: progress.done, total: progress.total } : null

  // A TENTATIVA ATUAL e o run mais recente, nao `task.started_at`.
  //
  // Medido no board: t_95203088 tem `started_at` = 1789755714 (a PRIMEIRA
  // largada) e o run mais recente em 1789860256 — 29h de diferenca. Cronometrar
  // a tentativa por `task.started_at` mostraria "29h" para um worker que
  // comecou ha minutos, que e exatamente o numero errado que motivou o card.
  //
  // `worker_started_at` tambem nao serve: no mesmo board vem corrompido
  // (178986025628, 178986104888 — digitos a mais), entao seria pior.
  const latestRun = runs.reduce<KanbanRun | null>((best, run) =>
    !best || (run.started_at ?? 0) > (best.started_at ?? 0) ? run : best, null)

  const attemptStart = latestRun?.started_at ?? task.started_at
  const attemptEnd = latestRun?.ended_at ?? (running ? now : task.completed_at)

  return {
    ageSeconds: spanSeconds(task.created_at, now),
    attemptNumber: runs.length > 0 ? runs.length : null,
    attemptSeconds: spanSeconds(attemptStart, attemptEnd),
    childProgress,
    heartbeatSeconds,
    lastSignal,
    liveness,
    nextAction,
    progressKnown: lastSignal != null,
    waiting
  }
}
