import { Button, useMutation, useQuery, useQueryClient, useValue } from '@hermes/plugin-sdk'


import { $boardSlug, decideApproval, fetchApprovals, taskKey } from './api'
import type { KanbanApproval } from './types'

interface Target {
  path_input: string
  path_real: string
  pre_sha256: string | null
  post_sha256: string
  post_blob: string
  diff_unified: string
}

interface Payload {
  op: string
  reasons: string[]
  targets: Target[]
}

interface ApprovalPanelProps {
  taskId: string
  waiting: boolean
}

function ApprovalItem({ approval, taskId }: { approval: KanbanApproval; taskId: string }) {

  const client = useQueryClient()
  const slug = useValue($boardSlug)
  const mutation = useMutation({
    mutationFn: (decision: 'granted' | 'denied' | 'cancelled') => decideApproval(taskId, approval, decision),
    onSettled: () => {

      void client.invalidateQueries({ queryKey: ['kanban', 'approvals', slug, taskId] })
      void client.invalidateQueries({ queryKey: taskKey(slug, taskId) })
      void client.invalidateQueries({ queryKey: ['kanban', 'board'] })
    }
  })
  let payload: Payload
  try {
    payload = JSON.parse(approval.payload_json) as Payload
    if (!Array.isArray(payload.targets) || !Array.isArray(payload.reasons)) throw new Error('Invalid payload')
  } catch {
    return <p role="alert">Approval content could not be loaded. No decision is available.</p>
  }
  const pending = approval.state === 'pending'
  return (
    <article className="flex flex-col gap-2 rounded border border-(--ui-border) p-3">
      <p className="font-medium">{payload.op} · {approval.state}</p>
      <p className="break-all text-xs">Run {approval.run_id} · {approval.profile_home}</p>
      <p className="break-all text-xs">Request: {approval.request_id}</p>
      <p className="break-all font-mono text-xs">SHA-256: {approval.request_hash}</p>
      <p className="text-xs">{payload.reasons.join(' · ')}</p>
      {payload.targets.map(target => (
        <details key={target.path_input} open>
          <summary className="break-all">{target.path_real}</summary>
          <p className="break-all font-mono text-xs">Before: {target.pre_sha256 ?? 'New file'}</p>
          <p className="break-all font-mono text-xs">After: {target.post_sha256}</p>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{target.diff_unified}</pre>
          <details>
            <summary>Full proposed content</summary>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{target.post_blob}</pre>
          </details>
        </details>
      ))}
      {approval.decided_by && <p className="text-xs">Decision by {approval.decided_by} · {approval.decided_at ? new Date(approval.decided_at * 1000).toLocaleString() : ''}</p>}
      {approval.state === 'granted' && <p>Approved. Waiting for the original worker and available capacity.</p>}
      {approval.state === 'consumed' && <p>{approval.applied_at ? 'Written and verified.' : 'Consumed. Write receipt pending; do not retry.'}</p>}
      {mutation.error && <p role="alert">Decision failed: {String(mutation.error)}</p>}
      {pending && (
        <div className="flex flex-wrap gap-2">
          <Button disabled={mutation.isPending} onClick={() => mutation.mutate('granted')} size="xs">Approve once</Button>
          <Button disabled={mutation.isPending} onClick={() => mutation.mutate('denied')} size="xs" variant="outline">Deny</Button>
          <Button disabled={mutation.isPending} onClick={() => mutation.mutate('cancelled')} size="xs" variant="outline">Cancel request</Button>
        </div>
      )}
      {pending && <p className="text-xs">Approve only this exact content once. Changed files invalidate approval. This does not approve the task or any future command.</p>}
    </article>
  )
}

export function ApprovalPanel({ taskId, waiting }: ApprovalPanelProps) {
  const slug = useValue($boardSlug)
  const query = useQuery({
    queryKey: ['kanban', 'approvals', slug, taskId],
    queryFn: () => fetchApprovals(taskId),
    refetchInterval: waiting ? 2000 : 8000
  })
  if (query.isPending) return <p role="status">Loading file approvals…</p>
  if (query.error) return (
    <div role="alert">
      <p>File approvals unavailable. Authentication or permission may be required: {String(query.error)}</p>
      <Button onClick={() => void query.refetch()} size="xs" variant="outline">Retry</Button>
    </div>
  )
  if (!query.data?.approvals.length) return waiting ? <p>No approval request is available. Refresh the task before taking action.</p> : null
  return (
    <section aria-label="File approvals" className="flex flex-col gap-3">
      <h3 className="font-semibold">File approvals</h3>
      {query.data.approvals.map(approval => <ApprovalItem key={approval.request_id} approval={approval} taskId={taskId} />)}
    </section>
  )
}
