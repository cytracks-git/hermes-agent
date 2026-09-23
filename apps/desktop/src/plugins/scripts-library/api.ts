/**
 * Scripts library — typed view of the plugin's own REST namespace.
 *
 * ``bindApi`` receives ``ctx.rest`` at register time exactly like
 * ``plugins/kanban/api.ts`` does: every call is namespace-scoped to
 * ``/api/plugins/scripts-library`` by construction, so this module cannot
 * address a core route or another plugin even by mistake.
 */

import type { PluginRestOptions } from '@hermes/plugin-sdk'

export type VcsState = 'committed' | 'modified' | 'published' | 'unknown' | 'untracked'
export type StageStatus = 'no' | 'unknown' | 'yes'

export interface ScriptSummary {
  category: string
  id: string
  interpreter: string
  language: string
  modified_at: number
  name: string
  path: string
  purpose: string
  relpath: string
  root_id: string
  root_label: string
  run_command: string
  size_bytes: number
  vcs_state: VcsState
}

export interface ScriptRootInfo {
  error: string
  exists: boolean
  id: string
  label: string
  origin: string
  path: string
}

export interface Catalog {
  errors: string[]
  languages: string[]
  matched: number
  roots: ScriptRootInfo[]
  scanned_at: number
  scripts: ScriptSummary[]
  total: number
  truncated: boolean
}

export interface CommitInfo {
  author: string
  date: string
  sha: string
  short_sha: string
  subject: string
}

export interface LifecycleStage {
  /** Why the status says what it says — never empty, so the UI never shows a
   *  verdict the operator cannot check. */
  evidence: string
  stage: 'committed' | 'prepared' | 'published' | 'reviewed'
  status: StageStatus
}

export interface ScriptDetail extends ScriptSummary {
  doc: string
  lifecycle: { measured_at: number; stages: LifecycleStage[] }
  sections: Record<string, string>
  vcs: {
    available: boolean
    commit: CommitInfo | null
    history: CommitInfo[]
    reason: string
    relpath: string
    remote_ref: string
    remote_url: string
    repo_root: string
    review_merge_commit: string
    review_pr: string
    review_reason: string
    review_state: string
    state: VcsState
    web_url: string
  }
}

export interface ScriptSource {
  bytes: number
  content: string
  id: string
  language: string
  name: string
  truncated: boolean
}

type Rest = <T>(path: string, opts?: PluginRestOptions) => Promise<T>

let rest: null | Rest = null

/** Bind the plugin's REST door; returns the disposer the host tracks. */
export function bindApi(restFn: Rest): () => void {
  rest = restFn

  return () => {
    rest = null
  }
}

function call<T>(path: string): Promise<T> {
  if (!rest) {
    // Unbound means the plugin is disabled or mid-unload; a rejected promise
    // surfaces as the page's error state rather than a silent empty list.
    return Promise.reject(new Error('scripts-library: API not bound'))
  }

  return rest<T>(path)
}

function query(params: Record<string, string>): string {
  const search = new URLSearchParams()

  for (const [key, value] of Object.entries(params)) {
    if (value) {
      search.set(key, value)
    }
  }

  const encoded = search.toString()

  return encoded ? `?${encoded}` : ''
}

export const catalogKey = (search: string, language: string, root: string) => [
  'scripts-library',
  'catalog',
  search,
  language,
  root
]
export const detailKey = (id: string) => ['scripts-library', 'detail', id]
export const sourceKey = (id: string) => ['scripts-library', 'source', id]

export const fetchCatalog = (search: string, language: string, root: string) =>
  call<Catalog>(`/catalog${query({ language, q: search, root })}`)

export const fetchDetail = (id: string) => call<ScriptDetail>(`/scripts/${encodeURIComponent(id)}`)

export const fetchSource = (id: string) => call<ScriptSource>(`/scripts/${encodeURIComponent(id)}/source`)
