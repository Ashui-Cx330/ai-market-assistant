const { _electron: electron } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const testData = path.join(root, 'work', 'desktop-e2e-data')
fs.rmSync(testData, { recursive: true, force: true })

async function nav(page, label, heading) {
  await page.locator('nav button').filter({ hasText: label }).click()
  await page.getByRole('heading', { name: heading, exact: true }).waitFor({ timeout: 30000 })
}

async function run() {
  let complete = false
  const packaged = process.env.AI_PACKAGED_E2E === '1'
  const app = await electron.launch({
    executablePath: packaged ? path.join(root, 'outputs', 'desktop', 'win-unpacked', 'AI行情助手.exe') : path.join(__dirname, 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: packaged ? [] : [path.join(__dirname, 'main.cjs')], cwd: root, timeout: 60000,
    env: { ...process.env, TRADING_AI_DESKTOP_PORT: '18766', TRADING_AI_TEST_DATA_DIR: testData }
  })
  try {
    const page = await app.firstWindow({ timeout: 90000 })
    await page.waitForLoadState('domcontentloaded')
    await page.getByRole('heading', { name: '市场概览' }).waitFor({ timeout: 30000 })

    await nav(page, '行情搜索', '行情搜索终端')
    await page.getByRole('heading', { name: '找股票 / 看股票' }).waitFor()
    await nav(page, 'AI 预测', 'AI预测中心')
    await page.getByText('PREDICTION CENTER').waitFor()
    await nav(page, '回测', '策略研究与回测')
    await page.getByText('STRATEGY LAB').waitFor()
    await nav(page, '模拟交易', '模拟交易账户')
    await page.getByRole('heading', { name: '下单面板' }).waitFor()

    await nav(page, '行情搜索', '行情搜索终端')
    const search = page.locator('.search input')
    await search.fill('600519')
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.locator('.search-results button').filter({ hasText: '贵州茅台' }).click({ timeout: 60000 })
    await page.getByRole('heading', { name: '贵州茅台', exact: true }).waitFor({ timeout: 30000 })
    if (!page.url().endsWith('/stock/600519')) throw new Error(`Unexpected symbol route: ${page.url()}`)
    await page.locator('.kline-chart canvas').waitFor({ timeout: 30000 })
    await page.locator('[title*="RSI衡量"]').waitFor()
    await page.locator('[title*="MACD用于观察"]').waitFor()

    await page.locator('.periods .buy').click()
    await page.getByRole('heading', { name: '下单面板' }).waitFor()
    await page.getByRole('button', { name: '确认买入' }).click()
    await page.locator('.position-row').filter({ hasText: '600519.SH' }).waitFor({ timeout: 30000 })

    await page.locator('.order-ticket select').selectOption('LIMIT')
    await page.locator('.order-ticket label').filter({ hasText: '限价' }).locator('input').fill('1')
    await page.getByRole('button', { name: '确认买入' }).click()
    const pending = page.locator('.paper-order-row').filter({ hasText: 'pending' }).first()
    await pending.waitFor({ timeout: 30000 })
    await pending.getByRole('button', { name: '撤单' }).click()
    await page.locator('.paper-order-row').filter({ hasText: 'cancelled' }).first().waitFor({ timeout: 30000 })
    await page.locator('.position-row').filter({ hasText: '600519.SH' }).getByRole('button', { name: '全部卖出' }).click()
    await page.locator('.paper-order-row').filter({ hasText: 'SELL / MARKET' }).first().waitFor({ timeout: 30000 })

    await nav(page, '新闻情报', 'AI Market Intelligence')
    await page.getByRole('heading', { name: '真实新闻列表' }).waitFor({ timeout: 90000 })
    const newsCards = page.locator('.news-list.rich-news article')
    if (await newsCards.count()) {
      await newsCards.first().getByRole('button', { name: 'AI深度分析' }).click()
      await page.getByText('已发生 · 新闻事实').waitFor()
      await page.getByRole('heading', { name: /AI判断/ }).waitFor()
      await page.getByRole('heading', { name: '市场预测' }).waitFor()
      await page.getByRole('button', { name: 'Close this dialog' }).click()
    }

    await nav(page, '设置与更新', '设置与更新')
    console.log(`PASS ${packaged ? 'packaged' : 'development'} independent-routes/canonical-symbol/chart/tooltips/news/paper-market-limit-cancel-position`)
    complete = true
  } finally {
    await app.close()
    if (complete) fs.rmSync(testData, { recursive: true, force: true })
  }
}

run().catch(error => { console.error(error); process.exitCode = 1 })
