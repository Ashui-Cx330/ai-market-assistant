const pkg = require('./package.json')

const owner = process.env.GH_OWNER
const repo = process.env.GH_REPO
if (Boolean(owner) !== Boolean(repo)) throw new Error('GH_OWNER 和 GH_REPO 必须同时设置。')

module.exports = {
  ...pkg.build,
  publish: owner && repo ? [{ provider: 'github', owner, repo, releaseType: 'release' }] : undefined
}
