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
