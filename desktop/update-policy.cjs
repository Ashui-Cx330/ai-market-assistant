const INSTALL_OPTIONS = Object.freeze({
  isSilent: true,
  isForceRunAfter: true
})

function numericVersion(version) {
  const match = String(version || '').trim().match(/^v?(\d+)\.(\d+)\.(\d+)(?:\.\d+)?(?:[-+].*)?$/)
  return match ? match.slice(1, 4).map(Number) : null
}

function isStrictlyNewerVersion(candidate, current) {
  const next = numericVersion(candidate)
  const installed = numericVersion(current)
  if (!next || !installed) return false
  for (let index = 0; index < 3; index += 1) {
    if (next[index] > installed[index]) return true
    if (next[index] < installed[index]) return false
  }
  return false
}

module.exports = { INSTALL_OPTIONS, isStrictlyNewerVersion }
