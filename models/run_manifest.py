"""训练运行清单：把数据、特征、参数、指标、阈值与环境写入 run_manifest.json。

目的：任何一次训练都能追溯到具体的数据文件、特征清单与代码版本，避免
"指标可复现但不知道对应哪份数据/哪次改动"。清单同时按 run_id 归档并追加
历史记录，便于论文附录与答辩现场核对。
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

from config import settings
from etl.io_utils import get_logger, resolve

logger = get_logger("manifest")

MANIFEST_NAME = "run_manifest.json"
HISTORY_NAME = "run_history.jsonl"


def sha256_file(path: Path | str) -> str | None:
    """文件内容指纹；文件不存在返回 None。"""
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def git_state() -> dict:
    """当前 git 分支/提交/是否有未提交改动（非 git 环境返回 unknown）。"""

    def _run(args: list[str]) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=settings.PROJECT_ROOT,
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            return ""

    return {
        "commit": _run(["rev-parse", "--short", "HEAD"]) or "unknown",
        "branch": _run(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown",
        "dirty": bool(_run(["status", "--porcelain"])),
    }


def dataset_state() -> dict:
    """建模输入表（缺失时退回特征面板）的路径、大小与内容指纹。"""
    path = resolve(settings.FEATURE_MATRIX) or resolve(settings.FEATURE_PANEL)
    if path is None:
        return {"path": None, "sha256": None, "bytes": None}
    return {
        "path": settings.rel(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def environment() -> dict:
    """运行环境版本，跨机器复现时用于排查依赖差异。"""
    info = {"python": platform.python_version(), "platform": platform.platform()}
    for pkg in ("xgboost", "scikit-learn", "pandas", "numpy", "shap"):
        try:
            info[pkg] = version(pkg)
        except Exception:
            info[pkg] = "unknown"
    return info


def record_run(
    *,
    run_type: str,
    params: dict,
    metrics: dict,
    threshold: dict | None = None,
    dataset: dict | None = None,
    features: list[str] | None = None,
    extra: dict | None = None,
    out_dir: Path | str | None = None,
) -> dict:
    """生成并落盘运行清单；同时写 `runs/<run_id>.json` 与历史 jsonl。"""
    target = Path(out_dir or settings.ARTIFACT_DIR)
    target.mkdir(parents=True, exist_ok=True)

    state = {**dataset_state(), **(dataset or {})}
    feature_list = list(features or [])
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{(state.get('sha256') or 'nodata')[:8]}"

    manifest = {
        "run_id": run_id,
        "run_type": run_type,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "git": git_state(),
        "dataset": state,
        "features": {"n": len(feature_list), "sha256": _hash_payload(feature_list)},
        "params": params,
        "threshold": threshold,
        "metrics": metrics,
        "environment": environment(),
    }
    if extra:
        manifest.update(extra)

    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    runs_dir = target / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (target / HISTORY_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "run_id": run_id,
            "run_type": run_type,
            "created_at": manifest["created_at"],
            "git_commit": manifest["git"]["commit"],
            "data_sha256": state.get("sha256"),
            "n_features": len(feature_list),
        }, ensure_ascii=False) + "\n")

    logger.info("运行清单已写出：%s（run_id=%s）", settings.rel(target / MANIFEST_NAME), run_id)
    return manifest
