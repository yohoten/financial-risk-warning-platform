"""爬虫基础设施：限速会话、重试、磁盘缓存与 PDF 落盘。

不依赖 Scrapy，使用 requests + 显式限速，好处是：
1. 依赖轻，容器镜像小；
2. 行为可控（每个请求都有间隔、重试与日志），便于在论文中说明合规性；
3. 单文件即可运行，适合答辩现场演示。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import requests

from crawlers.config.user_agents import RATE_LIMITS, random_ua
from etl.io_utils import get_logger

logger = get_logger("crawler")


class RateLimitedSession:
    """带全局限速、重试与 UA 轮换的 HTTP 会话。"""

    def __init__(self, site: str = "cninfo", max_retries: int = 3, timeout: int = 30):
        config = RATE_LIMITS.get(site, {"delay": 2.0, "concurrency": 1})
        self.site = site
        self.delay = config["delay"]
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self._last_request = 0.0

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", random_ua())
        headers.setdefault("Accept-Language", "zh-CN,zh;q=0.9")
        kwargs.setdefault("timeout", self.timeout)

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._wait()
            try:
                resp = self.session.request(method, url, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as exc:  # 网络/HTTP 错误统一重试
                last_error = exc
                logger.warning("[%s] 第 %d/%d 次请求失败：%s", self.site, attempt, self.max_retries, exc)
                time.sleep(self.delay * attempt)
        raise RuntimeError(f"请求失败（已重试 {self.max_retries} 次）：{url}") from last_error

    def get_json(self, url: str, **kwargs) -> dict:
        return self.request("GET", url, **kwargs).json()

    def post_json(self, url: str, data: dict | None = None, **kwargs) -> dict:
        return self.request("POST", url, data=data, **kwargs).json()


def download_file(url: str, save_path: Path, session: RateLimitedSession | None = None) -> Path:
    """流式下载文件（用于年报 PDF），已存在且非空则跳过。"""
    save_path = Path(save_path)
    if save_path.exists() and save_path.stat().st_size > 1024:
        logger.info("已存在，跳过下载：%s", save_path.name)
        return save_path

    session = session or RateLimitedSession("cninfo")
    resp = session.request("GET", url, stream=True)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = save_path.with_suffix(".part")
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    tmp.replace(save_path)

    digest = hashlib.md5(save_path.read_bytes()).hexdigest()
    logger.info("下载完成：%s（%.1f KB, md5=%s）", save_path.name, save_path.stat().st_size / 1024, digest[:8])
    return save_path
