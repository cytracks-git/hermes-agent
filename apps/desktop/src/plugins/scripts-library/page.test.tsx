/**
 * Scripts library — desktop plugin contract and page behaviour.
 *
 * Os testes que pesam aqui são os negativos: a página promete acesso SOMENTE
 * LEITURA e promete não inventar estágio que não mediu. Um teste que só
 * renderiza o caso feliz não mede nenhuma das duas coisas.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Test harness supplies the host's locale registration, as plugin loading does.
// eslint-disable-next-line no-restricted-imports
import { registerPluginLocales } from '@/i18n/plugin-i18n'

import type * as ScriptsApi from './api'
import { SCRIPTS_LOCALES } from './i18n'
import { ScriptsLibraryPage } from './page'
import plugin from './plugin'

const SUMMARY: ScriptsApi.ScriptSummary = {
  category: 'general',
  id: 'abc123',
  interpreter: 'bash',
  language: 'shell',
  modified_at: 1_790_000_000,
  name: 'rotate-logs.sh',
  path: '/home/u/.hermes/scripts/rotate-logs.sh',
  purpose: 'Rotate gateway logs.',
  relpath: 'scripts/rotate-logs.sh',
  root_id: 'hermes-home',
  root_label: 'Hermes home',
  run_command: '/home/u/.hermes/scripts/rotate-logs.sh',
  size_bytes: 2048,
  vcs_state: 'committed'
}

const DETAIL: ScriptsApi.ScriptDetail = {
  ...SUMMARY,
  doc: 'Rotate gateway logs.',
  lifecycle: {
    measured_at: 1_790_000_100,
    stages: [
      { evidence: 'file is readable on disk', stage: 'prepared', status: 'yes' },
      { evidence: 'tracked and clean at 1a2b3c4', stage: 'committed', status: 'yes' },
      { evidence: 'no pull-request merge commit on the path to the remote', stage: 'reviewed', status: 'unknown' },
      { evidence: 'commit is not reachable from the tracked remote branch', stage: 'published', status: 'no' }
    ]
  },
  sections: { usage: 'rotate-logs.sh --keep 2' },
  vcs: {
    available: true,
    commit: { author: 'Ana', date: '2026-09-01', sha: '1a2b3c4'.padEnd(40, '0'), short_sha: '1a2b3c4', subject: 'add rotation' },
    history: [{ author: 'Ana', date: '2026-09-01', sha: '1a2b3c4'.padEnd(40, '0'), short_sha: '1a2b3c4', subject: 'add rotation' }],
    reason: '',
    relpath: 'scripts/rotate-logs.sh',
    remote_ref: 'origin/main',
    remote_url: 'git@github.com:owner/repo.git',
    repo_root: '/home/u/repo',
    review_merge_commit: '',
    review_pr: '',
    review_reason: 'no pull-request merge commit on the path to the remote',
    review_state: 'unknown',
    state: 'committed',
    web_url: ''
  }
}

const CATALOG: ScriptsApi.Catalog = {
  errors: [],
  languages: ['shell'],
  matched: 1,
  roots: [
    { error: '', exists: true, id: 'hermes-home', label: 'Hermes home', origin: 'hermes_home', path: '/home/u/.hermes/scripts' }
  ],
  scanned_at: 1_790_000_100,
  scripts: [SUMMARY],
  total: 1,
  truncated: false
}

const fetchCatalog = vi.fn(async () => CATALOG)
const fetchDetail = vi.fn(async () => DETAIL)

vi.mock('./api', async importOriginal => ({
  ...(await importOriginal<typeof ScriptsApi>()),
  fetchCatalog: (...args: unknown[]) => fetchCatalog(...(args as [])),
  fetchDetail: (...args: unknown[]) => fetchDetail(...(args as [])),
  fetchSource: vi.fn(async () => ({
    bytes: 10,
    content: '#!/bin/sh\n',
    id: 'abc123',
    language: 'shell',
    name: 'rotate-logs.sh',
    truncated: false
  }))
}))

let disposeLocales: () => void = () => undefined

beforeEach(() => {
  disposeLocales = registerPluginLocales('scripts-library', SCRIPTS_LOCALES)
})

afterEach(() => {
  cleanup()
  disposeLocales()
  vi.clearAllMocks()
})

const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ScriptsLibraryPage />
    </QueryClientProvider>
  )

describe('scripts library page', () => {
  it('lists a script by name so the operator can find it', async () => {
    mount()

    expect(await screen.findByText('rotate-logs.sh')).toBeTruthy()
  })

  it('shows the run command as copyable text, never as a run button', async () => {
    // NEGATIVE CONTROL — execução. O card pediu acesso de leitura; um botão
    // "Run" aqui seria escopo que ninguém autorizou.
    mount()
    ;(await screen.findByText('rotate-logs.sh')).click()

    expect(await screen.findByText('/home/u/.hermes/scripts/rotate-logs.sh')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^run$/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /execute/i })).toBeNull()
  })

  it('renders an unmeasured lifecycle stage as "Not measured", not as a pass', async () => {
    // NEGATIVE CONTROL — verdade. "reviewed: unknown" tem de chegar ao olho do
    // operador como não medido, com o motivo, nunca some nem vira verde.
    mount()
    ;(await screen.findByText('rotate-logs.sh')).click()

    expect(await screen.findByText('Reviewed')).toBeTruthy()
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0)
    expect(screen.getByText(/no pull-request merge commit/)).toBeTruthy()
  })

  it('shows every lifecycle stage with its evidence', async () => {
    mount()
    ;(await screen.findByText('rotate-logs.sh')).click()

    for (const label of ['On disk', 'Committed', 'Reviewed', 'Published']) {
      expect(await screen.findByText(label)).toBeTruthy()
    }

    expect(screen.getByText('tracked and clean at 1a2b3c4')).toBeTruthy()
  })

  it('says a script has no documentation instead of inventing a purpose', async () => {
    // NEGATIVE CONTROL: documentação ausente não pode virar texto plausível.
    fetchCatalog.mockResolvedValueOnce({ ...CATALOG, scripts: [{ ...SUMMARY, purpose: '' }] })
    fetchDetail.mockResolvedValueOnce({ ...DETAIL, doc: '', purpose: '', sections: {} })
    mount()
    ;(await screen.findByText('rotate-logs.sh')).click()

    expect(await screen.findByText('This script has no documentation yet.')).toBeTruthy()
  })

  it('names a missing configured location rather than showing a bare empty list', async () => {
    fetchCatalog.mockResolvedValueOnce({
      ...CATALOG,
      matched: 0,
      roots: [
        { error: 'no such directory', exists: false, id: 'team', label: 'Team scripts', origin: 'config', path: '/gone' }
      ],
      scripts: [],
      total: 0
    })
    mount()

    expect(await screen.findByText(/Configured location not found: Team scripts/)).toBeTruthy()
  })

  it('distinguishes "no scripts at all" from "nothing matches the search"', async () => {
    fetchCatalog.mockResolvedValueOnce({ ...CATALOG, matched: 0, scripts: [], total: 0 })
    mount()

    expect(await screen.findByText('No scripts found')).toBeTruthy()
  })

  it('surfaces a failed read as an error with a retry, not as an empty library', async () => {
    // NEGATIVE CONTROL: falha silenciosa que parece "biblioteca vazia" faria o
    // operador concluir que não há scripts.
    fetchCatalog.mockRejectedValueOnce(new Error('backend down'))
    mount()

    expect(await screen.findByText('Could not read the library')).toBeTruthy()
    // A falha tem de dizer que NÃO conseguiu ler — "vazia" seria outra conclusão.
    expect(screen.getByText(/could not be read/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})

describe('scripts library plugin contract', () => {
  it('contributes a page, a sidebar entry and a palette command', () => {
    const contributions: Array<{ area: string; id: string }> = []

    const ctx = {
      i18n: { register: vi.fn(), t: (key: string) => key },
      onDispose: vi.fn(),
      registerMany: (items: Array<{ area: string; id: string }>) => {
        contributions.push(...items)

        return () => undefined
      },
      rest: vi.fn()
    }

    plugin.register(ctx as never)

    expect(contributions.map(c => c.id).sort()).toEqual(['nav', 'open', 'page'])
  })

  it('ships off by default so it registers nothing until the user opts in', () => {
    expect(plugin.defaultEnabled).toBe(false)
  })

  it('binds the REST door and hands the host a disposer for it', () => {
    // O disposer é o que impede o plugin desabilitado de continuar falando com
    // o backend; sem ele, "desligar" seria só cosmético.
    const onDispose = vi.fn()

    const ctx = {
      i18n: { register: vi.fn(), t: (key: string) => key },
      onDispose,
      registerMany: () => () => undefined,
      rest: vi.fn()
    }

    plugin.register(ctx as never)

    expect(onDispose).toHaveBeenCalledTimes(1)
    expect(typeof onDispose.mock.calls[0][0]).toBe('function')
  })
})
