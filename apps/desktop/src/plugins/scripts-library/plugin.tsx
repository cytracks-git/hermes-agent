/**
 * Scripts library — a first-class `/scripts-library` page + sidebar entry +
 * ⌘K command, reusing `plugins/scripts-library/dashboard/plugin_api.py` through
 * `ctx.rest` (namespace-scoped to `/api/plugins/scripts-library`). No core edit.
 *
 * Ships OFF by default (`defaultEnabled: false`), like kanban: it inventories in
 * Capabilities ▸ Plugins and registers nothing until the user flips the switch.
 *
 * O acesso é SOMENTE LEITURA por construção: o backend só tem rotas GET e esta
 * página não oferece execução — o operador copia o comando e decide.
 */

import {
  type HermesPlugin,
  host,
  PALETTE_AREA,
  type PaletteContribution,
  type RouteContribution,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  type SidebarNavContribution
} from '@hermes/plugin-sdk'

import { bindApi } from './api'
import { SCRIPTS_LOCALES } from './i18n'
import { ScriptsLibraryPage } from './page'

const PATH = '/scripts-library'

const plugin: HermesPlugin = {
  defaultEnabled: false,
  description:
    'Read-only library of the scripts on this machine — purpose, run command, dependencies, tests and version state.',
  id: 'scripts-library',
  name: 'Scripts',
  register(ctx) {
    ctx.i18n.register(SCRIPTS_LOCALES)
    ctx.onDispose(bindApi(ctx.rest))

    ctx.registerMany([
      {
        area: ROUTES_AREA,
        data: { path: PATH } satisfies RouteContribution,
        id: 'page',
        render: () => <ScriptsLibraryPage />
      },
      {
        area: SIDEBAR_NAV_AREA,
        data: { codicon: 'file-code', label: ctx.i18n.t('nav'), path: PATH } satisfies SidebarNavContribution,
        id: 'nav',
        order: 55
      },
      {
        area: PALETTE_AREA,
        data: {
          id: 'scriptsLibrary.open',
          keywords: ['scripts', 'library', 'tools', 'automation'],
          label: ctx.i18n.t('openCommand'),
          run: () => host.navigate(PATH)
        } satisfies PaletteContribution,
        id: 'open'
      }
    ])
  }
}

export default plugin
