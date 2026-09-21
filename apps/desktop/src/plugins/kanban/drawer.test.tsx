import type { PluginRestOptions } from '@hermes/plugin-sdk'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Test harness supplies the host's locale registration, as plugin loading does.
// eslint-disable-next-line no-restricted-imports
import { registerPluginLocales } from '@/i18n/plugin-i18n'

import type * as activityModule from './activity'
import { bindApi, taskKey } from './api'
import { TaskDrawer } from './drawer'
import { en, KANBAN_LOCALES } from './i18n'
import type { KanbanTaskDetail } from './types'

vi.mock('@/hermes', () => ({ setApiRequestProfile: vi.fn() }))

// Alavanca para exercitar o caminho de ERRO do painel de progresso. Nao da para
// provar esse estado so com dado ruim: o calculo e deliberadamente tolerante
// (payload ilegivel vira `{}`), entao a unica forma honesta de ver a tela de
// falha e fazer a leitura lancar de verdade, como faria um defeito futuro.
let mockActivityThrows = false

vi.mock('./activity', async () => {
  const actual = await vi.importActual<typeof activityModule>('./activity')

  return {
    ...actual,
    cardActivity: (input: Parameters<typeof actual.cardActivity>[0]) => {
      if (mockActivityThrows) {
        throw new Error('unreadable activity')
      }

      return actual.cardActivity(input)
    }
  }
})

const legacyDetail: Omit<KanbanTaskDetail, 'attachments'> = {
  task: { id: 't_example', title: 'Example task', body: 'Keep this description readable.', status: 'todo' },
  comments: [{ id: 1, author: 'test', body: 'Keep this comment readable.', created_at: 0 }],
  events: [],
  links: { parents: [], children: [] },
  runs: []
}

let detail: object
let client: QueryClient
let disposeApi: () => void
let disposeLocales: () => void

const rest = vi.fn(async (path: string, options?: PluginRestOptions): Promise<unknown> => {
  if (path === '/tasks/t_example/attachments' && options?.method === 'POST') {
    detail = { ...legacyDetail, attachments: [{ id: 1, filename: options.upload?.filename }] }

    return { ok: true }
  }

  if (path === '/tasks/t_example') {
    return detail
  }

  if (path.startsWith('/tasks/t_example/log?')) {
    return { exists: false, content: '', size_bytes: 0, truncated: false }
  }

  if (path === '/profiles') {
    return { profiles: [] }
  }

  if (path === '/orchestration') {
    return { default_assignee: '' }
  }

  throw new Error(`Unexpected REST request: ${path}`)
})

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  disposeLocales = registerPluginLocales('kanban', KANBAN_LOCALES)
  disposeApi = bindApi(
    async <T,>(path: string, options?: PluginRestOptions) => (await rest(path, options)) as T,
    { get: (_key, fallback) => fallback, set: vi.fn(), remove: vi.fn() },
    () => vi.fn()
  )
})

afterEach(() => {
  mockActivityThrows = false
  cleanup()
  client.clear()
  disposeApi()
  disposeLocales()
  vi.clearAllMocks()
})

function openDrawer() {
  return render(
    <QueryClientProvider client={client}>
      <TaskDrawer columns={['todo', 'ready', 'done']} id="t_example" onClose={vi.fn()} onOpen={vi.fn()} />
    </QueryClientProvider>
  )
}

describe('task attachment compatibility', () => {
  it.each([{}, { attachments: null }])(
    'keeps older task details usable without attachment controls (%j)',
    async extra => {
      detail = { ...legacyDetail, ...extra }
      openDrawer()

      expect(await screen.findByRole('heading', { name: legacyDetail.task.title })).toBeTruthy()
      expect(screen.getByText(legacyDetail.task.body!)).toBeTruthy()
      expect(screen.getByText(legacyDetail.comments[0].body)).toBeTruthy()
      expect(screen.queryByRole('button', { name: en.uploadAttachment })).toBeNull()
      expect(screen.queryByText(en.noAttachments)).toBeNull()

      // A later backend response restores the capability without remounting.
      detail = { ...legacyDetail, attachments: [] }
      await act(() => client.invalidateQueries({ queryKey: taskKey('', legacyDetail.task.id) }))
      expect(await screen.findByRole('button', { name: en.uploadAttachment })).toBeTruthy()
      expect(screen.getByText(en.noAttachments)).toBeTruthy()
    }
  )

  it('keeps upload and attachment rendering working for a supported empty list', async () => {
    detail = { ...legacyDetail, attachments: [] }
    const { container } = openDrawer()
    const upload = await screen.findByRole('button', { name: en.uploadAttachment })
    expect(screen.getByText(en.noAttachments)).toBeTruthy()

    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    const click = vi.spyOn(input, 'click')
    fireEvent.click(upload)
    expect(click).toHaveBeenCalledOnce()

    const file = new File(['example'], 'example.txt', { type: 'text/plain' })
    const bytes = new ArrayBuffer(7)
    // jsdom's File lacks arrayBuffer; the upload still uses the real REST adapter.
    Object.defineProperty(file, 'arrayBuffer', { value: async () => bytes })
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() =>
      expect(rest).toHaveBeenCalledWith('/tasks/t_example/attachments', {
        method: 'POST',
        upload: { filename: file.name, contentType: file.type, bytes }
      })
    )
    expect(await screen.findByText(file.name)).toBeTruthy()
    expect(screen.queryByText(en.noAttachments)).toBeNull()
  })
})

/**
 * O painel de progresso montado de verdade, pelo drawer, com o i18n real.
 *
 * `activity.test.ts` prova o CALCULO; estes provam que o calculo chega a TELA
 * — que o painel aparece, que idade e tentativa sao lidas como duas coisas
 * diferentes, e que uma falha de leitura nao leva o drawer junto.
 */
describe('progress panel', () => {
  const HOUR = 3600
  const now = () => Math.floor(Date.now() / 1000)

  it('separates card age from the current attempt', async () => {
    // Exatamente o caso que foi lido como contador congelado: card velho,
    // tentativa nova. Um numero so nao consegue dizer as duas coisas.
    detail = {
      ...legacyDetail,
      attachments: [],
      task: { ...legacyDetail.task, assignee: 'executor', created_at: now() - 4 * HOUR, status: 'running' },
      runs: [{ id: 1, started_at: now() - 3 * 60, status: 'running' }]
    }
    openDrawer()

    expect(await screen.findByText(en.progress)).toBeTruthy()
    expect(screen.getByText(en.cardAge)).toBeTruthy()
    expect(screen.getByText(en.attempt)).toBeTruthy()
    // 4h de idade e 3m de tentativa, lado a lado e distinguiveis.
    expect(screen.getByText('4h')).toBeTruthy()
    expect(screen.getByText('3m')).toBeTruthy()
  })

  it('says progress is UNKNOWN when nothing was reported, never "stalled"', async () => {
    detail = { ...legacyDetail, attachments: [], events: [], runs: [] }
    openDrawer()

    expect(await screen.findByText(en.progressUnknown)).toBeTruthy()
  })

  it('shows a block reason verbatim with the next action', async () => {
    const reason = 'Need the staging credentials before the migration can run.'
    detail = {
      ...legacyDetail,
      attachments: [],
      task: { ...legacyDetail.task, status: 'blocked' },
      events: [
        {
          id: 1,
          kind: 'blocked',
          created_at: now() - 60,
          payload: JSON.stringify({ kind: 'needs_input', reason })
        }
      ]
    }
    openDrawer()

    // O motivo aparece no painel de progresso, como ultimo sinal E como a
    // espera atual — duas leituras do mesmo fato — alem do feed de atividade
    // que ja existia. Contar nos seria fragil; o que importa e que o texto
    // chegue LITERAL e acompanhado da espera e da proxima acao.
    const shown = await screen.findAllByText(reason)
    expect(shown.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(en.waitInput)).toBeTruthy()
    expect(screen.getByText(en.actAnswer)).toBeTruthy()
  })

  it('keeps the drawer usable when the activity payload is malformed', async () => {
    // Controle negativo do isolamento: um payload que NAO e JSON valido nao
    // pode apagar descricao, comentarios e acoes de recuperacao — a tela que o
    // operador usa justamente para consertar o card quebrado.
    detail = {
      ...legacyDetail,
      attachments: [],
      task: { ...legacyDetail.task, status: 'blocked' },
      events: [{ id: 1, kind: 'blocked', created_at: now(), payload: '{not json at all' }]
    }
    openDrawer()

    expect(await screen.findByRole('heading', { name: legacyDetail.task.title })).toBeTruthy()
    expect(screen.getByText(legacyDetail.task.body!)).toBeTruthy()
    expect(screen.getByText(legacyDetail.comments[0].body)).toBeTruthy()
    // E o painel continua de pe, dizendo o que sabe sem inventar o resto.
    expect(screen.getByText(en.progress)).toBeTruthy()
    // CONTROLE POSITIVO do caso abaixo: dado ruim NAO e falha de leitura, entao
    // o aviso de erro nao pode aparecer aqui. Sem esta linha, um painel que
    // gritasse "erro" em toda tela passaria nos dois testes.
    expect(screen.queryByText(en.activityUnavailable)).toBeNull()
  })

  it('says the panel FAILED instead of vanishing when the reading throws', async () => {
    // Sumir calado e indistinguivel de "nada a mostrar". Sao duas afirmacoes
    // diferentes e o operador precisa saber qual das duas esta vendo.
    mockActivityThrows = true
    detail = { ...legacyDetail, attachments: [] }
    openDrawer()

    expect(await screen.findByText(en.activityUnavailable)).toBeTruthy()
    // O resto do drawer sobrevive — a falha e do painel, nao da tela.
    expect(screen.getByRole('heading', { name: legacyDetail.task.title })).toBeTruthy()
    expect(screen.getByText(legacyDetail.comments[0].body)).toBeTruthy()
    // E NAO mente dizendo que nao ha progresso: isso seria uma leitura, e a
    // leitura foi justamente o que falhou.
    expect(screen.queryByText(en.progressUnknown)).toBeNull()
  })
})
