"""清理项目冗余产物：构建依赖、缓存、备份、陈旧数据（跨平台、可复现）。

设计原则
--------
- 只删除「可再生或明确冗余」的产物，绝不触碰：
    * 原始契约数据（``data/raw`` 当前表、``data/incoming`` 暂存/批次归档）
    * 模型权重（``models/artifacts`` 的 ``xgboost_final.json``、``runs/`` 快照）
    * 虚拟环境（``.venv``）与源码/文档
- 默认 dry-run，仅打印将删除项与可回收空间；加 ``--write`` 才真正删除。
- 所有目标均按类别组织，可精细跳过。

用法
----
.. code-block:: bash

    python -m scripts.clean_project                  # 预演
    python -m scripts.clean_project --write          # 执行
    python -m scripts.clean_project --write --no-pycache      # 跳过 __pycache__/.pyc
    python -m scripts.clean_project --write --staging-unzip   # 额外清理暂存区解压临时目录
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 排除目录：不进入扫描（虚拟环境 / 前端依赖 / git 元数据）
EXCLUDED_DIRS = {".venv", "venv", "env", "node_modules", ".git", ".codebuddy", ".workbuddy"}

# 构建产物与运行时依赖（npm install / pip 打包 / 前端 build 可再生）
BUILD_ARTIFACTS: list[str] = [
    "desktop/node_modules",
    "web/node_modules",
    "web/dist",
    "desktop/release",
    "desktop/resources/backend",
    "desktop/resources/web",
    "build",
    "catboost_info",
    "cachedir",
    "browser",
]

# 冗余备份：脚本覆盖前自动生成的 .bak_*、显式 backup 文件、陈旧版本目录
BACKUP_TARGETS: list[str] = [
    "data/raw/**/*.bak_*",
    "data/raw/ST_events_proxy_backup.csv",
    "data/feature_store/_stale",
]

# 临时/一次性文件
TEMP_TARGETS: list[str] = [
    ".trash",
    "exec-approvals.json",
    "ps-exe.txt",
]

# 可选：暂存区解压临时目录（与 _archives 压缩包重复，体积大，需显式开启）
STAGING_UNZIP_PATTERNS: list[str] = [
    "data/incoming/csmar/*/_unzip",
]


def _path_size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _onerror(func, path, exc_info):  # pragma: no cover - Windows 只读文件兜底
    """Windows 下 node_modules 常含只读文件，先清只读位再重试。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _rmtree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, onerror=_onerror)
    elif path.is_file() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass


def collect_globs(patterns: list[str]) -> list[Path]:
    """按 glob 展开，仅返回真实存在且位于项目根内的路径。"""
    found: list[Path] = []
    for pat in patterns:
        for p in glob.glob(str(ROOT / pat), recursive=True):
            path = Path(p)
            if path.exists() and path != ROOT:
                found.append(path)
    # 去重并保持稳定顺序（父目录优先，避免重复统计）
    return sorted(set(found), key=lambda p: (str(p),))


def collect_pycache() -> list[Path]:
    """扫描 __pycache__ 目录与 .pyc/.pyo 文件（跳过 EXCLUDED_DIRS）。"""
    targets: list[Path] = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        if Path(root).name == "__pycache__":
            targets.append(Path(root))
            dirs[:] = []
            continue
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                targets.append(Path(root) / f)
    # .pytest_cache 也属缓存
    p = ROOT / ".pytest_cache"
    if p.exists():
        targets.append(p)
    return targets


def build_plan(args: argparse.Namespace) -> dict[str, list[tuple[Path, int]]]:
    plan: dict[str, list[tuple[Path, int]]] = {}

    plan["构建产物/依赖"] = [(p, _path_size(p)) for p in collect_globs(BUILD_ARTIFACTS)]
    plan["冗余备份/陈旧数据"] = [(p, _path_size(p)) for p in collect_globs(BACKUP_TARGETS)]
    plan["临时文件"] = [(p, _path_size(p)) for p in collect_globs(TEMP_TARGETS)]

    if not args.no_pycache:
        plan["Python 缓存"] = [(p, _path_size(p)) for p in collect_pycache()]

    if args.staging_unzip:
        plan["暂存区解压临时目录"] = [(p, _path_size(p)) for p in collect_globs(STAGING_UNZIP_PATTERNS)]

    return {k: v for k, v in plan.items() if v}


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> int:
    parser = argparse.ArgumentParser(description="清理项目冗余产物（默认预演）")
    parser.add_argument("--write", action="store_true", help="真正删除（默认仅预演）")
    parser.add_argument("--no-pycache", action="store_true", help="跳过 __pycache__/.pyc 清理")
    parser.add_argument("--staging-unzip", action="store_true", help="额外清理 data/incoming 的解压临时目录")
    args = parser.parse_args()

    plan = build_plan(args)
    if not plan:
        print("没有发现需要清理的冗余产物。")
        return 0

    total = 0
    total_count = 0
    print(f"{'预演' if not args.write else '清理'}目标（项目根：{ROOT}）：\n")
    for category, items in plan.items():
        cat_size = sum(s for _, s in items)
        print(f"【{category}】{len(items)} 项，共 {human(cat_size)}")
        for p, s in items:
            rel = p.relative_to(ROOT)
            print(f"  - {rel}  ({human(s)})")
        total += cat_size
        total_count += len(items)
        print()

    print(f"合计 {total_count} 项，可回收 {human(total)}。")
    if not args.write:
        print("未删除任何文件（dry-run）。确认后执行：python -m scripts.clean_project --write")
        return 0

    for category, items in plan.items():
        for p, _ in items:
            try:
                _rmtree(p)
            except OSError as e:
                print(f"  删除失败：{p}（{e}）", file=sys.stderr)

    print("清理完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
