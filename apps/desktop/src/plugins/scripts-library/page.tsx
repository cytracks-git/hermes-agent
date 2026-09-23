/**
 * Scripts library page — master list of scripts beside a read-only inspector.
 *
 * Composed from the core panel toolkit (PanelList/PanelDetail/PanelMeta/…) so it
 * looks like Scheduled jobs and Kanban rather than a second design language.
 *
 * Duas decisões de superfície que valem registro:
 *
 * 1. Nada aqui executa script. Não há botão de run e a API não tem rota de
 *    escrita; o que existe é "copiar o comando", que deixa a execução com o
 *    operador, onde o card a colocou.
 * 2. Estágio sem medição aparece como "Not measured" com o motivo ao lado,
 *    nunca como ausência silenciosa. Um selo verde que o operador não pode
 *    conferir é pior que nenhum selo.
 */

import {
  Button,
  cn,
  Codicon,
  CopyButton,
  PanelBlock,
  PanelBody,
  PanelDetail,
  PanelEmpty,
  PanelList,
  PanelListRow,
  PanelMeta,
  type PanelMetaRow,
  PanelPill,
  type PanelPillTone,
  PanelSectionLabel,
  Tip,
  useQuery
} from '@hermes/plugin-sdk'
import { useState } from 'react'

import {
  catalogKey,
  detailKey,
  fetchCatalog,
  fetchDetail,
  fetchSource,
  type LifecycleStage,
  type ScriptDetail,
  type ScriptSummary,
  sourceKey,
  type StageStatus,
  type VcsState
} from './api'
import { type ScriptsText, SECTION_API_KEY, SECTION_ORDER, useScriptsText } from './i18n'

const STATE_TONE: Record<VcsState, PanelPillTone> = {
  committed: 'good',
  modified: 'warn',
  published: 'good',
  unknown: 'muted',
  untracked: 'warn'
}

const STAGE_TONE: Record<StageStatus, PanelPillTone> = {
  // `diverged` is warn, never good: the commit exists but does not describe the
  // bytes on disk, which is exactly the claim the card forbids.
  diverged: 'warn',
  no: 'bad',
  unknown: 'muted',
  yes: 'good'
}

const LANGUAGE_ICON: Record<string, string> = {
  javascript: 'symbol-method',
  powershell: 'terminal-powershell',
  python: 'symbol-namespace',
  ruby: 'ruby',
  shell: 'terminal',
  typescript: 'symbol-method'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(epochSeconds: number): string {
  if (!epochSeconds) {
    return '—'
  }

  return new Date(epochSeconds * 1000).toLocaleString()
}

/** One lifecycle stage as a row: verdict AND the evidence behind it, side by
 *  side, so the operator never has to take the badge on faith. */
function StageRow({ k, stage }: { k: ScriptsText; stage: LifecycleStage }) {
  const copy = k.stage[stage.stage]

  return (
    <div className="flex items-start gap-2 py-1">
      <div className="w-20 shrink-0">
        <PanelPill tone={STAGE_TONE[stage.status]}>{k.status[stage.status]}</PanelPill>
      </div>
      <div className="min-w-0">
        <Tip label={copy.help}>
          <span className="text-[0.72rem] font-medium text-foreground/85">{copy.label}</span>
        </Tip>
        <p className="text-[0.66rem] leading-relaxed text-muted-foreground/70">{stage.evidence}</p>
      </div>
    </div>
  )
}

function DocumentationSections({ detail, k }: { detail: ScriptDetail; k: ScriptsText }) {
  const present = SECTION_ORDER.filter(name => detail.sections[SECTION_API_KEY[name]])

  if (present.length === 0) {
    return null
  }

  return (
    <>
      {present.map(name => (
        <div key={name}>
          <PanelSectionLabel>{k.sections[name]}</PanelSectionLabel>
          <PanelBlock>{detail.sections[SECTION_API_KEY[name]]}</PanelBlock>
        </div>
      ))}
    </>
  )
}

function SourceBlock({ id, k }: { id: string; k: ScriptsText }) {
  const [open, setOpen] = useState(false)

  const { data, isError } = useQuery({
    enabled: open,
    queryFn: () => fetchSource(id),
    queryKey: sourceKey(id)
  })

  return (
    <div>
      <div className="flex items-center justify-between">
        <PanelSectionLabel>{k.source}</PanelSectionLabel>
        <Button onClick={() => setOpen(value => !value)} size="sm" variant="ghost">
          <Codicon name={open ? 'chevron-up' : 'chevron-down'} size="0.7rem" />
        </Button>
      </div>
      {open ? (
        isError ? (
          <p className="text-[0.66rem] text-muted-foreground/70">{k.sourceUnavailable}</p>
        ) : (
          <>
            <PanelBlock>{data?.content ?? ''}</PanelBlock>
            {data?.truncated ? (
              <p className="mt-1 text-[0.62rem] text-muted-foreground/60">{k.sourceTruncated}</p>
            ) : null}
          </>
        )
      ) : null}
    </div>
  )
}

function ScriptInspector({ id, k }: { id: string; k: ScriptsText }) {
  const { data: detail, isError, isPending } = useQuery({ queryFn: () => fetchDetail(id), queryKey: detailKey(id) })

  if (isPending) {
    return <PanelEmpty description={k.loading} icon="loading~spin" />
  }

  if (isError || !detail) {
    return <PanelEmpty description={k.failed} icon="warning" />
  }

  const commit = detail.vcs.commit

  const rows: PanelMetaRow[] = [
    { label: k.path, value: <span className="font-mono text-[0.66rem]">{detail.relpath}</span> },
    { label: k.root, value: detail.root_label },
    { label: k.language, value: detail.language },
    { label: k.size, value: formatBytes(detail.size_bytes) },
    { label: k.modified, value: formatDate(detail.modified_at) },
    {
      label: k.version,
      value: commit ? (
        <span className="font-mono text-[0.66rem]">
          {commit.short_sha} · {commit.subject}
        </span>
      ) : (
        <span className="text-muted-foreground/70">{k.noVersion}</span>
      )
    }
  ]

  return (
    <PanelDetail>
      <div>
        <h3 className="text-sm font-semibold text-foreground">{detail.name}</h3>
        <p className={cn('text-xs leading-relaxed', detail.purpose ? 'text-foreground/75' : 'text-muted-foreground/60')}>
          {detail.purpose || k.purposeMissing}
        </p>
      </div>

      <div>
        <PanelSectionLabel>{k.run}</PanelSectionLabel>
        <div className="flex items-start gap-1.5">
          <PanelBlock className="flex-1">{detail.run_command}</PanelBlock>
          {/* Copiar, nunca executar: a decisão de rodar fica com o operador. */}
          <CopyButton label={k.copy} text={detail.run_command} title={k.copy} />
        </div>
      </div>

      <PanelMeta rows={rows} />

      <div>
        <PanelSectionLabel>{k.lifecycle}</PanelSectionLabel>
        {detail.lifecycle.stages.map(stage => (
          <StageRow k={k} key={stage.stage} stage={stage} />
        ))}
        {detail.vcs.web_url ? (
          <a
            className="mt-1 inline-flex items-center gap-1 text-[0.68rem] text-primary hover:underline"
            href={detail.vcs.web_url}
            rel="noreferrer"
            target="_blank"
          >
            <Codicon name="github" size="0.7rem" />
            {k.openOnGithub}
          </a>
        ) : null}
      </div>

      <DocumentationSections detail={detail} k={k} />

      <div>
        <PanelSectionLabel>{k.history}</PanelSectionLabel>
        {detail.vcs.history.length === 0 ? (
          <p className="text-[0.66rem] text-muted-foreground/70">{k.noHistory}</p>
        ) : (
          <ul className="space-y-0.5">
            {detail.vcs.history.map(entry => (
              <li className="flex gap-2 text-[0.66rem]" key={entry.sha}>
                <span className="shrink-0 font-mono text-muted-foreground/60">{entry.short_sha}</span>
                <span className="min-w-0 truncate text-foreground/80">{entry.subject}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <SourceBlock id={detail.id} k={k} />
    </PanelDetail>
  )
}

export function ScriptsLibraryPage() {
  const k = useScriptsText()
  const [search, setSearch] = useState('')
  const [language, setLanguage] = useState('')
  const [selected, setSelected] = useState<string>('')

  const {
    data: catalog,
    isError,
    isPending,
    refetch
  } = useQuery({
    queryFn: () => fetchCatalog(search, language, ''),
    queryKey: catalogKey(search, language, '')
  })

  const scripts: ScriptSummary[] = catalog?.scripts ?? []
  const missingRoots = (catalog?.roots ?? []).filter(root => !root.exists)

  return (
    <div className="flex h-full min-h-0 flex-col p-4">
      <header className="mb-3 shrink-0">
        <h2 className="text-sm font-semibold text-foreground">{k.title}</h2>
        <p className="text-xs text-muted-foreground/80">{k.subtitle}</p>
      </header>

      {/* Uma configuração quebrada é dito na cara, não escondida atrás de uma
          lista vazia — "nada aqui" e "o diretório sumiu" são fatos diferentes. */}
      {missingRoots.length > 0 ? (
        <p className="mb-2 shrink-0 text-[0.66rem] text-amber-600 dark:text-amber-300">
          {k.rootsMissing(missingRoots.map(root => root.label).join(', '))}
        </p>
      ) : null}
      {catalog?.truncated ? (
        <p className="mb-2 shrink-0 text-[0.66rem] text-amber-600 dark:text-amber-300">{k.truncated}</p>
      ) : null}

      <PanelBody>
        <PanelList
          onSearchChange={setSearch}
          searchLabel={k.search}
          searchPlaceholder={k.searchPlaceholder}
          searchValue={search}
        >
          {(catalog?.languages.length ?? 0) > 1 ? (
            <div className="mb-1 flex flex-wrap gap-1">
              <Button
                onClick={() => setLanguage('')}
                size="sm"
                variant={language === '' ? 'secondary' : 'ghost'}
              >
                {k.allLanguages}
              </Button>
              {catalog?.languages.map(item => (
                <Button
                  key={item}
                  onClick={() => setLanguage(item)}
                  size="sm"
                  variant={language === item ? 'secondary' : 'ghost'}
                >
                  {item}
                </Button>
              ))}
            </div>
          ) : null}

          {scripts.map(script => (
            <PanelListRow
              active={script.id === selected}
              icon={LANGUAGE_ICON[script.language] ?? 'file-code'}
              key={script.id}
              meta={<PanelPill tone={STATE_TONE[script.vcs_state]}>{script.vcs_state}</PanelPill>}
              onSelect={() => setSelected(script.id)}
              rowKey={script.id}
              title={script.name}
            />
          ))}

          {catalog ? (
            <p className="px-1 py-1 text-[0.62rem] text-muted-foreground/50">
              {k.matched(catalog.matched, catalog.total)}
            </p>
          ) : null}
        </PanelList>

        {isPending ? (
          <PanelEmpty description={k.loading} icon="loading~spin" />
        ) : isError ? (
          <PanelEmpty
            action={
              <Button onClick={() => void refetch()} size="sm" variant="secondary">
                {k.retry}
              </Button>
            }
            description={k.failedHint}
            icon="warning"
            title={k.failed}
          />
        ) : scripts.length === 0 ? (
          <PanelEmpty
            description={search || language ? k.noMatchHint : k.emptyHint}
            icon="search"
            title={search || language ? k.noMatch : k.empty}
          />
        ) : selected ? (
          <ScriptInspector id={selected} k={k} />
        ) : (
          <PanelEmpty description={k.noSelectionHint} icon="file-code" title={k.noSelection} />
        )}
      </PanelBody>
    </div>
  )
}
