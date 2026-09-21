import { describe, expect, it } from 'vitest'

import { type ActivityInput, cardActivity, formatElapsed } from './activity'
import type { KanbanEvent, KanbanRun, KanbanTaskFull } from './types'

// Relogio fixo: nada aqui pode depender de Date.now(). Um teste de duracao que
// le o relogio real passa hoje e reprova amanha por motivo errado.
const NOW = 1_800_000_000
const s = (secondsAgo: number) => NOW - secondsAgo

const MIN = 60
const HOUR = 60 * MIN
const DAY = 24 * HOUR

const task = (over: Partial<KanbanTaskFull> = {}): KanbanTaskFull => ({
  id: 't_example',
  title: 'Example',
  status: 'running',
  created_at: s(3 * DAY),
  ...over
})

const event = (kind: string, secondsAgo: number, payload: unknown = {}): KanbanEvent => ({
  id: 1_000 - secondsAgo,
  kind,
  payload,
  created_at: s(secondsAgo)
})

const run = (over: Partial<KanbanRun> = {}): KanbanRun => ({ id: 1, status: 'running', ...over })

const input = (over: Partial<ActivityInput> = {}): ActivityInput => ({
  now: NOW,
  task: task(),
  ...over
})

describe('formatElapsed', () => {
  it('keeps minutes visible above a day and rejects non-finite telemetry', () => {
    expect(formatElapsed(2 * DAY + 4 * HOUR + 7 * MIN)).toBe('2d 4h 7m')
    expect(formatElapsed(Number.NaN)).toBeNull()
    expect(formatElapsed(Number.POSITIVE_INFINITY)).toBeNull()
  })
  it('renders two units so an hour-scale label keeps moving every minute', () => {
    // O defeito original: "1h" parado por 59 minutos.
    expect(formatElapsed(HOUR + 59 * MIN)).toBe('1h 59m')
    expect(formatElapsed(2 * DAY + 4 * HOUR)).toBe('2d 4h')
  })

  it('omits a zero remainder and renders sub-minute durations alone', () => {
    expect(formatElapsed(2 * HOUR)).toBe('2h')
    expect(formatElapsed(42)).toBe('42s')
  })

  it('returns null for a missing duration instead of "0s"', () => {
    // Campo ausente NAO e duracao zero; quem chama tem de poder dizer
    // "desconhecido" em vez de mentir um numero.
    expect(formatElapsed(null)).toBeNull()
    expect(formatElapsed(undefined)).toBeNull()
  })
})

describe('cardActivity — age is not the attempt', () => {
  it('never uses an old run as the replacement claim or a heartbeat from that run', () => {
    const current = run({ id: 2, started_at: s(MIN) })
    const old = run({ id: 1, started_at: s(DAY), ended_at: s(HOUR), status: 'ended' })
    const t = task({ current_run_id: 2, started_at: s(DAY), last_heartbeat_at: s(2 * MIN) })
    expect(cardActivity(input({ task: t, runs: [old] })).attemptSeconds).toBeNull()
    expect(cardActivity(input({ task: t, runs: [current, old] })).attemptSeconds).toBe(MIN)
    expect(cardActivity(input({ task: t, runs: [current, old] })).liveness).toBe('unknown')
  })
  it('keeps card age and current attempt as separate readings', () => {
    const act = cardActivity(
      input({ task: task({ created_at: s(3 * DAY), started_at: s(2 * HOUR + 5 * MIN) }) })
    )

    expect(act.ageSeconds).toBe(3 * DAY)
    expect(act.attemptSeconds).toBeNull()
    expect(formatElapsed(act.ageSeconds)).toBe('3d')
    expect(formatElapsed(act.attemptSeconds)).toBeNull()
  })

  it('reports a replacement attempt from the CURRENT claim, not the first one', () => {
    // Card velho, tentativa nova: confundir os dois era exatamente o erro que
    // fazia o quadro parecer travado ha dias.
    //
    // `task.started_at` fica na PRIMEIRA largada e NAO e reescrito a cada
    // reclaim — medido no board real: t_95203088 tem started_at 29h atras e o
    // run corrente comecou ha minutos. Por isso o cenario aqui mantem
    // `started_at` la atras de proposito: se o calculo voltar a usa-lo, este
    // teste tem de acusar. (Com started_at = s(3 * MIN) o teste passava com as
    // DUAS implementacoes, isto e, nao media nada.)
    const act = cardActivity(
      input({
        task: task({ created_at: s(9 * DAY), started_at: s(9 * DAY) }),
        runs: [
          run({ id: 1, status: 'ended', outcome: 'crashed', started_at: s(9 * DAY), ended_at: s(8 * DAY) }),
          run({ id: 2, status: 'running', started_at: s(3 * MIN) })
        ]
      })
    )

    expect(formatElapsed(act.attemptSeconds)).toBe('3m')
    expect(act.attemptNumber).toBe(2)
    // E a idade continua contando os 9 dias: as duas leituras convivem.
    expect(formatElapsed(act.ageSeconds)).toBe('9d')
  })

  it('stops a completed attempt at its end, and selects it independently of response order', () => {
    const finished = run({ id: 2, status: 'ended', started_at: s(HOUR), ended_at: s(20 * MIN) })
    const old = run({ id: 1, status: 'ended', started_at: s(DAY), ended_at: s(23 * HOUR) })

    for (const runs of [[old, finished], [finished, old]]) {
      const act = cardActivity(input({ task: task({ status: 'done' }), runs }))
      expect(act.attemptSeconds).toBe(40 * MIN)
    }
  })

  it('says nothing about an attempt that never started', () => {
    const act = cardActivity(input({ task: task({ started_at: null, status: 'ready' }) }))

    expect(act.attemptSeconds).toBeNull()
    expect(formatElapsed(act.attemptSeconds)).toBeNull()
  })
})

describe('cardActivity — progress needs a verifiable origin', () => {
  it('names the event it read, with its own timestamp', () => {
    const act = cardActivity(
      input({ events: [event('claimed', 40 * MIN), event('review_requested', 9 * MIN, { summary: 'did the thing' })] })
    )

    expect(act.lastSignal).toEqual({
      at: s(9 * MIN),
      id: 1_000 - 9 * MIN,
      detail: 'did the thing',
      kind: 'review_requested',
      source: 'event'
    })
  })

  it('prefers a finished run summary over an older event', () => {
    const act = cardActivity(
      input({
        events: [event('claimed', 50 * MIN)],
        runs: [run({ id: 7, status: 'ended', outcome: 'done', summary: 'shipped', ended_at: s(4 * MIN) })]
      })
    )

    expect(act.lastSignal?.source).toBe('run')
    expect(act.lastSignal?.detail).toBe('shipped')
    expect(act.lastSignal?.at).toBe(s(4 * MIN))
  })

  it('counts a human comment as a signal', () => {
    const act = cardActivity(
      input({ comments: [{ id: 3, author: 'h1', body: 'answered', created_at: s(2 * MIN) }] })
    )

    expect(act.lastSignal).toMatchObject({ kind: 'commented', source: 'comment' })
  })

  it('CONTROLE NEGATIVO: a heartbeat is NOT progress, even a fresh one', () => {
    // Medido no board atlas: 9614 eventos `heartbeat`, payload VAZIO nos mais
    // recentes. Contar isso como progresso seria inventar telemetria. O card
    // segue vivo e SEM progresso reportado — e a tela tem de dizer as duas.
    const act = cardActivity(
      input({
        events: [event('heartbeat', 10)],
        task: task({ last_heartbeat_at: s(10), started_at: s(2 * HOUR) })
      })
    )

    expect(act.lastSignal).toBeNull()
    expect(act.progressKnown).toBe(false)
    expect(act.heartbeatSeconds).toBe(10)
    expect(act.liveness).toBe('beating')
  })

  it('CONTROLE NEGATIVO: no telemetry at all reads unknown, never "no progress"', () => {
    const act = cardActivity(input({ events: [], runs: [], comments: [] }))

    expect(act.lastSignal).toBeNull()
    expect(act.progressKnown).toBe(false)
  })

  it('CONTROLE POSITIVO: a board with signals is not blanket-unknown', () => {
    // Um sensor que responde "desconhecido" sempre e tao inutil quanto um que
    // nunca responde. Mesma entrada, um evento real -> progressKnown vira true.
    const act = cardActivity(input({ events: [event('spawned', 5 * MIN, { pid: 42 })] }))

    expect(act.progressKnown).toBe(true)
    expect(act.lastSignal?.kind).toBe('spawned')
  })

  it('survives a malformed payload instead of blanking the panel', () => {
    // Falha de leitura e um caso previsto pelo card: o evento ainda conta como
    // sinal (ele existiu), so nao tem detalhe.
    const act = cardActivity(input({ events: [{ id: 1, kind: 'spawned', payload: '{{{', created_at: s(MIN) }] }))

    expect(act.lastSignal?.kind).toBe('spawned')
    expect(act.lastSignal?.detail).toBeUndefined()
  })
})

describe('cardActivity — liveness is measured, not assumed', () => {
  it('flags a silent worker as stale rather than sweeping green', () => {
    const act = cardActivity(input({ task: task({ last_heartbeat_at: s(11 * MIN), started_at: s(HOUR) }) }))

    expect(act.liveness).toBe('stale')
  })

  it('says unknown when a running card never reported a heartbeat', () => {
    const act = cardActivity(input({ task: task({ last_heartbeat_at: null, started_at: s(HOUR) }) }))

    expect(act.liveness).toBe('unknown')
    expect(act.heartbeatSeconds).toBeNull()
  })

  it('does not report liveness for a card that is not running', () => {
    const act = cardActivity(input({ task: task({ status: 'todo', started_at: null }) }))

    expect(act.liveness).toBeNull()
  })
})

describe('cardActivity — waiting and next action', () => {
  it('does not resurrect waits after completion or a newer recovery event', () => {
    const events = [event('preflight_refused', HOUR, { reason: 'auth unavailable' }), event('unblocked', MIN)]

    for (const status of ['done', 'archived', 'ready']) {
      expect(cardActivity(input({ task: task({ status, assignee: 'executor' }), events })).waiting).toBeNull()
    }

    const dependency = [event('dependency_wait', HOUR, { parent: 't_old' })]
    expect(cardActivity(input({ task: task({ status: 'review', assignee: 'revisor' }), events: dependency })).waiting)
      .toEqual({ kind: 'review', ref: 'revisor' })
  })

  it('reads a dependency wait off the event payload, naming the parent', () => {
    const act = cardActivity(
      input({
        events: [event('dependency_wait', MIN, { parent: 't_03ccc344', reason: 'parent_not_done' })],
        task: task({ status: 'todo', started_at: null })
      })
    )

    expect(act.waiting).toEqual({ kind: 'dependency', ref: 't_03ccc344' })
    expect(act.nextAction).toBe('wait_parent')
  })

  it('reads a block reason from the task, not from a guess', () => {
    const act = cardActivity(
      input({
        events: [event('blocked', 2 * MIN, { kind: 'needs_input', reason: 'which option?' })],
        task: task({ status: 'blocked', started_at: null })
      })
    )

    expect(act.waiting).toEqual({ detail: 'which option?', kind: 'input' })
    expect(act.nextAction).toBe('answer')
  })

  it('surfaces a rate limit as waiting on the provider, not as a crash', () => {
    const act = cardActivity(
      input({ events: [event('rate_limited', 30, { exit_code: 75 })], task: task({ status: 'ready' }) })
    )

    expect(act.waiting?.kind).toBe('rate_limit')
    expect(act.nextAction).toBe('wait_quota')
  })

  it('passes a preflight refusal through VERBATIM, without re-deriving it', () => {
    // O motivo pertence ao preflight (card t_00b18862). Reescrever aqui criaria
    // uma segunda verdade que diverge silenciosamente da primeira.
    const reason = 'profile "reviewer" does not exist -> create it or reassign to revisor'

    const act = cardActivity(
      input({
        events: [event('preflight_refused', 20, { codes: ['profile_missing'], reason })],
        task: task({ status: 'ready', started_at: null })
      })
    )

    expect(act.waiting).toEqual({ detail: reason, kind: 'refused' })
    expect(act.nextAction).toBe('fix_route')
  })

  it('tells a ready card with nobody attached to get an assignee', () => {
    const act = cardActivity(
      input({ defaultAssignee: '', task: task({ assignee: null, status: 'ready', started_at: null }) })
    )

    expect(act.waiting).toEqual({ kind: 'unassigned' })
    expect(act.nextAction).toBe('assign')
  })

  it('CONTROLE NEGATIVO: a configured fallback removes the unassigned warning', () => {
    const act = cardActivity(
      input({ defaultAssignee: 'executor', task: task({ assignee: null, status: 'ready', started_at: null }) })
    )

    expect(act.waiting).toBeNull()
    expect(act.nextAction).toBeNull()
  })

  it('points a review card at the reviewer, never at the author', () => {
    const act = cardActivity(input({ task: task({ assignee: 'revisor', status: 'review', started_at: null }) }))

    expect(act.waiting).toEqual({ kind: 'review', ref: 'revisor' })
    expect(act.nextAction).toBe('review')
  })

  it('only offers reclaim once the worker has actually gone quiet', () => {
    const fresh = cardActivity(input({ task: task({ last_heartbeat_at: s(20), started_at: s(HOUR) }) }))
    const silent = cardActivity(input({ task: task({ last_heartbeat_at: s(30 * MIN), started_at: s(HOUR) }) }))

    // Controle positivo/negativo no mesmo par: vivo NAO pede reclaim, mudo pede.
    expect(fresh.nextAction).toBeNull()
    expect(silent.nextAction).toBe('reclaim')
  })

  it('leaves a plain running card alone — no invented next action', () => {
    const act = cardActivity(
      input({ task: task({ assignee: 'executor', last_heartbeat_at: s(15), started_at: s(5 * MIN) }) })
    )

    expect(act.waiting).toBeNull()
    expect(act.nextAction).toBeNull()
  })

  it('ignores an ancient event that a newer state already superseded', () => {
    // Estado inalterado x estado velho: um dependency_wait de 2 dias atras nao
    // pode legendar um card que ja esta rodando agora.
    const act = cardActivity(
      input({
        events: [event('dependency_wait', 2 * DAY, { parent: 't_old' }), event('claimed', MIN)],
        task: task({ started_at: s(MIN), status: 'running' })
      })
    )

    expect(act.waiting).toBeNull()
  })
})

describe('cardActivity — never invents a percentage', () => {
  it('reports child completion only when children exist', () => {
    const withKids = cardActivity(input({ task: task({ progress: { done: 2, total: 5 } }) }))
    const without = cardActivity(input({ task: task({ progress: null }) }))

    expect(withKids.childProgress).toEqual({ done: 2, total: 5 })
    expect(without.childProgress).toBeNull()
  })

  it('CONTROLE NEGATIVO: a zero-child rollup is not 0%', () => {
    const act = cardActivity(input({ task: task({ progress: { done: 0, total: 0 } }) }))

    expect(act.childProgress).toBeNull()
  })
})
