# 桌面端（Electron）

把「FastAPI 后端 + Vue SPA」打成一个可分发的桌面应用，Windows / macOS / Linux 三平台共用同一套代码。

## 架构

```text
┌──────────────────────── Electron 主进程 ────────────────────────┐
│  main.js                                                       │
│   1. 单实例锁 + 动态端口（net.listen(0)）                        │
│   2. 拉起后端 → 轮询 /health 直到就绪                            │
│   3. BrowserWindow 加载 http://127.0.0.1:<port>/               │
│   4. 菜单 / 托盘 / 外链走系统浏览器                              │
│   5. 退出时优雅关闭后端进程树                                   │
└───────────────────────────────────────────────────────────────┘
        │                                   │
        ▼                                   ▼
  FastAPI（api/main.py）            Vue SPA（web/dist）
  自身静态托管前端 → 单一端口即可访问
```

## 后端启动优先级

`main.js` 按以下顺序探测后端：

1. `RWP_BACKEND` 环境变量（显式指定可执行文件或脚本）
2. 打包产物 `resources/backend/risk-backend/risk-backend[.exe]`（PyInstaller 冻结版，自包含）
3. 项目 `.venv` 里的 Python（开发态）
4. 系统 `python` / `python3`（兜底）

健康检查路径是 `/health`（不是旧项目的 `/api/health`）。

## 数据目录约定

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| 只读资产 | `resources/backend/runtime/` | 面板数据、模型产物、评分缓存、SHAP 解释器 |
| 可写资产 | Electron `userData/data/` | `alerts.db`、市值快照、报告输出 |

开发态（未打包）时 `runtime/` 不存在，`config/settings.py` 自动回退到项目目录。

## 构建

```bash
# 一键（Makefile）
make desktop-dist

# 或分步
cd web && npm install && npm run build          # 前端
pip install pyinstaller                          # 后端打包依赖（装进 .venv）
python scripts/build_backend.py                  # 后端 → desktop/resources/backend
cd desktop && npm install && npm run dist        # electron-builder 出安装包
```

产物：

```text
desktop/release/
├── FinancialRiskWarningPlatform-1.0.0-x64-Setup.exe     # nsis 安装包
├── FinancialRiskWarningPlatform-1.0.0-x64-Portable.exe   # 免安装单文件
└── win-unpacked/                                         # 免安装目录
```

## 自检

```bash
cd desktop && npm run smoke          # 仅拉起后端 + 健康检查后退出
cd desktop && npm run smoke:window   # 加载窗口并抓取 DOM 后退出
```

环境变量：

- `RWP_SMOKE=1` — 只做「拉起后端 + 健康检查」，成功后退出（CI 自检）
- `RWP_SMOKE=2` — 加载窗口后抓取 DOM 退出
- `RWP_DEV=1` — 强制使用开发模式
- `RWP_BACKEND` — 指定后端可执行文件路径（覆盖自动探测）

## 打包后端的技术要点

- 由 `scripts/build_backend.py` 调用 PyInstaller 生成 **onedir**（`risk-backend/` 目录 + `risk-backend.exe`）。
- 入口脚本 `_desktop_backend_entry.py` 由构建脚本生成到项目根：**必须静态 import `api` / `config` / `etl` / `models`**，否则 PyInstaller 不会把这些项目包打进产物（`--collect-submodules` 只对已被分析到的包生效）。
- 入口把 `app` 对象直接传给 `uvicorn.run(app, ...)`，避免冻结环境下的字符串二次导入失败。
- 大文件（parquet / pkl）不进 exe，由 `runtime/` 目录携带；`config.settings.rt()` 负责在 runtime/ 与项目目录之间回退。
- **`xgboost.dll` 必须用 `--add-binary` 显式带入**：它是纯数据文件形态的原生库，不是 extension module，静态分析收集不到，缺失时运行时抛 `XGBoostLibraryNotFound`。
- **不要用 `--collect-all xgboost`**：它会递归 `xgboost.testing` 等测试子包，触发 `hypothesis` / `pytest` 缺失而中断构建；用 `--collect-data` + `--add-binary` 组合。
- **PyInstaller 每次构建使用带时间戳的唯一 dist 目录**：构建前 PyInstaller 会尝试删除同名旧目录，在受控环境下大批量删除会被拦截导致构建失败；构建完成后再逐项拷贝到 `desktop/resources/backend/`。
