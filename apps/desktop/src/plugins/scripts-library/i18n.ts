/**
 * Scripts library — i18n bundle, registered under the plugin id via
 * ctx.i18n.register (never a core en.ts edit), same shape as kanban/i18n.ts.
 *
 * Every string here is UI text the administrator reads, so it is written in
 * English; the comments explaining WHY are in pt-BR per the house rule.
 */

import { type PluginLocaleBundles, type PluginTranslate, usePluginI18n } from '@hermes/plugin-sdk'
import { useMemo } from 'react'

type ScriptsMessages = {
  nav: string
  title: string
  openCommand: string
  subtitle: string
  search: string
  searchPlaceholder: string
  allLanguages: string
  allRoots: string
  matched: (shown: number, total: number) => string
  empty: string
  emptyHint: string
  noMatch: string
  noMatchHint: string
  loading: string
  failed: string
  failedHint: string
  retry: string
  rootsMissing: (labels: string) => string
  scanErrors: (n: number) => string
  truncated: string

  // Detail pane
  noSelection: string
  noSelectionHint: string
  purposeMissing: string
  run: string
  copy: string
  copied: string
  reveal: string
  openOnGithub: string
  source: string
  sourceTruncated: string
  sourceUnavailable: string

  // Documentation sections
  sections: Record<
    | 'dependencies'
    | 'environment'
    | 'exitCodes'
    | 'inputs'
    | 'limits'
    | 'notes'
    | 'outputs'
    | 'permissions'
    | 'tests'
    | 'usage',
    string
  >
  sectionMissing: (name: string) => string

  // Lifecycle
  lifecycle: string
  stage: Record<'committed' | 'prepared' | 'published' | 'reviewed', { label: string; help: string }>
  status: Record<'diverged' | 'no' | 'unknown' | 'yes', string>
  notMeasured: string
  version: string
  noVersion: string
  history: string
  noHistory: string
  language: string
  size: string
  modified: string
  path: string
  root: string
}

const en: ScriptsMessages = {
  nav: 'Scripts',
  title: 'Scripts',
  openCommand: 'Scripts: Open library',
  subtitle: 'Read-only library of the scripts on this machine',
  search: 'Search',
  searchPlaceholder: 'Search name, purpose or path…',
  allLanguages: 'All languages',
  allRoots: 'All locations',
  matched: (shown: number, total: number) => `${shown} of ${total}`,
  empty: 'No scripts found',
  emptyHint: 'Add a scripts directory under scripts_library.roots in config.yaml, or put scripts in the Hermes home.',
  noMatch: 'Nothing matches this search',
  noMatchHint: 'Try a shorter term, or clear the language and location filters.',
  loading: 'Reading the library…',
  failed: 'Could not read the library',
  failedHint: 'The backend did not answer. The library is not empty — it could not be read.',
  retry: 'Try again',
  rootsMissing: (labels: string) => `Configured location not found: ${labels}`,
  scanErrors: (n: number) => `${n} location could not be read in full`,
  truncated: 'Too many files — this list is partial.',

  noSelection: 'Select a script',
  noSelectionHint: 'Its documentation, run command and version history appear here.',
  purposeMissing: 'This script has no documentation yet.',
  run: 'Run command',
  copy: 'Copy',
  copied: 'Copied',
  reveal: 'Show in file manager',
  openOnGithub: 'Open on GitHub',
  source: 'Source',
  sourceTruncated: 'Source shown in part — open the file for the rest.',
  sourceUnavailable: 'Source cannot be shown for this file.',

  sections: {
    dependencies: 'Dependencies',
    environment: 'Environment',
    exitCodes: 'Exit codes',
    inputs: 'Inputs',
    limits: 'Limits',
    notes: 'Notes',
    outputs: 'Outputs',
    permissions: 'Permissions',
    tests: 'Tests',
    usage: 'Usage'
  },
  sectionMissing: (name: string) => `${name}: not documented`,

  lifecycle: 'State',
  stage: {
    committed: { help: 'The file is tracked and matches its last commit.', label: 'Committed' },
    prepared: { help: 'The file exists on disk and can be read.', label: 'On disk' },
    published: { help: 'The commit is reachable from the tracked remote branch.', label: 'Published' },
    reviewed: { help: 'A pull-request merge carries this commit to the remote.', label: 'Reviewed' }
  },
  status: { diverged: 'Edited', no: 'No', unknown: 'Not measured', yes: 'Yes' },
  notMeasured: 'Not measured',
  version: 'Version',
  noVersion: 'No commit yet — this script exists only on this machine.',
  history: 'History',
  noHistory: 'No commit history.',
  language: 'Language',
  size: 'Size',
  modified: 'Modified',
  path: 'Path',
  root: 'Location'
}

/** Registered via ctx.i18n.register at plugin load (disposer tracked). */
export const SCRIPTS_LOCALES: PluginLocaleBundles = { en }

type Bound<T> = {
  [K in keyof T]: T[K] extends (...args: infer A) => string
    ? (...args: A) => string
    : T[K] extends object
      ? Bound<T[K]>
      : string
}

function bind<T extends object>(t: PluginTranslate, template: T, prefix = ''): Bound<T> {
  const out = {} as Record<string, unknown>

  for (const [key, value] of Object.entries(template)) {
    const path = prefix ? `${prefix}.${key}` : key
    out[key] =
      typeof value === 'function'
        ? (...args: unknown[]) => t(path, ...args)
        : value && typeof value === 'object'
          ? bind(t, value as object, path)
          : t(path)
  }

  return out as Bound<T>
}

export type ScriptsText = Bound<ScriptsMessages>

/** The scripts-library strings for the active locale. */
export function useScriptsText(): ScriptsText {
  const t = usePluginI18n('scripts-library')

  return useMemo(() => bind(t, en), [t])
}

/** Section keys the backend may return, mapped to their heading. Unknown keys
 *  are not invented into headings — they simply do not render. */
export const SECTION_ORDER = [
  'usage',
  'inputs',
  'outputs',
  'dependencies',
  'environment',
  'permissions',
  'exitCodes',
  'limits',
  'tests',
  'notes'
] as const

/** Backend section ids are snake_case; the message shape is camelCase. */
export const SECTION_API_KEY: Record<(typeof SECTION_ORDER)[number], string> = {
  dependencies: 'dependencies',
  environment: 'environment',
  exitCodes: 'exit_codes',
  inputs: 'inputs',
  limits: 'limits',
  notes: 'notes',
  outputs: 'outputs',
  permissions: 'permissions',
  tests: 'tests',
  usage: 'usage'
}
