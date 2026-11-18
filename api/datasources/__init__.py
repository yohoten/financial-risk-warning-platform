"""数据源执行层（pull 通道）。

移植自旧项目 `server/app/datasources/`（registry.py + 三个具体源），按本项目的
裸 sqlite3 存储（``api/db/database.py``）与 `api/ingest` 事件总线适配。

与 `api/services/datasources.py`（状态声明 + 单企业市值刷新）的关系：
本包补齐"执行 + 幂等入库"两半，供 worker 定时拉取与手工触发使用。
"""
