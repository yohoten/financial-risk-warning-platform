/** 构建 Vue 前端并拷贝到 resources/web，供 Electron 打包。 */
const { execSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const desktopDir = path.resolve(__dirname, '..')
const webDir = path.resolve(desktopDir, '..', 'web')
const outDir = path.join(desktopDir, 'resources', 'web')

console.log('[build-web] building Vue...')
execSync('npm run build', { cwd: webDir, stdio: 'inherit' })

fs.rmSync(outDir, { recursive: true, force: true })
fs.cpSync(path.join(webDir, 'dist'), outDir, { recursive: true })
console.log('[build-web] copied web/dist ->', outDir)
