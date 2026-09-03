const fs = require('node:fs')
const path = require('node:path')
const root = path.resolve(__dirname, '..')
const desktop = require('./package.json')
const release = require('../version.json')
const required = ['frontend/dist/index.html', 'backend/main.py', '.venv/Scripts/pythonw.exe', 'desktop/assets/app-icon.ico']
const missing = required.filter(file => !fs.existsSync(path.join(root, file)))
if (desktop.version !== release.version) throw new Error(`版本不一致: desktop=${desktop.version}, root=${release.version}`)
if (missing.length) throw new Error(`缺少运行文件: ${missing.join(', ')}`)
console.log(`Desktop Batch 1 verified: ${desktop.productName} v${desktop.version}`)

