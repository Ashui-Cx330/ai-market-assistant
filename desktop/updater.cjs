const { app, dialog } = require('electron/main')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const state = require('./update-state.cjs')

let configured = false
let checking = false
let parentWindow = null
let logger = () => {}
const concise = value => String(value?.message || value || 'unknown error').split(/\r?\n/, 1)[0]

function updateConfiguration() {
  const file = path.join(app.getPath('userData'), 'settings', 'update.json')
  if (fs.existsSync(file)) {
    const value = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (value.provider === 'github' && value.owner && value.repo) return value
  }
  const owner = process.env.GH_OWNER || process.env.AI_MARKET_UPDATE_OWNER
  const repo = process.env.GH_REPO || process.env.AI_MARKET_UPDATE_REPO
  if (owner && repo) return { provider: 'github', owner, repo }
  const embedded = path.join(process.resourcesPath, 'app-update.yml')
  return app.isPackaged && fs.existsSync(embedded) ? { embedded: true } : null
}

function configureUpdater() {
  const { autoUpdater } = require('electron-updater')
  if (configured) return autoUpdater
  const configuration = updateConfiguration()
  if (!configuration) return null
  if (!configuration.embedded) autoUpdater.setFeedURL(configuration)
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.logger = {
    info: value => logger(concise(value)), warn: value => logger(concise(value)),
    error: value => logger(concise(value)), debug: value => logger(concise(value))
  }

  autoUpdater.on('error', error => {
    logger(`update error: ${concise(error)}`)
    state.updateLog(`check/download failed: ${concise(error)}`)
  })
  autoUpdater.on('download-progress', progress => parentWindow?.setProgressBar(progress.percent / 100))
  configured = true
  return autoUpdater
}

function copyInstalledVersion(info) {
  const installDir = path.dirname(process.execPath)
  const backupRoot = path.join(app.getPath('userData'), 'update-backups')
  const backupPath = path.join(backupRoot, `v${app.getVersion()}`)
  fs.mkdirSync(backupRoot, { recursive: true })
  if (fs.existsSync(backupPath)) fs.rmSync(backupPath, { recursive: true, force: true })
  state.updateLog(`backup started: ${installDir} -> ${backupPath}`)
  fs.cpSync(installDir, backupPath, { recursive: true, force: true })
  state.writeState({
    currentVersion: app.getVersion(),
    previousVersion: app.getVersion(),
    pendingVersion: info.version,
    updateStatus: 'pending-health-check',
    healthCheck: 'waiting',
    launchAttempts: 0,
    backupPath,
    installDir,
    executableName: path.basename(process.execPath),
    downloadResult: 'verified-by-electron-updater',
    installResult: 'pending'
  })
  state.updateLog(`download verified and backup completed: ${app.getVersion()} -> ${info.version}`)
  return backupPath
}

function startRollbackGuard() {
  const guard = app.isPackaged ? path.join(process.resourcesPath, 'app.asar.unpacked', 'rollback-guard.ps1') : path.join(__dirname, 'rollback-guard.ps1')
  const timeout = process.env.AI_UPDATE_HEALTH_TIMEOUT_SECONDS || '300'
  const child = spawn('powershell.exe', [
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
    '-File', guard, '-StateFile', state.statePath(), '-LogFile', state.updateLogPath(), '-TimeoutSeconds', timeout
  ], { detached: true, windowsHide: true, stdio: 'ignore' })
  child.unref()
  state.updateLog(`rollback guard started: pid=${child.pid}, timeout=${timeout}s`)
}

async function offerUpdate(autoUpdater, info, interactive) {
  const saved = state.readState()
  if ((saved.badVersions || []).includes(info.version)) {
    logger(`release v${info.version} is marked bad; update suppressed`)
    if (interactive && parentWindow) await dialog.showMessageBox(parentWindow, {
      type: 'warning', title: '已阻止问题版本',
      message: `v${info.version} 曾启动失败，已停止重复更新。`,
      detail: '请等待发布修复版本。当前稳定版本可以继续使用。',
      buttons: ['知道了']
    })
    return 'bad-release'
  }
  const notes = typeof info.releaseNotes === 'string' ? info.releaseNotes : '请查看发布说明。'
  const choice = process.env.AI_UPDATE_AUTO_ACCEPT === '1' ? { response: 0 } : await dialog.showMessageBox(parentWindow, {
    type: 'info', title: '发现新版本', message: `发现新版本 v${info.version}`,
    detail: `当前版本：v${app.getVersion()}\n最新版本：v${info.version}\n\n更新内容：\n${notes}`,
    buttons: ['立即更新', '稍后提醒'], defaultId: 0, cancelId: 1, noLink: true
  })
  if (process.env.AI_UPDATE_AUTO_ACCEPT === '1') state.updateLog('test automation accepted the real update prompt')
  if (choice.response !== 0) return 'later'
  parentWindow?.setProgressBar(0.01)
  try {
    await autoUpdater.downloadUpdate()
    return 'downloaded'
  } catch (error) {
    parentWindow?.setProgressBar(-1)
    state.updateLog(`download failed; old version retained: ${concise(error)}`)
    dialog.showErrorBox('更新下载失败', `${concise(error)}\n旧版本仍可继续使用。`)
    return 'download-failed'
  }
}

async function checkForUpdates(parent, log, options = {}) {
  if (!app.isPackaged && process.env.AI_UPDATE_ALLOW_DEV !== '1') return { status: 'development' }
  if (checking) return { status: 'checking' }
  checking = true
  parentWindow = parent
  logger = log
  const interactive = Boolean(options.interactive)
  try {
    const autoUpdater = configureUpdater()
    if (!autoUpdater) {
      log('update check skipped: no GitHub owner/repo or embedded app-update.yml')
      if (interactive) await dialog.showMessageBox(parent, {
        type: 'info', title: '自动更新尚未配置', message: '当前项目没有检测到真实 GitHub 仓库，需要配置 owner/repo。',
        buttons: ['知道了']
      })
      return { status: 'not-configured' }
    }

    const result = await autoUpdater.checkForUpdates()
    const info = result?.updateInfo
    if (!info || info.version === app.getVersion()) {
      state.updateLog(`no update: current=${app.getVersion()}`)
      if (interactive) await dialog.showMessageBox(parent, { type: 'info', title: '检查更新', message: '当前已经是最新版本。', buttons: ['知道了'] })
      return { status: 'current', version: app.getVersion() }
    }
    const action = await offerUpdate(autoUpdater, info, interactive)
    if (action === 'downloaded') {
      parent?.setProgressBar(-1)
      copyInstalledVersion(info)
      startRollbackGuard()
      state.updateLog('installer launching; current app will quit')
      autoUpdater.quitAndInstall(false, true)
      return { status: 'installing', version: info.version }
    }
    return { status: action, version: info.version }
  } catch (error) {
    log(`update check failed: ${concise(error)}`)
    state.updateLog(`update check failed: ${concise(error)}`)
    if (interactive) await dialog.showMessageBox(parent, {
      type: 'warning', title: '检查更新失败', message: '暂时无法检查更新，请稍后重试。',
      detail: concise(error), buttons: ['知道了']
    })
    return { status: 'network-error', message: concise(error) }
  } finally {
    checking = false
  }
}

module.exports = { checkForUpdates, updateConfiguration, startRollbackGuard }
