const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { app, BrowserWindow, dialog, Menu, ipcMain } = require('electron/main')
const { shell } = require('electron/common')

const APP_NAME = 'AI行情助手'
const SERVICE_HOST = '127.0.0.1'
const SERVICE_PORT = Number(process.env.TRADING_AI_DESKTOP_PORT || 18765)
const SERVICE_URL = `http://${SERVICE_HOST}:${SERVICE_PORT}`
let mainWindow = null
let backendProcess = null
let ownsBackend = false
let quitting = false
const updateState = require('./update-state.cjs')

// NSIS --force-run can inherit transient installer profile variables. Resolve
// the per-user data roots from the actual Windows home before Electron reads
// appData/userData, so an updated launch immediately opens the persistent DB.
if (process.platform === 'win32' && process.argv.includes('--updated')) {
  const userHome = process.env.USERPROFILE || os.homedir()
  process.env.APPDATA = path.join(userHome, 'AppData', 'Roaming')
  process.env.LOCALAPPDATA = path.join(userHome, 'AppData', 'Local')
}

app.setName(APP_NAME)
app.setPath('userData', process.env.TRADING_AI_TEST_DATA_DIR ? path.join(process.env.TRADING_AI_TEST_DATA_DIR, 'electron') : path.join(app.getPath('appData'), APP_NAME))
app.enableSandbox()
const logFile = path.join(app.getPath('userData'), 'desktop.log')
fs.mkdirSync(app.getPath('userData'), { recursive: true })
const log = message => fs.appendFileSync(logFile, `${new Date().toISOString()} ${message}\n`, 'utf8')
process.on('uncaughtException', error => log(`uncaughtException ${error.stack || error.message}`))
process.on('unhandledRejection', error => log(`unhandledRejection ${error?.stack || error}`))
log(`starting Electron ${process.versions.electron}, app ${app.getVersion()}`)

const lock = app.requestSingleInstanceLock()
if (!lock) app.quit()

function projectRoot() {
  return app.isPackaged ? path.join(process.resourcesPath, 'app') : path.resolve(__dirname, '..')
}

async function serviceReady() {
  try {
    const response = await fetch(`${SERVICE_URL}/api/health`, { signal: AbortSignal.timeout(5000) })
    if (!response.ok) return false
    const result = await response.json()
    return result.status === 'ok' && result.service === APP_NAME && result.database === 'ok' && result.frontend === 'ok'
  } catch {
    return false
  }
}

function startBackend() {
  log(`starting backend on ${SERVICE_URL}`)
  const dataDir = process.env.TRADING_AI_TEST_DATA_DIR || app.getPath('userData')
  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'backend', 'AI行情助手服务.exe')
    if (!fs.existsSync(executable)) throw new Error(`缺少后端组件：${executable}`)
    backendProcess = spawn(executable, ['--host', SERVICE_HOST, '--port', String(SERVICE_PORT)], {
      windowsHide: true, stdio: 'ignore', env: { ...process.env, TRADING_AI_DATA_DIR: dataDir, TRADING_AI_DESKTOP: '1', TRADING_AI_FRONTEND_DIR: path.join(process.resourcesPath, 'app', 'frontend', 'dist') }
    })
  } else {
    const pythonw = path.join(projectRoot(), '.venv', 'Scripts', 'pythonw.exe')
    if (!fs.existsSync(pythonw)) throw new Error('开发环境缺少 .venv\\Scripts\\pythonw.exe，请先运行 start.bat 完成初始化。')
    backendProcess = spawn(pythonw, ['-m', 'uvicorn', 'backend.main:app', '--host', SERVICE_HOST, '--port', String(SERVICE_PORT)], {
      cwd: projectRoot(), windowsHide: true, stdio: 'ignore',
      env: { ...process.env, TRADING_AI_DATA_DIR: dataDir, TRADING_AI_DESKTOP: '1' }
    })
  }
  ownsBackend = true
  backendProcess.once('exit', () => { backendProcess = null })
}

function stopBackend() {
  if (!ownsBackend || !backendProcess) return
  const pid = backendProcess.pid
  if (process.platform === 'win32' && pid) {
    spawnSync('taskkill', ['/pid', String(pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' })
  } else {
    backendProcess.kill()
  }
  backendProcess = null
}

async function ensureBackend() {
  if (await serviceReady()) return
  startBackend()
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 500))
    if (await serviceReady()) return
    if (!backendProcess) break
  }
  throw new Error('本地行情服务未能在规定时间内启动。')
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    title: `${APP_NAME} v${app.getVersion()}`,
    width: 1380, height: 880, minWidth: 980, minHeight: 680,
    show: false, backgroundColor: '#07101d', autoHideMenuBar: true,
    icon: path.join(__dirname, 'assets', 'app-icon.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.cjs') }
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', event => event.preventDefault())
  mainWindow.once('ready-to-show', () => mainWindow.show())
  await mainWindow.loadURL(SERVICE_URL)
  let rendererReady = false
  let serviceHealthy = false
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try { rendererReady = await mainWindow.webContents.executeJavaScript("Boolean(document.querySelector('main') && document.body.innerText.includes('AI行情助手'))") } catch { rendererReady = false }
    serviceHealthy = await serviceReady()
    if (rendererReady && serviceHealthy) break
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  // Release acceptance hook: lets the automated Windows update test prove that
  // the external rollback guard restores the prior version after a bad launch.
  // It is inactive for normal users and is never persisted in application data.
  if (process.env.AI_FORCE_STARTUP_HEALTH_FAILURE === '1') {
    rendererReady = false
    log('startup health failure injected for release acceptance test')
  }
  log(`startup health: electron=ok renderer=${rendererReady ? 'ok' : 'failed'} backend/database/api=${serviceHealthy ? 'ok' : 'failed'}`)
  if (!rendererReady || !serviceHealthy) throw new Error('启动健康检查失败：页面、本地服务或数据库未就绪。')
  log('main window loaded')
  updateState.markHealthy()
  setTimeout(() => require('./updater.cjs').checkForUpdates(mainWindow, log, { beforeInstall: stopBackend }).catch(error => log(`update check failed ${error.message}`)), 2500)
}

if (lock) {
  const launchState = updateState.recordLaunch()
  if (launchState.updateStatus === 'rolled-back' && launchState.rollbackMessage) {
    app.whenReady().then(() => dialog.showMessageBox({ type: 'warning', title: '自动回滚完成', message: `新版本启动失败，已自动恢复到稳定版本 v${launchState.currentVersion}。`, buttons: ['知道了'] }))
    updateState.writeState({ rollbackMessage: null })
  }
  ipcMain.handle('desktop:check-for-updates', () => require('./updater.cjs').checkForUpdates(mainWindow, log, { interactive: true, beforeInstall: stopBackend }))
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus() }
  })

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null)
    try { await ensureBackend(); await createWindow() }
    catch (error) { log(`startup failed ${error.stack || error.message}`); dialog.showErrorBox(`${APP_NAME} 启动失败`, error.message); app.quit() }
  })

  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', () => {
    if (quitting) return
    quitting = true
    stopBackend()
  })
}
