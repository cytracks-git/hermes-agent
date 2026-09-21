import { execFileSync } from 'node:child_process'
import { readFileSync, realpathSync } from 'node:fs'
import { resolve } from 'node:path'

import { test, expect } from './test'
import { buildAppEnv, createSandbox, launchDesktop } from './fixtures'

// Integração opt-in: backend real, loopback e cópia SQLite; nunca intercepta respostas.
// O token fica no arquivo privado do lab, não em argumentos ou evidência.
test('Kanban live: clocks and source navigation against a real backend', async () => {
  test.setTimeout(180_000)
  test.skip(!process.env.KANBAN_LIVE_TOKEN_FILE, 'Requires an isolated real backend and a board snapshot')
  const sandbox = createSandbox('kanban-live')
  const env = buildAppEnv(sandbox, {
    HOME: resolve(import.meta.dirname, '../../../.proof/host-home'),
    HERMES_DESKTOP_REMOTE_URL: process.env.KANBAN_LIVE_URL ?? 'http://127.0.0.1:9527',
    HERMES_DESKTOP_REMOTE_TOKEN: readFileSync(process.env.KANBAN_LIVE_TOKEN_FILE!, 'utf8').trim(),
    HERMES_DESKTOP_CDP_PORT: 'off'
  })
  const { app, page } = await launchDesktop(env)
  try {
    await page.getByRole('button', { name: "I'll choose a provider later" }).click({ timeout: 40_000 })
    await page.goto(new URL('#/capabilities?tab=plugins&plugin=kanban', page.url()).href)
    await page.getByRole('switch', { name: 'Desktop: Kanban', exact: true }).check({ timeout: 45_000 })
    await page.goto(new URL('#/kanban', page.url()).href)
    const title = process.env.KANBAN_LIVE_TASK_TITLE!
    await expect(page.getByText(title, { exact: true }).first()).toBeVisible({ timeout: 40_000 })
    await page.getByText(title, { exact: true }).first().click()
    await expect(page.getByText('Card age', { exact: true })).toBeVisible()
    await expect(page.getByText('This attempt', { exact: true })).toBeVisible()
    const panel = page.getByText('Card age', { exact: true }).locator('../..')
    const before = await panel.innerText()
    await expect.poll(() => panel.innerText(), { timeout: 65_000 }).not.toBe(before)
    console.log(JSON.stringify({ before, after: await panel.innerText() }))
    await page
      .getByText('Card age', { exact: true })
      .locator('../../..')
      .screenshot({ path: process.env.KANBAN_LIVE_SCREENSHOT ?? `${sandbox.root}/kanban.png` })
    const source = page.getByRole('button', { name: /from (activity|a comment|run)/ }).first()
    await source.focus()
    await page.keyboard.press('Enter')
    const focused = await page.evaluate(() => document.activeElement?.id)
    expect(focused).toMatch(/^kanban-(event|comment|run)-/)
    console.log(JSON.stringify({ focused, url: new URL(page.url()).hash }))
    // Corrompe somente o snapshot privado: claim inexistente não pode herdar run antigo.
    const snapshot = resolve(import.meta.dirname, '../../../.proof/home/kanban.db')
    expect(realpathSync(snapshot)).toBe(snapshot)
    const id = process.env.KANBAN_LIVE_TASK_ID!
    expect(id).toMatch(/^t_[0-9a-f]{8}$/)
    const sql = (query: string) => execFileSync('sqlite3', [snapshot, query], { encoding: 'utf8' }).trim()
    const run = Number(sql(`SELECT current_run_id FROM tasks WHERE id='${id}'`))
    expect(Number.isSafeInteger(run) && run > 0).toBe(true)
    try {
      sql(`UPDATE tasks SET current_run_id=-1 WHERE id='${id}'`)
      const response = await fetch(`${env.HERMES_DESKTOP_REMOTE_URL}/api/plugins/kanban/tasks/${id}?board=default`, {
        headers: { Authorization: `Bearer ${env.HERMES_DESKTOP_REMOTE_TOKEN}` }
      })
      expect(response.status).toBe(200)
      const payload = await response.json()
      console.log(JSON.stringify({ observedClaim: payload.task.current_run_id }))
      expect(payload.task.current_run_id).toBe(-1)
      await page.getByRole('button', { name: 'Close', exact: true }).click()
      await page.getByText(title, { exact: true }).first().click()
      await expect(page.getByText('Unknown — no run reported', { exact: false })).toBeVisible({
        timeout: 45_000
      })
      console.log('NEGATIVE: missing current claim is visibly unavailable; no fallback to the old run')
    } finally {
      sql(`UPDATE tasks SET current_run_id=${run} WHERE id='${id}'`)
    }
    await page.getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByText(title, { exact: true }).first().click()
    await expect(page.getByText('Unknown — no run reported', { exact: false })).toHaveCount(0, {
      timeout: 45_000
    })
    await expect(page.getByText('This attempt', { exact: true })).toBeVisible()
    console.log('RESTORED: current attempt reading recovered')
  } catch (error) {
    console.log('UI on failure:', (await page.locator('body').innerText()).slice(0, 12000))
    throw error
  } finally {
    await app.close()
    sandbox.cleanup()
  }
})
