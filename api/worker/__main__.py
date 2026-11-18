"""``python -m api.worker``：启动后台数据拉取 worker（定时 pull + 闭环）。"""

from __future__ import annotations

import time


def main() -> None:
    from api.worker.scheduler import start_worker

    sched = start_worker()
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown(wait=False)


if __name__ == "__main__":
    main()
