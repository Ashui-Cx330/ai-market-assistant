const fs = require('node:fs')
const path = require('node:path')
const { app } = require('electron/main')

function statePath() { return path.join(app.getPath('userData'), 'update-state.json') }
function updateLogPath() { return path.join(app.getPath('userData'), 'update.log') }

function readState() {
  try { return JSON.parse(fs.readFileSync(statePath(), 'utf8')) }
  catch { return { currentVersion: app.getVersion(), previousVersion: null, pendingVersion: null, updateStatus: 'stable', healthCheck: 'unknown', launchAttempts: 0, rollbackCount: 0, badVersions: [] } }
}

function writeState(changes) {
  const next = { ...readState(), ...changes, lastUpdateTime: new Date().toISOString() }
  fs.mkdirSync(path.dirname(statePath()), { recursive: true })
  const temporary = `${statePath()}.tmp`
  fs.writeFileSync(temporary, `${JSON.stringify(next, null, 2)}\n`, 'utf8')
  try {
    fs.renameSync(temporary, statePath())
  } catch (error) {
    if (error?.code !== 'EXDEV') throw error
    // EFS-encrypted Windows profile directories can reject an otherwise local
    // atomic rename. Preserve correctness with a flushed copy fallback.
    fs.copyFileSync(temporary, statePath())
    fs.unlinkSync(temporary)
  }
  return next
}

function updateLog(message) {
  fs.appendFileSync(updateLogPath(), `${new Date().toISOString()} ${message}\n`, 'utf8')
}

function recordLaunch() {
  const state = readState()
  if (state.pendingVersion === app.getVersion() && state.updateStatus === 'pending-health-check') {
    const next = writeState({ healthCheck: 'running', launchAttempts: Number(state.launchAttempts || 0) + 1 })
    updateLog(`new version launch: ${app.getVersion()}, attempt ${next.launchAttempts}`)
    return next
  }
  return state
}

function markHealthy() {
  const state = readState()
  if (state.pendingVersion !== app.getVersion()) return state
  updateLog(`health check passed: ${app.getVersion()}`)
  const backupPath = state.backupPath
  const result = writeState({ currentVersion: app.getVersion(), previousVersion: null, pendingVersion: null, updateStatus: 'stable', healthCheck: 'passed', installResult: 'confirmed', launchAttempts: 0, backupPath: null })
  if (backupPath && backupPath.startsWith(path.join(app.getPath('userData'), 'update-backups')) && fs.existsSync(backupPath)) {
    fs.rmSync(backupPath, { recursive: true, force: true })
    updateLog(`stable backup removed: ${backupPath}`)
  }
  return result
}

module.exports = { statePath, updateLogPath, readState, writeState, updateLog, recordLaunch, markHealthy }
