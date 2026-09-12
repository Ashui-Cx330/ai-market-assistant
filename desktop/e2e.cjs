const { _electron: electron } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const testData = path.join(root, 'work', 'desktop-e2e-data')
if (process.env.AI_E2E_FRESH === '1') fs.rmSync(testData, { recursive: true, force: true })

async function nav(page, label, heading) {
  await page.locator('.terminal-sidebar nav button').filter({ hasText: label }).click()
  await page.getByRole('heading', { name: heading, exact: true }).first().waitFor({ timeout: 60000 })
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
    await page.getByRole('heading', { name: 'Market Intelligence', exact: true }).waitFor({ timeout: 90000 })
    await page.locator('.pulse-score strong').waitFor({ timeout: 90000 })

    await nav(page, '行情', 'Market Scanner')
    const scannerRow = page.locator('.scanner-table tbody tr').first()
    await scannerRow.waitFor({ timeout: 90000 })
    const scannerSymbol = (await scannerRow.locator('td b').first().innerText()).trim()
    // Search suggestions are deterministic even when a quote provider is down.
    await page.locator('.global-search input').fill('NVDA')
    await page.locator('.global-search button').filter({ hasText: '搜索' }).click()
    await page.locator('.search-pop button').filter({ hasText: 'NVDA' }).first().waitFor()
    // Detail/chart verification uses a row that the scanner just proved has a
    // working real provider, rather than assuming Yahoo is reachable.
    await scannerRow.click({ force: true })
    await page.locator('.instrument-bar').filter({ hasText: scannerSymbol }).waitFor({ timeout: 60000 })
    try {
      await page.locator('.kline-chart canvas').waitFor({ timeout: 90000 })
    } catch (error) {
      await page.screenshot({ path: path.join(root, 'work', 'v19-packaged-detail-failure.png'), fullPage: true })
      console.error('DETAIL_ERRORS', await page.locator('.state-error').allTextContents())
      console.error('DETAIL_TEXT', (await page.locator('.detail-workspace').innerText().catch(() => 'missing')).slice(0, 2000))
      throw error
    }
    await page.locator('.periods button').filter({ hasText: '1W' }).waitFor()
    await page.locator('.info-tip').filter({ hasText: 'RSI' }).waitFor()
    await page.locator('.ai-score strong').waitFor({ timeout: 60000 })

    await nav(page, '模型表现', 'Model Lab')
    await page.getByText(/Immutable resolved history/).waitFor()
    await page.getByText(/no random split/).waitFor()

    await nav(page, 'Quant Research', '寻找统计优势，而不是生成买卖口号')
    await page.getByText('Production Model').waitFor()
    await page.getByText('NONE', { exact: true }).first().waitFor()

    await nav(page, '策略实验室', 'Strategy Lab')
    await page.getByRole('button', { name: '转换为可执行规则' }).click()
    await page.getByText('HOLD_BARS 5').waitFor()

    await nav(page, '模拟交易', 'Paper Trading Terminal')
    await page.locator('.order-ticket').waitFor({ timeout: 60000 })
    await page.getByRole('button', { name: 'Review BUY' }).click()
    await page.getByRole('heading', { name: '确认模拟订单' }).waitFor()
    await page.getByRole('button', { name: '确认买入' }).click()
    await page.locator('.positions-pane button').first().waitFor({ timeout: 60000 })

    await nav(page, 'AI Copilot', 'AI Market Copilot')
    await page.getByRole('button', { name: '分析 NVDA' }).click()
    await page.getByText('market.quote').last().waitFor({ timeout: 90000 })
    await page.getByText(/数据截止/).last().waitFor()

    await nav(page, '新闻情报', 'AI Market Intelligence')
    await page.locator('.news-tabs').waitFor()
    // Navigation starts a real multi-provider collection. Let that request
    // settle before changing the sentiment filter so the E2E does not create
    // two identical cold collections at once.
    await page.locator('.news-feed, .news-workspace .state-error').first().waitFor({ timeout: 90000 })
    await page.getByRole('button', { name: '利好', exact: true }).click()
    await page.locator('.news-feed').waitFor({ timeout: 90000 })

    await nav(page, '设置', 'Settings & Data Health')
    await page.getByRole('heading', { name: 'Data Health', exact: true }).waitFor({ timeout: 60000 })
    await page.getByText(/不属于交易所授权逐笔行情/).waitFor()
    await nav(page, '首页', 'Market Intelligence')
    await page.locator('.pulse-score strong').waitFor({ timeout: 90000 })
    await page.screenshot({ path: path.join(root, 'work', 'v19-home.png'), fullPage: true })
    console.log(`PASS ${packaged ? 'packaged' : 'development'} v1.9 routes/scanner/chart/tooltip/model-lab/strategy/paper-confirm/copilot/news/data-health`)
    complete = true
  } finally {
    await app.close()
    if (complete) fs.rmSync(testData, { recursive: true, force: true })
  }
}

run().catch(error => { console.error(error); process.exitCode = 1 })
