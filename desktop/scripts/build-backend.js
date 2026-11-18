/**
 * 打包 FastAPI 后端为独立可执行文件（PyInstaller），供 Electron 生产形态使用。
 *
 * 产物：desktop/resources/backend/risk-backend[.exe]  +  runtime/（运行时数据资产）
 * 打包后桌面端不依赖目标机安装 Python，也不依赖项目源码目录。
 *
 * 实际逻辑委托给 scripts/build_backend.py（需要项目的 .venv 环境）。
 */
const { execSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const desktopDir = path.resolve(__dirname, '..')
const repoDir = path.resolve(desktopDir, '..')
const pyScript = path.join(repoDir, 'scripts', 'build_backend.py')

function findPython() {
  const candidates = process.platform === 'win32'
    ? [path.join(repoDir, '.venv', 'Scripts', 'python.exe'),
       path.join(repoDir, '.venv', 'Scripts', 'pythonw.exe')]
    : [path.join(repoDir, '.venv', 'bin', 'python3'),
       path.join(repoDir, '.venv', 'bin', 'python')]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

if (!fs.existsSync(pyScript)) {
  console.error('[build-backend] 找不到打包脚本：' + pyScript)
  process.exit(1)
}

const python = findPython()
console.log('[build-backend] using python:', python)
try {
  execSync(`"${python}" "${pyScript}"`, { cwd: repoDir, stdio: 'inherit' })
} catch (err) {
  console.error('[build-backend] 打包失败（若缺少 PyInstaller，请先在 .venv 中执行 pip install pyinstaller）')
  process.exit(err.status ?? 1)
}
console.log('[build-backend] done ->', path.join(desktopDir, 'resources', 'backend'))
