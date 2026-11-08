"""浏览器 UA 池与请求限速参数。

合规提示：爬虫仅采集公开披露信息，请遵守目标站点的 robots.txt 与服务条款，
单域名并发不超过 2、请求间隔不低于 2 秒，避免对站点造成压力。
"""

from __future__ import annotations

import random

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

# 各站点限速配置：请求间隔（秒）与最大并发
RATE_LIMITS = {
    "cninfo": {"delay": 3.0, "concurrency": 2},
    "eastmoney": {"delay": 2.0, "concurrency": 2},
    "qichacha": {"delay": 5.0, "concurrency": 1},
    "stats_gov": {"delay": 1.5, "concurrency": 1},
}


def random_ua() -> str:
    return random.choice(UA_POOL)
