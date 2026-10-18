import type { PluginRestOptions } from '@hermes/plugin-sdk'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { $boardSlug, bindApi } from './api'
import { ApprovalPanel } from './approval-panel'

vi.mock('@/hermes', () => ({ setApiRequestProfile: vi.fn() }))

afterEach(cleanup)

it('one explicit gesture authorizes only the displayed content', async () => {
  let state = 'pending'
  const rest = vi.fn(async (path: string, options?: PluginRestOptions) => {
    if (options?.method === 'POST') {
      state = 'granted'
      return { ok: true }
    }
    return { approvals: [{
      request_id: 'ap_fixture', request_hash: 'fixture-content-hash', state,
      run_id: 12, profile_home: '/fixture/profile', decided_by: null,
      payload_json: JSON.stringify({ op: 'write_file', reasons: ['Instruction file'], targets: [{
        path_input: 'AGENTS.md', path_real: '/fixture/AGENTS.md', pre_sha256: 'old-hash',
        post_sha256: 'new-hash', post_blob: 'approved bytes', diff_unified: '-old\n+approved bytes'
      }] })
    }] }
  })
  const dispose = bindApi(async <T,>(path: string, options?: PluginRestOptions) => await rest(path, options) as T,
    { get: (_key, fallback) => fallback, set: vi.fn(), remove: vi.fn() }, () => vi.fn())
  $boardSlug.set('isolated-board')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  try {
    render(<QueryClientProvider client={client}><ApprovalPanel taskId="t_fixture" waiting /></QueryClientProvider>)
    await screen.findByText('/fixture/AGENTS.md')
    expect(rest.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Approve once' }))
    await screen.findByText('Approved. Waiting for the original worker and available capacity.')
    expect(rest.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
    expect(rest).toHaveBeenCalledWith('/tasks/t_fixture/approvals/ap_fixture/decision?board=isolated-board', {
      method: 'POST', body: { decision: 'granted', request_hash: 'fixture-content-hash' }
    })
    expect(screen.queryByRole('button', { name: 'Approve once' })).toBeNull()
  } finally {
    cleanup()
    client.clear()
    dispose()
  }
})

it('does not offer a decision while content is unavailable', async () => {
  const rest = vi.fn(async () => { throw new Error('403 Forbidden') })
  const dispose = bindApi(rest, { get: (_key, fallback) => fallback, set: vi.fn(), remove: vi.fn() }, () => vi.fn())
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  try {
    render(<QueryClientProvider client={client}><ApprovalPanel taskId="t_forbidden" waiting /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('403 Forbidden'))
    expect(screen.queryByRole('button', { name: 'Approve once' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDefined()
  } finally {
    cleanup()
    client.clear()
    dispose()
  }
})

/** Um approval ``granted`` com a projeção de diagnóstico anexada. */
const withDiagnostics = (diagnostics: Record<string, unknown> | null) => ({
  request_id: 'ap_diag', request_hash: 'diag-hash', state: 'granted', run_id: 7,
  profile_home: '/fixture/profile', decided_by: 'human', decided_at: 1_700_000_000,
  applied_at: null, diagnostics,
  payload_json: JSON.stringify({
    op: 'write_file', reasons: ['Instruction file'],
    targets: [{ path_input: 'AGENTS.md', path_real: '/fixture/AGENTS.md', pre_sha256: 'old',
                post_sha256: 'new', post_blob: 'bytes', diff_unified: '-old\n+bytes' }]
  })
})

it('names the wait reason, the next action, and never invents a resource cost', async () => {
  const rest = vi.fn(async () => ({ approvals: [withDiagnostics({
    phase: 'awaiting_admission', phase_label: 'Approved; waiting for a dispatch slot',
    reason: 'host_capacity', next_action: 'Free a running task on this host, or raise kanban.max_in_progress.',
    last_transition_at: 1_700_000_000, last_evidence_at: null, resource_cost: null,
    delivery_status: 'delivered', delivery_label: 'Transport acknowledged',
    delivery_attempts: 1, delivery_generation: 'gen-1'
  })] }))
  const dispose = bindApi(rest as never, { get: (_key, fallback) => fallback, set: vi.fn(), remove: vi.fn() }, () => vi.fn())
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  try {
    render(<QueryClientProvider client={client}><ApprovalPanel taskId="t_diag" waiting /></QueryClientProvider>)
    const list = await screen.findByLabelText('Wait diagnostics')
    expect(list.textContent).toContain('Approved; waiting for a dispatch slot')
    expect(list.textContent).toContain('raise kanban.max_in_progress')
    // Custo não é medido: a UI diz isso, em vez de mostrar um zero tranquilizador.
    expect(list.textContent).toContain('Unavailable (not measured)')
    expect(list.textContent).not.toMatch(/Resource cost[\s:]*0/)
    // Recibo é de transporte, nunca de leitura humana.
    expect(list.textContent).toContain('Transport acknowledged')
    expect(list.textContent).not.toContain('read')
    // Entrega saudável não oferece retry.
    expect(screen.queryByRole('button', { name: 'Retry notice' })).toBeNull()
  } finally {
    cleanup()
    client.clear()
    dispose()
  }
})

it('offers Retry notice only when the delivery budget is exhausted, and it decides nothing', async () => {
  let status = 'exhausted'
  const rest = vi.fn(async (path: string, options?: PluginRestOptions) => {
    if (options?.method === 'POST') {
      expect(path).toContain('/notice-retry')
      status = 'failed'
      return { ok: true }
    }
    return { approvals: [withDiagnostics({
      phase: 'awaiting_human', phase_label: 'Human decision pending',
      reason: 'human_decision_pending', next_action: 'Approve or deny this exact content on the card.',
      last_transition_at: 1_700_000_000, last_evidence_at: 1_700_000_500, resource_cost: null,
      delivery_status: status,
      delivery_label: status === 'exhausted' ? 'Delivery failed; budget exhausted' : 'Delivery failed',
      delivery_attempts: 3, delivery_generation: 'gen-1'
    })] }
  })
  const dispose = bindApi(rest as never, { get: (_key, fallback) => fallback, set: vi.fn(), remove: vi.fn() }, () => vi.fn())
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  try {
    render(<QueryClientProvider client={client}><ApprovalPanel taskId="t_exhausted" waiting /></QueryClientProvider>)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry notice' }))
    await waitFor(() => expect(rest.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1))
    // O retry é do AVISO: nenhuma decisão foi enviada junto.
    const posted = rest.mock.calls.filter(([, o]) => o?.method === 'POST')
    expect(posted.every(([p]) => !String(p).includes('/decision'))).toBe(true)
    expect(posted.every(([, o]) => (o?.body as undefined | { decision?: string })?.decision === undefined)).toBe(true)
  } finally {
    cleanup()
    client.clear()
    dispose()
  }
})

it('stays silent about diagnostics when the backend does not send them', async () => {
  // Servidor anterior a t_78aaa333: omitir é honesto, inventar "OK" não seria.
  const rest = vi.fn(async () => ({ approvals: [withDiagnostics(null)] }))
  const dispose = bindApi(rest as never, { get: (_key, fallback) => fallback, set: vi.fn(), remove: vi.fn() }, () => vi.fn())
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  try {
    render(<QueryClientProvider client={client}><ApprovalPanel taskId="t_old" waiting /></QueryClientProvider>)
    await screen.findByText('/fixture/AGENTS.md')
    expect(screen.queryByLabelText('Wait diagnostics')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Retry notice' })).toBeNull()
  } finally {
    cleanup()
    client.clear()
    dispose()
  }
})
