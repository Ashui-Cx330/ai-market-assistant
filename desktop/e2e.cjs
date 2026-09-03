const { _electron: electron } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const testData = path.join(root, 'work', 'desktop-e2e-data')
fs.rmSync(testData, { recursive: true, force: true })

async function run() {
  let complete = false
  const app = await electron.launch({
    executablePath: path.join(__dirname, 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: [path.join(__dirname, 'main.cjs')], cwd: root, timeout: 60000,
    env: { ...process.env, TRADING_AI_DESKTOP_PORT: '18766', TRADING_AI_TEST_DATA_DIR: testData }
  })
  try {
    const page = await app.firstWindow({ timeout: 90000 })
    await page.waitForLoadState('domcontentloaded')
    await page.getByRole('heading', { name: '市场概览' }).waitFor({ timeout: 30000 })
    await page.locator('nav button').filter({ hasText: '设置与更新' }).click()
    await page.getByRole('heading', { name: '设置与更新' }).waitFor({ timeout: 10000 })
    await page.getByRole('button', { name: '检查更新' }).click()
    await page.getByText('更新检查已完成。', { exact: true }).waitFor({ timeout: 10000 })
    await page.locator('nav button').filter({ hasText: '首页' }).click()
    const search = page.locator('.search input')
    await search.fill('600519')
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.locator('.search-results button').filter({ hasText: '贵州茅台' }).click({ timeout: 60000 })
    await page.getByRole('heading', { name: '贵州茅台', exact: true }).waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: '1H', exact: true }).click()
    await page.locator('.kline-chart canvas').waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: '1D', exact: true }).click()
    await page.locator('.head-actions .primary').click()
    await page.getByText('未来 1h', { exact: true }).waitFor({ timeout: 120000 })
    await page.locator('.two-col .panel').nth(1).getByRole('button', { name: '开始回测' }).click()
    await page.getByText('最终资金', { exact: true }).waitFor({ timeout: 120000 })
    await page.locator('.head-actions button').first().click()
    await page.getByText(/已移出自选/).waitFor({ timeout: 10000 })
    await page.locator('.head-actions button').first().click()
    await page.getByText(/已加入自选/).waitFor({ timeout: 10000 })
    await page.locator('.trade-panel .buy').click()
    await page.getByText(/模拟买入已按实时价成交/).waitFor({ timeout: 30000 })
    await page.locator('nav button').filter({ hasText: '模拟交易' }).click()
    await page.getByText('实时持仓', { exact: true }).waitFor({ timeout: 30000 })
    await page.locator('.table-row').filter({ hasText: '600519' }).getByRole('button', { name: '全部卖出' }).click()
    await page.getByText(/已按实时价全部卖出/).waitFor({ timeout: 30000 })
    await search.fill('BTC')
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.locator('.search-results button').filter({ hasText: 'BTC/USDT' }).click({ timeout: 60000 })
    await page.getByRole('heading', { name: 'BTC/USDT', exact: true }).waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: '4H', exact: true }).click()
    await page.locator('.kline-chart canvas').waitFor({ timeout: 30000 })
    console.log('PASS home/settings/update-check/search/stock-detail/1H/chart/AI/backtest/watchlist/paper-buy/paper-sell/crypto-search/4H')
    complete = true
  } finally {
    await app.close()
    if (complete) fs.rmSync(testData, { recursive: true, force: true })
  }
}

run().catch(error => { console.error(error); process.exitCode = 1 })
