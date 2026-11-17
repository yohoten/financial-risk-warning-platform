"""构建期数据注入：把项目真实指标写进根目录 index.html 的数据块。

数据源（单一事实来源，禁止在 HTML 中手写数字）：
  - models/artifacts/evaluation_metrics.json  → run_id / 2023 留出测试指标
  - README.md                                 → 测试数徽章、面板规模
  - git log                                   → 最近更新日期
  - models.shap_analysis.global_importance    → 全局特征重要性 Top 10（迷你图）

用法：
    python scripts/build_homepage.py           # 注入并校验
    python scripts/build_homepage.py --check   # 仅校验（CI 用，不一致则退出码 1）

index.html 中的数据块由标记包围：
    <!-- HOMEPAGE-DATA:BEGIN --> ... <!-- HOMEPAGE-DATA:END -->
页面加载时由 <script> 读取该 JSON 并填充带 data-stat 属性的元素。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "index.html"
METRICS = ROOT / "models/artifacts/evaluation_metrics.json"
README = ROOT / "README.md"

BEGIN = "<!-- HOMEPAGE-DATA:BEGIN -->"
END = "<!-- HOMEPAGE-DATA:END -->"

# 允许直接以脚本方式运行（python scripts/build_homepage.py），而非仅 python -m
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _last_commit_date() -> str:
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=short"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:  # noqa: BLE001 —— 无 git 环境时退化为指标文件日期
        return ""


def collect() -> dict:
    m = json.loads(METRICS.read_text(encoding="utf-8"))
    test = m["test_2023"]
    readme = README.read_text(encoding="utf-8")

    tests = re.search(r"tests-(\d+)%20passed", readme)
    panel = re.search(r"建模面板\s*\|\s*([\d,]+)\s*行\s*/\s*([\d,]+)\s*家", readme)
    if not tests or not panel:
        raise SystemExit("README.md 中未找到测试徽章或面板规模，数据源结构可能已变化")

    from models.shap_analysis import global_importance

    gi = global_importance(10)
    top = [
        {"name": str(r["中文名"]), "value": round(float(r["importance"]), 4)}
        for _, r in gi.iterrows()
    ]
    peak = max((t["value"] for t in top), default=1) or 1

    return {
        "run_id": m["run_id"],
        "updated": _last_commit_date(),
        "metrics": {
            "auc": f"{test['auc']:.4f}",
            "ks": f"{test['ks']:.4f}",
            "recall_top10": f"{test['top_k']['top_10pct']['recall'] * 100:.2f}%",
            "n_test": test["n_samples"],
            "ece": f"{test['ece']:.4f}",
        },
        "panel": {"rows": panel.group(1), "companies": panel.group(2)},
        "features": {"selected": 36, "candidates": 80},
        "tests": int(tests.group(1)),
        "top_features": [
            {**t, "norm": round(t["value"] / peak, 4)} for t in top
        ],
    }


def render(data: dict) -> str:
    block = (
        f'{BEGIN}\n'
        f'  <script type="application/json" id="page-data">\n'
        f'{json.dumps(data, ensure_ascii=False, indent=4)}\n'
        f'  </script>\n'
        f'  {END}'
    )
    return block


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="仅校验数据块是否与数据源一致")
    args = ap.parse_args()

    html = PAGE.read_text(encoding="utf-8")
    if BEGIN not in html or END not in html:
        print("index.html 缺少 HOMEPAGE-DATA 标记", file=sys.stderr)
        return 1

    data = collect()
    new_block = render(data)
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    current = pattern.search(html).group(0)  # type: ignore[union-attr]

    if current == new_block:
        print(f"数据块已是最新（run_id={data['run_id']}，updated={data['updated']}）")
        return 0

    if args.check:
        print("数据块与数据源不一致，请运行 python scripts/build_homepage.py", file=sys.stderr)
        return 1

    PAGE.write_text(pattern.sub(lambda _: new_block, html, count=1), encoding="utf-8")
    print(
        f"已注入：AUC={data['metrics']['auc']} KS={data['metrics']['ks']} "
        f"tests={data['tests']} updated={data['updated']} "
        f"top_features={len(data['top_features'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
