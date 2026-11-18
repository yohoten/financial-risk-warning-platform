/**
 * 财务风险智能预警平台 · Electron 主进程（Windows / macOS / Linux）
 *
 * 职责：
 *  1. 单实例锁 + 动态端口
 *  2. 拉起 FastAPI 后端（uvicorn，优先 .venv python，兜底系统 python）
 *  3. 等待 /health 就绪后创建窗口，加载 http://127.0.0.1:<port>
 *  4. 菜单 / 外链用系统浏览器打开
 *  5. 退出时优雅关闭后端进程树
 *
 * 环境变量：
 *  RWP_SMOKE=1  只做「拉起后端 + 健康检查」，成功后退出（CI/自检）
 *  RWP_DEV=1    强制使用开发模式
 *  RWP_BACKEND  指定后端可执行文件路径（覆盖自动探测）
 */
const { app, BrowserWindow, Menu, dialog, shell, nativeImage, Tray } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
const net = require('node:net')
const path = require('node:path')

const SMOKE = process.env.RWP_SMOKE || ''
const isDev = process.env.RWP_DEV === '1' || !app.isPackaged
const isWin = process.platform === 'win32'
const isMac = process.platform === 'darwin'

app.setName('FinancialRiskWarningPlatform')

let backend = null
let win = null
let tray = null
let backendPort = 0
let quitting = false

// ---------- 路径 ----------
const repo = path.resolve(__dirname, '..')

function resourcePath(...parts) {
  return path.join(app.isPackaged ? process.resourcesPath : path.join(__dirname, 'resources'), ...parts)
}

function webDist() {
  const packaged = resourcePath('web')
  if (fs.existsSync(path.join(packaged, 'index.html'))) return packaged
  const dist = path.join(repo, 'web', 'dist')
  return fs.existsSync(path.join(dist, 'index.html')) ? dist : packaged
}

/**
 * 后端启动命令解析，优先级：
 *   1. RWP_BACKEND 环境变量（显式指定 exe/脚本）
 *   2. 打包产物 resources/backend/risk-backend[.exe]（PyInstaller 冻结版，自包含）
 *   3. 项目 .venv 里的 python（开发态）
 *   4. 系统 python（兜底）
 */
function backendCommand() {
  if (process.env.RWP_BACKEND) {
    return { cmd: process.env.RWP_BACKEND, args: [], cwd: path.dirname(process.env.RWP_BACKEND) }
  }
  // 打包形态：PyInstaller onedir 冻结版（resources/backend/risk-backend/risk-backend[.exe]）
  const backendRoot = resourcePath('backend')
  const frozenCandidates = [
    path.join(backendRoot, 'risk-backend', isWin ? 'risk-backend.exe' : 'risk-backend'),
    path.join(backendRoot, isWin ? 'risk-backend.exe' : 'risk-backend'),
  ]
  const frozen = frozenCandidates.find((p) => fs.existsSync(p))
  if (frozen) {
    return { cmd: frozen, args: [], cwd: path.dirname(frozen) }
  }
  const venvCandidates = isWin
    ? [path.join(repo, '.venv', 'Scripts', 'python.exe'), path.join(repo, '.venv', 'Scripts', 'pythonw.exe')]
    : [path.join(repo, '.venv', 'bin', 'python3'), path.join(repo, '.venv', 'bin', 'python')]
  const python = venvCandidates.find((p) => fs.existsSync(p))
  if (python) {
    return { cmd: python, args: ['-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1'], cwd: repo }
  }
  return { cmd: isWin ? 'python' : 'python3', args: ['-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1'], cwd: repo }
}

/** 用户可写数据目录：alerts.db、市值快照、报告输出等落在这里 */
function userDataDir() {
  const dir = path.join(app.getPath('userData'), 'data')
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

// ---------- 工具 ----------
function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port
      srv.close(() => resolve(port))
    })
  })
}

function waitForHealth(port, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const ping = () => {
      const req = http.get({ host: '127.0.0.1', port, path: '/health', timeout: 3000 }, (res) => {
        res.resume()
        if (res.statusCode === 200) return resolve(true)
        retry()
      })
      req.on('error', retry)
      req.on('timeout', () => { req.destroy(); retry() })
    }
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error('后端启动超时（120s）'))
      setTimeout(ping, 400)
    }
    ping()
  })
}

function killBackend() {
  if (!backend || backend.killed) return
  const pid = backend.pid
  try {
    if (isWin) {
      spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore' })
    } else {
      try {
        process.kill(-pid, 'SIGTERM')
      } catch {
        process.kill(pid, 'SIGTERM')
      }
    }
  } catch { /* 忽略 */ }
  backend = null
}

// ---------- 后端 ----------
async function startBackend() {
  backendPort = await freePort()
  const { cmd, args, cwd } = backendCommand()
  const fullArgs = [...args, '--port', String(backendPort)]
  const runtimeDir = path.join(resourcePath('backend'), 'runtime')
  const env = {
    ...process.env,
    RISK_WEB_DIST: webDist(),
    PYTHONIOENCODING: 'utf-8',
    RISK_BACKEND_HOST: '127.0.0.1',
    RISK_BACKEND_PORT: String(backendPort),
    // 只读资产目录（模型产物、面板数据、评分缓存）
    ...(fs.existsSync(runtimeDir) ? { RISK_RUNTIME_DIR: runtimeDir } : {}),
    // 可写数据目录（alerts.db / 市值快照 / 报告）
    RISK_DATA_DIR: userDataDir(),
  }
  console.log('[main] starting backend:', cmd, fullArgs.join(' '))
  backend = spawn(cmd, fullArgs, {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    detached: !isWin,
  })
  backend.stdout.on('data', (d) => console.log('[backend]', String(d).trim()))
  backend.stderr.on('data', (d) => console.error('[backend]', String(d).trim()))
  backend.on('exit', (code) => {
    console.log('[main] backend exited:', code)
    if (!quitting && !SMOKE) {
      dialog.showErrorBox('后端已退出', `后端进程异常退出（code=${code}）。`)
    }
  })
  await waitForHealth(backendPort)
  console.log('[main] backend ready on', backendPort)
}

// ---------- 窗口 ----------
function createWindow() {
  win = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 1080,
    minHeight: 700,
    title: `财务风险智能预警平台 v${app.getVersion()}`,
    backgroundColor: '#0b1220',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  win.loadURL(`http://127.0.0.1:${backendPort}/`)
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://127.0.0.1') || url.startsWith('http://localhost')) return { action: 'allow' }
    shell.openExternal(url)
    return { action: 'deny' }
  })
  win.on('closed', () => { win = null })

  if (SMOKE === '2') {
    win.webContents.on('did-finish-load', async () => {
      try {
        const info = await win.webContents.executeJavaScript(
          `JSON.stringify({ title: document.title, hasApp: !!document.querySelector('#app'), text: (document.body.innerText || '').slice(0, 80) })`,
        )
        console.log('SMOKE_WINDOW_OK ' + info)
      } catch (err) {
        console.log('SMOKE_WINDOW_FAIL ' + err)
      }
      quitting = true
      app.quit()
    })
    win.webContents.on('did-fail-load', (_e, code, desc) => {
      console.log(`SMOKE_WINDOW_FAIL ${code} ${desc}`)
      quitting = true
      app.quit()
    })
  }
  return win
}

function buildMenu() {
  const template = []
  if (isMac) {
    template.push({ role: 'appMenu' })
    template.push({ role: 'editMenu' })
  }
  template.push(
    { label: '文件', submenu: [{ type: 'separator' }, { label: '退出', accelerator: 'CmdOrCtrl+Q', click: () => { quitting = true; app.quit() } }] },
    { label: '视图', submenu: [{ role: 'reload' }, { role: 'forceReload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }] },
  )
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

function createTray() {
  const iconPath = path.join(__dirname, 'build', 'icon.png')
  if (!fs.existsSync(iconPath)) return
  const image = nativeImage.createFromPath(iconPath).resize(isMac ? { width: 18, height: 18 } : { width: 16, height: 16 })
  if (isMac) image.setTemplateImage(true)
  tray = new Tray(image)
  tray.setToolTip('财务风险智能预警平台')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示主窗口', click: () => (win ? (win.show(), win.focus()) : createWindow()) },
    { type: 'separator' },
    { label: '退出', click: () => { quitting = true; app.quit() } },
  ]))
}

// ---------- 生命周期 ----------
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus() }
  })
  app.whenReady().then(async () => {
    try {
      await startBackend()
    } catch (err) {
      dialog.showErrorBox('启动失败', String(err))
      app.quit()
      return
    }
    if (SMOKE === '1') {
      console.log('SMOKE_OK port=' + backendPort)
      quitting = true
      app.quit()
      return
    }
    buildMenu()
    createWindow()
    createTray()
  })
  app.on('window-all-closed', () => { quitting = true; app.quit() })
  app.on('activate', () => { if (!win) createWindow() })
  app.on('before-quit', () => { quitting = true; killBackend() })
  app.on('will-quit', () => killBackend())
  process.on('exit', () => killBackend())
}
