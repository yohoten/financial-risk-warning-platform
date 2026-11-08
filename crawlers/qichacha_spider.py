"""企查查司法/合规风险爬虫（官方 API 模式）。

为什么不用 Selenium 直接爬页面
------------------------------
1. 页面反爬强度高（验证码、登录态、字体混淆），单人维护成本过高；
2. 司法数据涉及个人信息合规，官方 API 有明确授权边界，更适合学术研究；
3. API 返回结构化 JSON，无需解析 DOM，稳定性高一个数量级。

没有 API Key 时的替代方案（已在文档中说明）：
- 国家企业信用信息公示系统（免费，但需人工核验）
- 中国裁判文书网（公开检索）
- 巨潮资讯网"重大诉讼/仲裁"公告（结构化程度最好）

用法
----
    set QICHACHA_KEY=your_key
    python -m crawlers.qichacha_spider --codes 600000 600002
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time

import pandas as pd

from config import settings
from crawlers.base import RateLimitedSession
from etl.io_utils import get_logger, write_table

logger = get_logger("qichacha")

BASE_URL = "https://api.qichacha.com"


def _sign(key: str) -> dict:
    """企查查签名：Token = md5(key + timespan) 大写，timespan 为秒级时间戳。"""
    timespan = str(int(time.time()))
    token = hashlib.md5((key + timespan).encode("utf-8")).hexdigest().upper()
    return {"Token": token, "Timespan": timespan}


class QichachaClient:
    """最小可用的企查查 API 客户端。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("QICHACHA_KEY", "")
        self.session = RateLimitedSession("qichacha")
        if not self.api_key:
            logger.warning("未配置 QICHACHA_KEY，将只能生成空结果（参考 README 的替代数据源）")

    def _get(self, path: str, **params) -> dict:
        if not self.api_key:
            return {"Status": "error", "Message": "missing api key"}
        headers = {**_sign(self.api_key), "Content-Type": "application/json"}
        resp = self.session.request("GET", f"{BASE_URL}{path}",
                                    params={"key": self.api_key, **params}, headers=headers)
        return resp.json()

    def judicial_risk(self, company_name: str) -> dict:
        """司法风险：被执行人、失信、限制高消费、裁判文书统计。"""
        return self._get("/JudicialRisk/GetList", searchKey=company_name, pageIndex=1, pageSize=20)

    def penalties(self, company_name: str) -> dict:
        """行政处罚记录。"""
        return self._get("/AdministrativePenalty/GetList", searchKey=company_name, pageIndex=1, pageSize=20)


def crawl(codes: list[str], names: dict[str, str] | None = None) -> pd.DataFrame:
    """采集司法与处罚记录；无 Key 时输出结构正确的空表。"""
    names = names or {}
    client = QichachaClient()
    rows = []
    for code in codes:
        name = names.get(code, code)
        try:
            judicial = client.judicial_risk(name)
            penalty = client.penalties(name)
        except Exception as exc:
            logger.error("%s 采集失败：%s", code, exc)
            continue

        data = judicial.get("Result") or []
        rows.append(
            {
                "stock_code": code.zfill(6),
                "company_name": name,
                "litigation_count": len(data),
                "penalty_count": len(penalty.get("Result") or []),
                "crawled_at": time.strftime("%Y-%m-%d"),
                "status": judicial.get("Status", "unknown"),
            }
        )

    df = pd.DataFrame(rows)
    out = write_table(df, settings.RAW_DIR / "legal_events_api.csv")
    logger.info("司法风险数据已写出：%s（%d 行）", settings.rel(out), len(df))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="企查查司法风险采集")
    parser.add_argument("--codes", nargs="+", required=True)
    args = parser.parse_args()
    crawl(args.codes)


if __name__ == "__main__":
    main()
