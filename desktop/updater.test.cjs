const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const Module = require('node:module')
const fs = require('node:fs')
const path = require('node:path')

async function runCase({ currentVersion, availableVersion, savedState }) {
  const calls = { checks: 0, downloads: 0, quit: [], logs: [], writes: [] }
  const autoUpdater = new EventEmitter()
  autoUpdater.app = {}
  autoUpdater.checkForUpdates = async () => {
    calls.checks += 1
    return { updateInfo: { version: availableVersion, releaseNotes: 'test' } }
  }
  autoUpdater.downloadUpdate = async () => { calls.downloads += 1 }
  autoUpdater.quitAndInstall = (...args) => { calls.quit.push(args) }

  const app = {
    isPackaged: true,
    getVersion: () => currentVersion,
    getPath: name => name === 'temp' ? 'C:\\Temp' : 'C:\\Users\\test\\AppData\\Roaming\\AI行情助手'
  }
  const state = {
    readState: () => ({ badVersions: [], updateStatus: 'stable', ...savedState }),
    writeState: value => { calls.writes.push(value); return value },
    updateLog: value => calls.logs.push(value),
    statePath: () => 'C:\\state\\update-state.json',
    updateLogPath: () => 'C:\\state\\update.log'
  }
  const fakeFs = {
    ...fs,
    existsSync: file => String(file).endsWith('app-update.yml'),
    mkdirSync: () => {}, rmSync: () => {}, cpSync: () => {}
  }
  const originalLoad = Module._load
  const originalResourcesPath = process.resourcesPath
  process.resourcesPath = 'C:\\Program Files\\AI行情助手\\resources'
  Module._load = function(request, parent, isMain) {
    if (request === 'electron/main') return { app, dialog: { showMessageBox: async () => ({ response: 0 }), showErrorBox: () => {} } }
    if (request === 'electron-updater') return { autoUpdater }
    if (request === './update-state.cjs') return state
    if (request === 'node:child_process') return { spawn: () => ({ pid: 1234, unref: () => {} }) }
    if (request === 'node:fs') return fakeFs
    return originalLoad.call(this, request, parent, isMain)
  }

  const updaterPath = path.join(__dirname, 'updater.cjs')
  delete require.cache[require.resolve(updaterPath)]
  try {
    const updater = require(updaterPath)
    const result = await updater.checkForUpdates({ setProgressBar: () => {} }, () => {})
    return { result, calls, autoUpdater }
  } finally {
    Module._load = originalLoad
    process.resourcesPath = originalResourcesPath
    delete require.cache[require.resolve(updaterPath)]
  }
}

async function main() {
  const upgrade = await runCase({ currentVersion: '1.0.0', availableVersion: '1.0.1', savedState: {} })
  assert.equal(upgrade.result.status, 'installing')
  assert.equal(upgrade.autoUpdater.autoInstallOnAppQuit, false)
  assert.equal(upgrade.autoUpdater.installDirectory, path.dirname(process.execPath))
  assert.deepEqual(upgrade.calls.quit, [[true, true]])
  assert.equal(upgrade.calls.downloads, 1)

  const current = await runCase({ currentVersion: '1.0.1', availableVersion: '1.0.1', savedState: {} })
  assert.equal(current.result.status, 'current')
  assert.equal(current.calls.downloads, 0)
  assert.equal(current.calls.quit.length, 0)

  const pending = await runCase({
    currentVersion: '1.0.0', availableVersion: '1.0.1',
    savedState: { updateStatus: 'pending-health-check', pendingVersion: '1.0.1' }
  })
  assert.equal(pending.result.status, 'update-pending')
  assert.equal(pending.calls.checks, 0)
  assert.equal(pending.calls.quit.length, 0)

  console.log('PASS 1.0.0->1.0.1 silent install / same-version suppression / pending-transaction suppression')
}

main().catch(error => { console.error(error); process.exitCode = 1 })
