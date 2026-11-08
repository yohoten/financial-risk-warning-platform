"""Streamlit 页面冒烟测试：用官方 AppTest 逐页执行脚本，捕获异常。

不启动浏览器与服务，适合 CI 或提交前自检：
    python -m scripts.smoke_streamlit
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

PAGES = [
    "streamlit_app/app.py",
    "streamlit_app/pages/1_数据看板.py",
    "streamlit_app/pages/2_企业诊断.py",
    "streamlit_app/pages/3_批量预警.py",
    "streamlit_app/pages/4_模型解释.py",
    "streamlit_app/pages/5_报告导出.py",
]


def run_all(timeout: int = 120) -> int:
    failed = 0
    for page in PAGES:
        path = ROOT / page
        if not path.exists():
            print(f"[SKIP] 文件不存在：{page}")
            continue
        at = AppTest.from_file(str(path), default_timeout=timeout)
        try:
            at.run()
        except Exception as exc:  # 脚本级异常
            print(f"[FAIL] {page} → {type(exc).__name__}: {exc}")
            failed += 1
            continue

        if at.exception:
            for exc in at.exception:
                print(f"[FAIL] {page} → {exc.value}")
            failed += 1
        else:
            print(f"[ OK ] {page}（元素 {len(at)} 个）")
    print(f"\n结果：{len(PAGES) - failed}/{len(PAGES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_all())
