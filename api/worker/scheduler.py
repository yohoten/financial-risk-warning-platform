"""后台 worker：APScheduler 定时拉取（pull 通道）。

任务清单来自 ``data_source_config.schedule_cron``（enabled=1 且 cron 非空），
每任务执行 ``pipeline.run_pull_dimension``。单机多副本去重由 P4 的 Redis 锁负责。
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

try:  # 项目其余模块用 loguru；缺失时退化为标准库
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("api.worker")


def _enabled_configs() -> list[dict]:
    from api.db.database import query

    return query("SELECT * FROM data_source_config WHERE enabled=1 AND schedule_cron!=''")


def build_scheduler() -> BackgroundScheduler:
    from api.worker.pipeline import run_pull_dimension

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    added = 0
    for cfg in _enabled_configs():
        dim = cfg["dimension"]
        name = cfg["source_name"]
        task_name = f"pull_{dim}_{name}"
        try:
            sched.add_job(
                run_pull_dimension,
                CronTrigger.from_crontab(cfg["schedule_cron"]),
                args=[dim, name, task_name],
                id=task_name,
                replace_existing=True,
                misfire_grace_time=300,
            )
            added += 1
            logger.info("已注册定时拉取任务 {}：{} / {}（cron={}）",
                        task_name, dim, name, cfg["schedule_cron"])
        except Exception as exc:  # noqa: BLE001 —— 单条 cron 非法不阻断整体
            logger.warning("注册定时任务失败 {}：{}", task_name, exc)

    logger.info("数据拉取 worker 就绪，共注册 {} 个定时任务", added)
    return sched


def start_worker() -> BackgroundScheduler:
    sched = build_scheduler()
    sched.start()
    return sched
