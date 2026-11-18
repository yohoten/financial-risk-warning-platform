"""PyInstaller 打包 FastAPI 后端为独立可执行文件（Electron 生产形态用）。

目标：让 desktop 产物不依赖目标机安装 Python、不依赖项目源码目录，
      双击即可运行（后端进程由 Electron 主进程拉起）。

用法：
    python scripts/build_backend.py            # 打包到 desktop/resources/backend
    python scripts/build_backend.py --skip-data  # 只打包代码，不拷贝运行时数据资产

产物：
    desktop/resources/backend/risk-backend[.exe]   （PyInstaller onedir 目录）

运行时数据资产（代码外的必要文件）由本脚本拷贝到同一目录的 ``runtime/`` 下，
通过环境变量 ``RISK_RUNTIME_DIR`` 指向；settings 会优先读取该目录。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "desktop" / "resources" / "backend"
# 当前解释器的 site-packages（原生 dll 从这里收集）
SITE_PACKAGES = Path(sys.prefix) / "Lib" / "site-packages"
if not SITE_PACKAGES.exists():
    import site
    SITE_PACKAGES = Path(site.getsitepackages()[0])

# 需要随包携带的运行时数据资产（相对项目根）
RUNTIME_ASSETS = [
    # 财务分析/规则评分的面板数据（parquet）
    "data/cleaned/panel_clean.parquet",
    # Altman X2 所需的留存收益补充表
    "data/raw/candidates/balance_sheet_ext.csv",
    # 模型输入特征矩阵与入选特征
    "data/feature_store/panel_model_input.parquet",
    "data/feature_store/panel_features.parquet",
    "data/feature_store/selected_features.json",
    # 模型产物
    "models/artifacts/xgboost_final.json",
    "models/artifacts/model_meta.json",
    "models/artifacts/calibrator.pkl",
    "models/artifacts/metrics.json",
    # 评分缓存与 SHAP 解释器
    "cache/predictions.parquet",
    "cache/predictions_meta.json",
    "cache/shap_explainer.pkl",
    "cache/shap_values.pkl",
]

# 需显式带入产物的原生 dll（非 extension module 形态，静态分析收集不到）
# 格式：(site-packages 相对路径, 产物内目标目录)
ADD_BINARY_PATTERNS = [
    ("xgboost/lib/xgboost.dll", "xgboost/lib"),
    ("sklearn/.libs/vcomp140.dll", "sklearn/.libs"),
]

HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "sklearn.utils._cython",
    "xgboost",
    "shap",
    "joblib",
    "pyarrow",
    "akshare",
    # 平台扩展包（对话 / 表格 / MCP / 技能等；api.main 静态导入会被跟随，
    # 此处显式列出避免部分动态 import 被漏收集）
    "api.db",
    "api.agent",
    "api.agent.tools",
    "api.agent.loop",
    "api.agent.session",
    "api.mcp",
    "api.mcp.service",
    "api.llm",
    "api.llm.preheat",
    "api.routers",
]


def _build_entry() -> Path:
    """生成 PyInstaller 入口脚本（冻结后的可执行文件直接起 uvicorn）。

    关键点：PyInstaller 只跟踪**静态 import**。入口必须直接 import 项目包，
    否则 api/config/etl/models 不会被打进产物（--collect-submodules 也不会生效，
    因为它只对已被分析到的包起作用）。
    """
    entry = ROOT / "_desktop_backend_entry.py"
    entry.write_text(
        '''"""PyInstaller 冻结入口：启动内置 uvicorn 服务。

由 scripts/build_backend.py 生成，勿手工编辑。
"""
import os
import sys


def main() -> int:
    # 冻结环境没有 CWD 依赖，必须把包根加入 sys.path
    root = os.environ.get("RISK_BACKEND_ROOT") or getattr(sys, "_MEIPASS", os.getcwd())
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        import uvicorn
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("import uvicorn failed: %r\\n" % (exc,))
        return 2

    try:
        # 静态 import：让 PyInstaller 分析到全部项目包
        import api  # noqa: F401
        import config  # noqa: F401
        import etl  # noqa: F401
        import models  # noqa: F401
        from api.main import app
    except Exception as exc:  # noqa: BLE001
        import traceback
        sys.stderr.write("import api.main failed: %r\\n" % (exc,))
        traceback.print_exc()
        return 3

    host = os.environ.get("RISK_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("RISK_BACKEND_PORT", "8000"))
    # 直接传 app 对象，避免 uvicorn 以字符串形式二次导入
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )
    return entry
    return entry


def _copy_runtime_assets(skip_data: bool) -> int:
    """拷贝运行时数据资产到 runtime/ 目录（覆盖同名文件，不整目录删除）。"""
    if skip_data:
        print("[build-backend] --skip-data：跳过运行时数据资产拷贝")
        return 0
    runtime = OUT_DIR / "runtime"
    copied, missing = 0, []
    for rel in RUNTIME_ASSETS:
        src = ROOT / rel
        if not src.exists():
            missing.append(rel)
            continue
        dst = runtime / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    print(f"[build-backend] 运行时数据资产：拷贝 {copied} 个")
    if missing:
        print(f"[build-backend] 缺失（不影响构建，但相关功能不可用）：{', '.join(missing)}")
    return copied


def _copy_tree(src: Path, dst: Path) -> None:
    """递归拷贝目录（覆盖同名文件），不做整目录删除。"""
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-data", action="store_true", help="只打包代码，不拷贝运行时数据资产")
    ap.add_argument("--clean", action="store_true", help="打包前清理 build/dist 目录")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[build-backend] 需要 PyInstaller：pip install pyinstaller", file=sys.stderr)
        return 1

    entry = _build_entry()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # PyInstaller 构建前会删除同名 dist 目录；在受控环境下目录删除被安全策略
    # 拦截会导致构建失败，因此每次用唯一的时间戳目录，构建完再拷贝到 OUT_DIR。
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dist_dir = ROOT / "build" / f"pyinstaller-dist-{stamp}"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--name", "risk-backend",
        "--distpath", str(dist_dir),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build" / "pyinstaller"),
        "--paths", str(ROOT),
        # 收集包数据（非 .py 文件）
        "--collect-data", "config",
        "--collect-data", "api",
        "--collect-data", "etl",
        "--collect-data", "models",
        # 含原生二进制的科学计算包：xgboost.dll / shap 的 .so 必须一并收集，
        # 否则冻结产物运行时抛 XGBoostLibraryNotFound。
        # 注意用 --collect-data 而非 --collect-all：后者会递归 xgboost.testing
        # 等测试子包，触发 hypothesis/pytest 缺失而中断构建。
        "--collect-data", "xgboost",
        "--collect-data", "shap",
        "--collect-data", "sklearn",
        "--collect-data", "scipy",
        # akshare 供 /enterprise/{code}/refresh 拉取公开财报与市值快照
        "--collect-data", "akshare",
        "--collect-submodules", "akshare",
    ]
    # 非模块形态的原生 dll（extension module 会被静态分析自动收集，此处补的是
    # 纯数据文件形态的 dll，如 xgboost/lib/xgboost.dll）
    for rel, dest in ADD_BINARY_PATTERNS:
        src = SITE_PACKAGES / rel
        if src.exists():
            cmd += ["--add-binary", f"{src};{dest}"]
        else:
            print(f"[build-backend] 警告：未找到原生库 {src}，已跳过")
    # 显式列出项目子模块：PyInstaller 只跟踪静态 import，
    # 入口脚本已静态 import 顶层包，这里再逐个列出子模块保证完整。
    for pkg in ("api", "config", "etl", "models"):
        cmd += ["--collect-submodules", pkg]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    # 大文件依赖不打包，改为运行时从 runtime/ 读取
    cmd += [
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "streamlit",
        "--exclude-module", "notebook",
    ]
    cmd.append(str(entry))

    print("[build-backend] 执行 PyInstaller…")
    print("[build-backend]", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        print(f"[build-backend] PyInstaller 失败（exit={proc.returncode}）", file=sys.stderr)
        return proc.returncode

    # 搬到 desktop/resources/backend/
    # 不用 shutil.rmtree 整目录删除（受控环境可能拦截大批量删除），
    # 逐项覆盖拷贝即可达到等效效果。
    built = dist_dir / "risk-backend"
    if not built.exists():
        print("[build-backend] 未找到构建产物：", built, file=sys.stderr)
        return 4
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _copy_tree(built, OUT_DIR / "risk-backend")

    _copy_runtime_assets(args.skip_data)
    entry.unlink(missing_ok=True)

    exe = OUT_DIR / "risk-backend" / ("risk-backend.exe" if os.name == "nt" else "risk-backend")
    print(f"[build-backend] 完成：{exe}")
    print(f"[build-backend] 运行时数据：{OUT_DIR / 'runtime'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
